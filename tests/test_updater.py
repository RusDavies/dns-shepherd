import subprocess
import tempfile
import unittest
from pathlib import Path

from dns_shepherd.updater import (
    ConfigError,
    apply_updates,
    load_config,
    main,
    nsupdate_key_material,
    parse_bind_key_file,
    parse_config,
    plan_updates,
    record_fqdn,
    run_nsupdate,
)


def base_config():
    return {
        "deployment": {
            "site_id": "primary",
            "zone": "example.invalid",
            "dns_server": "127.0.0.1",
            "key_file": "/etc/dns-shepherd/rfc2136.key",
        },
        "defaults": {
            "ttl": 30,
            "check_timeout_seconds": 2,
            "retain_last_known_good": True,
        },
        "hosts": {
            "alpha": {
                "enabled": True,
                "record": "alpha",
                "ttl": 30,
                "diagnostic_records": ["alpha-lan", "alpha-wifi", "alpha-ts"],
                "candidates": [
                    {"name": "lan", "address": "192.0.2.10", "check": "tcp", "port": 22},
                    {"name": "wifi", "address": "192.0.2.110", "check": "tcp", "port": 22},
                    {"name": "tailscale", "address": "203.0.113.10", "check": "tcp", "port": 22},
                ],
            }
        },
    }


