# dns-shepherd

`dns-shepherd` is a small DNS failover updater for sites that run their own
authoritative DNS. It checks ordered address candidates for each managed host
and updates the host's canonical A record to the first reachable address.

The first backend uses BIND-compatible RFC2136 dynamic updates through
`nsupdate`. The planner, health checks, and DNS update adapter are separated so
future backends can be added without changing how host failover is modeled.

## What It Does

- Watches explicitly configured host records.
- Tests candidate addresses in a preferred order, such as LAN, Wi-Fi, VPN, or
  other site-local routes.
- Updates only the approved canonical A records for enabled hosts.
- Leaves diagnostic/interface records and unmanaged hosts alone.
- Supports validation, dry-run, and one-shot update modes.
- Runs well from a systemd timer on Fedora-style hosts.

`dns-shepherd` is not a dynamic DNS provider client like `ddclient`, and it is
not a VRRP/load-balancer replacement like `keepalived`. It is for local
authoritative DNS failover where you want a host name to follow the best
reachable route under tightly scoped DNS update credentials.

## Quick Start

Validate one of the representative configurations:

```bash
PYTHONPATH=src python3 -m dns_shepherd validate --config examples/representative-two-hosts.config.toml
```

Preview planned DNS changes:

```bash
PYTHONPATH=src python3 -m dns_shepherd dry-run --config examples/representative-two-hosts.config.toml
```

Run the test and packaging checks:

```bash
scripts/check.sh
```

After installation, site-local configuration normally lives at:

```text
/etc/dns-shepherd/config.toml
/etc/dns-shepherd/rfc2136.key
```

Validate and dry-run a site config before enabling recurring updates:

```bash
dns-shepherd validate --config /etc/dns-shepherd/config.toml
dns-shepherd dry-run --config /etc/dns-shepherd/config.toml
```

## Documentation

- [Installation](docs/INSTALL.md): Fedora paths, config/key permissions,
  systemd timer operations, and RPM build verification.
- [Packaging](packaging/rpm/README.md): RPM packaging metadata and local build
  notes.
- [Examples](examples/): documentation-only sample configurations using
  reserved domains and IP ranges.
- [Security](SECURITY.md): supported reporting process and deployment safety
  expectations.
- [Releases](RELEASES.md): release-readiness and versioning notes.

## Contributing

Contributions should keep the public tree generic. Do not add private hostnames,
private domains, private IP addresses, live key paths, or site-specific runbook
history.

Before opening a change:

```bash
scripts/check.sh
```

Useful contribution areas include:

- additional DNS update adapters;
- more health-check methods;
- documentation and examples for generic RFC2136 deployments;
- Fedora packaging improvements;
- test coverage for planner and adapter behavior.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow.
