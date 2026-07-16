# dns-shepherd

`dns-shepherd` is a small configuration-driven DNS failover updater. It checks
ordered address candidates for each managed host and updates the canonical A
record to the first reachable candidate.

The current implementation targets BIND-compatible RFC2136 dynamic updates via
`nsupdate`. Host selection, health checks, and DNS update application are kept
separate so additional DNS backends can be added without rewriting the planner.

## Quick Start

Validate a configuration:

```bash
dns-shepherd validate --config examples/representative-two-hosts.config.toml
```

Preview planned changes:

```bash
dns-shepherd dry-run --config /etc/dns-shepherd/config.toml
```

Apply changes:

```bash
dns-shepherd update --config /etc/dns-shepherd/config.toml
```

## Configuration

Configurations are TOML files with one deployment and one or more managed
hosts. Representative public examples live in `examples/` and use reserved
documentation domains and IP ranges only.

## Safety

- Keep TSIG secrets in key files, not in the TOML config.
- Scope DNS update credentials to only the records the service manages.
- Run `validate` and `dry-run` before enabling the timer.
- Use the private marker scan before any public push when syncing from a private
  workbench.

## Packaging

Fedora RPM packaging metadata lives under `packaging/rpm/`. The package installs
the `dns-shepherd` CLI, Python module, and systemd service/timer units. Local
configuration and TSIG keys are deployment-owned and are not included in the
RPM.