class UpdaterTests(unittest.TestCase):
    def test_record_fqdn_handles_relative_and_absolute_records(self):
        self.assertEqual(
            record_fqdn("alpha", "example.invalid"),
            "alpha.example.invalid.",
        )
        self.assertEqual(
            record_fqdn("alpha.example.invalid", "example.invalid"),
            "alpha.example.invalid.",
        )
        self.assertEqual(
            record_fqdn("alpha.example.invalid.", "example.invalid"),
            "alpha.example.invalid.",
        )
        self.assertEqual(
            record_fqdn("service.example.net", "example.invalid"),
            "service.example.net.",
        )

    def test_parse_config_rejects_duplicate_enabled_records(self):
        raw = base_config()
        raw["hosts"]["copy"] = dict(raw["hosts"]["alpha"])
        raw["hosts"]["copy"]["record"] = "alpha.example.invalid."
        with self.assertRaisesRegex(ConfigError, "both manage"):
            parse_config(raw)

    def test_parse_config_defaults_to_bind_nsupdate_adapter(self):
        config = parse_config(base_config())
        self.assertEqual(config.deployment.update_adapter, "bind_nsupdate")

    def test_parse_config_rejects_unknown_update_adapter(self):
        raw = base_config()
        raw["deployment"]["update_adapter"] = "cloudflare"
        with self.assertRaisesRegex(ConfigError, "deployment.update_adapter"):
            parse_config(raw)

    def test_plan_updates_selects_first_reachable_candidate(self):
        config = parse_config(base_config())

        def health(candidate, timeout):
            return candidate.name == "wifi"

        def runner(args, **kwargs):
            self.assertIn("+short", args)
            return subprocess.CompletedProcess(args, 0, stdout="192.0.2.10\n", stderr="")

        plans = plan_updates(config, health_checker=health, runner=runner)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].action, "update")
        self.assertEqual(plans[0].selected_candidate, "wifi")
        self.assertEqual(plans[0].selected_address, "192.0.2.110")

    def test_plan_updates_keeps_current_record_when_candidate_matches(self):
        config = parse_config(base_config())

        def health(candidate, timeout):
            return candidate.name == "lan"

        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="192.0.2.10\n", stderr="")

        plans = plan_updates(config, health_checker=health, runner=runner)
        self.assertEqual(plans[0].action, "unchanged")

    def test_plan_updates_retains_last_known_good_when_all_candidates_fail(self):
        config = parse_config(base_config())

        def health(candidate, timeout):
            return False

        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="192.0.2.10\n", stderr="")

        plans = plan_updates(config, health_checker=health, runner=runner)
        self.assertEqual(plans[0].action, "retain")
        self.assertIsNone(plans[0].selected_address)

    def test_plan_updates_processes_two_hosts_without_special_cases(self):
        raw = base_config()
        raw["deployment"]["zone"] = "example.invalid"
        raw["hosts"] = {
            "alpha": {
                "enabled": True,
                "record": "alpha",
                "ttl": 30,
                "candidates": [
                    {"name": "lan", "address": "192.0.2.10", "check": "tcp", "port": 22},
                    {"name": "wifi", "address": "192.0.2.110", "check": "tcp", "port": 22},
                ],
            },
            "beta": {
                "enabled": True,
                "record": "beta",
                "ttl": 45,
                "candidates": [
                    {"name": "lan", "address": "198.51.100.20", "check": "tcp", "port": 22},
                    {"name": "tailscale", "address": "203.0.113.20", "check": "tcp", "port": 22},
                ],
            },
        }
        config = parse_config(raw)

        reachable = {"192.0.2.110", "198.51.100.20"}

        def health(candidate, timeout):
            return candidate.address in reachable

        def runner(args, **kwargs):
            record = args[-2]
            answers = {
                "alpha.example.invalid.": "192.0.2.10\n",
                "beta.example.invalid.": "198.51.100.20\n",
            }
            return subprocess.CompletedProcess(args, 0, stdout=answers[record], stderr="")

        plans = plan_updates(config, health_checker=health, runner=runner)
        by_host = {plan.host_id: plan for plan in plans}

        self.assertEqual(set(by_host), {"alpha", "beta"})
        self.assertEqual(by_host["alpha"].action, "update")
        self.assertEqual(by_host["alpha"].selected_candidate, "wifi")
        self.assertEqual(by_host["alpha"].selected_address, "192.0.2.110")
        self.assertEqual(by_host["beta"].action, "unchanged")
        self.assertEqual(by_host["beta"].selected_candidate, "lan")
        self.assertEqual(by_host["beta"].ttl, 45)

    def test_plan_and_apply_use_dns_update_adapter_boundary(self):
        config = parse_config(base_config())
        applied = []
        test_case = self

        class FakeAdapter:
            def current_addresses(self, record):
                test_case.assertEqual(record, "alpha.example.invalid.")
                return ("192.0.2.10",)

            def apply(self, plan):
                applied.append(plan)

        adapter = FakeAdapter()
        plans = plan_updates(
            config,
            health_checker=lambda candidate, timeout: candidate.name == "wifi",
            dns_adapter=adapter,
        )
        changed = apply_updates(config, plans, dns_adapter=adapter)

        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].selected_address, "192.0.2.110")
        self.assertEqual(applied, changed)

    def test_representative_two_host_example_validates(self):
        config = load_config(Path("examples/representative-two-hosts.config.toml"))
        self.assertEqual(len(config.hosts), 2)

    def test_representative_second_site_example_uses_its_own_boundaries(self):
        config = load_config(Path("examples/representative-second-site.config.toml"))
        self.assertEqual(config.deployment.site_id, "representative-branch")
        self.assertEqual(config.deployment.zone, "branch.example.invalid")
        self.assertEqual(config.deployment.dns_server, "198.51.100.53")
        self.assertEqual(len(config.hosts), 1)

        dig_calls = []

        def runner(args, **kwargs):
            dig_calls.append(args)
            self.assertEqual(args[:3], ["dig", "@198.51.100.53", "+short"])
            self.assertEqual(args[3], "gateway.branch.example.invalid.")
            return subprocess.CompletedProcess(args, 0, stdout="192.0.2.140\n", stderr="")

        plans = plan_updates(
            config,
            health_checker=lambda candidate, timeout: candidate.name == "lan",
            runner=runner,
        )

        self.assertEqual(len(dig_calls), 1)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].site_id, "representative-branch")
        self.assertEqual(plans[0].zone, "branch.example.invalid")
        self.assertEqual(plans[0].record, "gateway.branch.example.invalid.")
        self.assertEqual(plans[0].action, "update")
        self.assertEqual(plans[0].selected_address, "192.0.2.40")

    def test_nsupdate_payload_uses_bind_include_key_without_process_arg_secret(self):
        raw = base_config()
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "dns-shepherd.key"
            key_path.write_text(
                """
key "dns-shepherd" {
    algorithm hmac-sha256;
    secret "dummy-secret";
};
""".strip()
            )
            raw["deployment"]["key_file"] = str(key_path)
            config = parse_config(raw)
            plans = plan_updates(
                config,
                health_checker=lambda candidate, timeout: candidate.name == "wifi",
                runner=lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="192.0.2.10\n", stderr=""),
            )
            captured = {}

            def runner(args, **kwargs):
                captured["args"] = args
                captured["input"] = kwargs["input"]
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            run_nsupdate(config, plans[0], runner=runner)

        self.assertEqual(captured["args"], ["nsupdate"])
        self.assertIn("key hmac-sha256:dns-shepherd dummy-secret", captured["input"])
        self.assertIn("zone example.invalid", captured["input"])
        self.assertIn("update delete alpha.example.invalid. A", captured["input"])
        self.assertIn(
            "update add alpha.example.invalid. 30 A 192.0.2.110",
            captured["input"],
        )

    def test_nsupdate_payload_falls_back_to_key_file_argument(self):
        config = parse_config(base_config())
        plans = plan_updates(
            config,
            health_checker=lambda candidate, timeout: candidate.name == "wifi",
            runner=lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="192.0.2.10\n", stderr=""),
        )
        captured = {}

        def runner(args, **kwargs):
            captured["args"] = args
            captured["input"] = kwargs["input"]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        run_nsupdate(config, plans[0], runner=runner)

        self.assertEqual(
            captured["args"],
            ["nsupdate", "-k", "/etc/dns-shepherd/rfc2136.key"],
        )
        self.assertIn("zone example.invalid", captured["input"])
        self.assertIn("update delete alpha.example.invalid. A", captured["input"])
        self.assertIn(
            "update add alpha.example.invalid. 30 A 192.0.2.110",
            captured["input"],
        )

    def test_parse_bind_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "test.key"
            key_path.write_text(
                """
key "example-key" {
    algorithm hmac-sha512;
    secret "abc123==";
};
""".strip()
            )

            self.assertEqual(
                parse_bind_key_file(key_path),
                ("example-key", "hmac-sha512", "abc123=="),
            )
            self.assertEqual(
                nsupdate_key_material(str(key_path)),
                ([], "key hmac-sha512:example-key abc123=="),
            )

    def test_cli_accepts_config_after_subcommand(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                """
[deployment]
site_id = "primary"
zone = "example.invalid"
dns_server = "127.0.0.1"
key_file = "/etc/dns-shepherd/rfc2136.key"

[hosts.alpha]
enabled = true
record = "alpha"

[[hosts.alpha.candidates]]
name = "lan"
address = "192.0.2.10"
check = "tcp"
port = 22
""".strip()
            )
            self.assertEqual(main(["validate", "--config", str(config_path)]), 0)
            self.assertEqual(main(["--config", str(config_path), "validate"]), 0)


if __name__ == "__main__":
    unittest.main()
