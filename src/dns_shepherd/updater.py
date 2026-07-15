from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence


DEFAULT_CONFIG = Path("/etc/dns-shepherd/config.toml")
SUPPORTED_CHECKS = {"tcp"}
DEFAULT_UPDATE_ADAPTER = "bind_nsupdate"
SUPPORTED_UPDATE_ADAPTERS = {DEFAULT_UPDATE_ADAPTER}


class ConfigError(ValueError):
    """Raised when a config file is not safe to use."""


class UpdateError(RuntimeError):
    """Raised when a DNS update command fails."""


@dataclass(frozen=True)
class Deployment:
    site_id: str
    zone: str
    dns_server: str
    key_file: str
    update_adapter: str = DEFAULT_UPDATE_ADAPTER


@dataclass(frozen=True)
class Defaults:
    ttl: int = 30
    check_timeout_seconds: float = 2.0
    retain_last_known_good: bool = True


@dataclass(frozen=True)
class Candidate:
    name: str
    address: str
    check: str
    port: int


@dataclass(frozen=True)
class Host:
    host_id: str
    enabled: bool
    record: str
    ttl: int
    candidates: tuple[Candidate, ...]
    diagnostic_records: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class Config:
    deployment: Deployment
    defaults: Defaults
    hosts: tuple[Host, ...]


@dataclass(frozen=True)
class HostPlan:
    site_id: str
    zone: str
    host_id: str
    record: str
    current_addresses: tuple[str, ...]
    selected_candidate: str | None
    selected_address: str | None
    action: str
    ttl: int


HealthChecker = Callable[[Candidate, float], bool]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class DnsUpdateAdapter(Protocol):
    def current_addresses(self, record: str) -> tuple[str, ...]:
        """Return the current A answers for a managed record."""

    def apply(self, plan: HostPlan) -> None:
        """Apply one planned DNS update."""


class BindNsupdateAdapter:
    def __init__(
        self,
        deployment: Deployment,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.deployment = deployment
        self.runner = runner

    def current_addresses(self, record: str) -> tuple[str, ...]:
        return query_current_addresses(self.deployment.dns_server, record, self.runner)

    def apply(self, plan: HostPlan) -> None:
        run_bind_nsupdate(self.deployment, plan, self.runner)


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"cannot parse config {path}: {exc}") from exc

    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> Config:
    deployment_raw = require_table(raw, "deployment")
    defaults_raw = raw.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        raise ConfigError("defaults must be a TOML table")

    deployment = Deployment(
        site_id=require_string(deployment_raw, "site_id", "deployment"),
        zone=normalize_zone(require_string(deployment_raw, "zone", "deployment")),
        dns_server=require_string(deployment_raw, "dns_server", "deployment"),
        key_file=require_string(deployment_raw, "key_file", "deployment"),
        update_adapter=optional_string(
            deployment_raw, "update_adapter", "deployment"
        )
        or DEFAULT_UPDATE_ADAPTER,
    )
    if deployment.update_adapter not in SUPPORTED_UPDATE_ADAPTERS:
        raise ConfigError(
            "deployment.update_adapter must be one of: "
            f"{', '.join(sorted(SUPPORTED_UPDATE_ADAPTERS))}"
        )

    defaults = Defaults(
        ttl=require_positive_int(defaults_raw, "ttl", "defaults", default=30),
        check_timeout_seconds=require_positive_number(
            defaults_raw, "check_timeout_seconds", "defaults", default=2.0
        ),
        retain_last_known_good=require_bool(
            defaults_raw, "retain_last_known_good", "defaults", default=True
        ),
    )

    hosts_raw = raw.get("hosts", {})
    if not isinstance(hosts_raw, dict):
        raise ConfigError("hosts must be a TOML table")

    hosts: list[Host] = []
    managed_records: dict[str, str] = {}
    for host_id, host_raw in sorted(hosts_raw.items()):
        if not isinstance(host_raw, dict):
            raise ConfigError(f"hosts.{host_id} must be a TOML table")

        enabled = require_bool(host_raw, "enabled", f"hosts.{host_id}", default=True)
        record = optional_string(host_raw, "record", f"hosts.{host_id}") or ""
        ttl = require_positive_int(host_raw, "ttl", f"hosts.{host_id}", default=defaults.ttl)
        diagnostic_records = require_string_list(
            host_raw, "diagnostic_records", f"hosts.{host_id}", default=()
        )
        description = optional_string(host_raw, "description", f"hosts.{host_id}") or ""

        candidates_raw = host_raw.get("candidates", [])
        if not isinstance(candidates_raw, list):
            raise ConfigError(f"hosts.{host_id}.candidates must be a TOML array")

        candidates = tuple(parse_candidate(host_id, index, item) for index, item in enumerate(candidates_raw))

        if enabled:
            if not record:
                raise ConfigError(f"hosts.{host_id}.record is required when enabled")
            if not candidates:
                raise ConfigError(f"hosts.{host_id} is enabled but has no candidates")
            fqdn = record_fqdn(record, deployment.zone)
            if fqdn in managed_records:
                other = managed_records[fqdn]
                raise ConfigError(
                    f"hosts.{host_id} and hosts.{other} both manage {fqdn}"
                )
            managed_records[fqdn] = host_id

        hosts.append(
            Host(
                host_id=host_id,
                enabled=enabled,
                record=record,
                ttl=ttl,
                candidates=candidates,
                diagnostic_records=diagnostic_records,
                description=description,
            )
        )

    return Config(deployment=deployment, defaults=defaults, hosts=tuple(hosts))


def parse_candidate(host_id: str, index: int, raw: Any) -> Candidate:
    context = f"hosts.{host_id}.candidates[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{context} must be a TOML table")

    name = require_string(raw, "name", context)
    address = require_string(raw, "address", context)
    try:
        ipaddress.ip_address(address)
    except ValueError as exc:
        raise ConfigError(f"{context}.address is not a valid IP address: {address}") from exc

    check = require_string(raw, "check", context)
    if check not in SUPPORTED_CHECKS:
        raise ConfigError(f"{context}.check must be one of: {', '.join(sorted(SUPPORTED_CHECKS))}")

    port = require_positive_int(raw, "port", context)
    if port > 65535:
        raise ConfigError(f"{context}.port must be between 1 and 65535")

    return Candidate(name=name, address=address, check=check, port=port)


def require_table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a TOML table")
    return value


def require_string(raw: dict[str, Any], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def optional_string(raw: dict[str, Any], key: str, context: str) -> str | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, str):
        raise ConfigError(f"{context}.{key} must be a string")
    return value.strip()


def require_positive_int(
    raw: dict[str, Any], key: str, context: str, default: int | None = None
) -> int:
    if key not in raw:
        if default is None:
            raise ConfigError(f"{context}.{key} is required")
        return default
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{context}.{key} must be a positive integer")
    return value


def require_positive_number(
    raw: dict[str, Any], key: str, context: str, default: float
) -> float:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{context}.{key} must be a positive number")
    return float(value)


def require_bool(raw: dict[str, Any], key: str, context: str, default: bool) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{context}.{key} must be true or false")
    return value


def require_string_list(
    raw: dict[str, Any], key: str, context: str, default: Sequence[str]
) -> tuple[str, ...]:
    if key not in raw:
        return tuple(default)
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ConfigError(f"{context}.{key} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def normalize_zone(zone: str) -> str:
    return zone.strip().rstrip(".").lower()


def record_fqdn(record: str, zone: str) -> str:
    clean = record.strip().lower()
    if not clean:
        raise ConfigError("record must be non-empty")
    if clean.endswith("."):
        return clean
    normalized_zone = normalize_zone(zone)
    if clean == normalized_zone or clean.endswith(f".{normalized_zone}"):
        return f"{clean}."
    if "." in clean:
        return f"{clean}."
    return f"{clean}.{normalized_zone}."


def tcp_health_check(candidate: Candidate, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((candidate.address, candidate.port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def plan_updates(
    config: Config,
    health_checker: HealthChecker = tcp_health_check,
    runner: CommandRunner = subprocess.run,
    include_current_dns: bool = True,
    dns_adapter: DnsUpdateAdapter | None = None,
) -> list[HostPlan]:
    adapter = dns_adapter or dns_update_adapter(config.deployment, runner)
    plans: list[HostPlan] = []
    for host in config.hosts:
        if not host.enabled:
            continue

        selected = first_reachable_candidate(host, config.defaults.check_timeout_seconds, health_checker)
        fqdn = record_fqdn(host.record, config.deployment.zone)
        current_addresses: tuple[str, ...] = ()
        if include_current_dns:
            current_addresses = adapter.current_addresses(fqdn)

        if selected is None:
            action = "retain"
        elif tuple(current_addresses) == (selected.address,):
            action = "unchanged"
        else:
            action = "update"

        plans.append(
            HostPlan(
                site_id=config.deployment.site_id,
                zone=config.deployment.zone,
                host_id=host.host_id,
                record=fqdn,
                current_addresses=current_addresses,
                selected_candidate=selected.name if selected else None,
                selected_address=selected.address if selected else None,
                action=action,
                ttl=host.ttl,
            )
        )
    return plans


def first_reachable_candidate(
    host: Host, timeout_seconds: float, health_checker: HealthChecker
) -> Candidate | None:
    for candidate in host.candidates:
        if health_checker(candidate, timeout_seconds):
            return candidate
    return None


def query_current_addresses(
    dns_server: str, record: str, runner: CommandRunner = subprocess.run
) -> tuple[str, ...]:
    result = runner(
        ["dig", f"@{dns_server}", "+short", record, "A"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise UpdateError(f"dig failed for {record}: {result.stderr.strip()}")
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def apply_updates(
    config: Config,
    plans: Iterable[HostPlan],
    runner: CommandRunner = subprocess.run,
    dns_adapter: DnsUpdateAdapter | None = None,
) -> list[HostPlan]:
    adapter = dns_adapter or dns_update_adapter(config.deployment, runner)
    changed: list[HostPlan] = []
    for plan in plans:
        if plan.action != "update":
            continue
        if not plan.selected_address:
            continue
        adapter.apply(plan)
        changed.append(plan)
    return changed


def dns_update_adapter(
    deployment: Deployment,
    runner: CommandRunner = subprocess.run,
) -> DnsUpdateAdapter:
    if deployment.update_adapter == "bind_nsupdate":
        return BindNsupdateAdapter(deployment, runner)
    raise ConfigError(f"unsupported DNS update adapter: {deployment.update_adapter}")


def run_nsupdate(config: Config, plan: HostPlan, runner: CommandRunner = subprocess.run) -> None:
    run_bind_nsupdate(config.deployment, plan, runner)


def run_bind_nsupdate(
    deployment: Deployment,
    plan: HostPlan,
    runner: CommandRunner = subprocess.run,
) -> None:
    key_args, key_command = nsupdate_key_material(deployment.key_file)
    commands = [
        f"server {deployment.dns_server}",
        f"zone {deployment.zone}",
        f"update delete {plan.record} A",
        f"update add {plan.record} {plan.ttl} A {plan.selected_address}",
        "send",
        "",
    ]
    if key_command:
        commands.insert(0, key_command)
    payload = "\n".join(commands)
    result = runner(
        ["nsupdate", *key_args],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"nsupdate failed for {plan.record}: {detail}")


def nsupdate_key_material(key_file: str) -> tuple[list[str], str | None]:
    bind_key = parse_bind_key_file(Path(key_file))
    if bind_key:
        name, algorithm, secret = bind_key
        return [], f"key {algorithm}:{name} {secret}"
    return ["-k", key_file], None


def parse_bind_key_file(path: Path) -> tuple[str, str, str] | None:
    try:
        text = path.read_text()
    except OSError:
        return None

    match = re.search(
        r'key\s+"(?P<name>[^"]+)"\s*\{(?P<body>.*?)\};',
        text,
        flags=re.DOTALL,
    )
    if not match:
        return None

    body = match.group("body")
    algorithm = re.search(r"\balgorithm\s+(?P<value>[A-Za-z0-9_-]+)\s*;", body)
    secret = re.search(r'\bsecret\s+"(?P<value>[^"]+)"\s*;', body)
    if not algorithm or not secret:
        return None

    return match.group("name"), algorithm.group("value"), secret.group("value")


def emit_json(plans: Sequence[HostPlan]) -> str:
    return json.dumps([plan_to_dict(plan) for plan in plans], indent=2, sort_keys=True)


def plan_to_dict(plan: HostPlan) -> dict[str, Any]:
    return {
        "site_id": plan.site_id,
        "zone": plan.zone,
        "host_id": plan.host_id,
        "record": plan.record,
        "current_addresses": list(plan.current_addresses),
        "selected_candidate": plan.selected_candidate,
        "selected_address": plan.selected_address,
        "action": plan.action,
        "ttl": plan.ttl,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dns-shepherd")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"configuration file path (default: {DEFAULT_CONFIG})",
    )
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"configuration file path (default: {DEFAULT_CONFIG})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "validate", parents=[config_parent], help="validate configuration and exit"
    )
    subparsers.add_parser(
        "dry-run",
        parents=[config_parent],
        help="check candidates and print planned DNS actions",
    )
    subparsers.add_parser(
        "update",
        parents=[config_parent],
        help="check candidates and apply required nsupdate changes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        if args.command == "validate":
            print(
                f"valid config: site={config.deployment.site_id} "
                f"zone={config.deployment.zone} enabled_hosts={enabled_host_count(config)}"
            )
            return 0

        plans = plan_updates(config)
        if args.command == "dry-run":
            print(emit_json(plans))
            return 0

        changed = apply_updates(config, plans)
        print(emit_json(changed))
        return 0
    except (ConfigError, UpdateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def enabled_host_count(config: Config) -> int:
    return sum(1 for host in config.hosts if host.enabled)


if __name__ == "__main__":
    raise SystemExit(main())
