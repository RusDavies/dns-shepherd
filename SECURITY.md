# Security Policy

`dns-shepherd` updates DNS records and should be deployed with deliberately
scoped credentials.

## Supported Security Model

- Keep TSIG secrets in key files, not in TOML configuration.
- Scope DNS update policy to only the records managed by `dns-shepherd`.
- Run with the least-privileged account that can read the site config and key.
- Validate and dry-run configuration before enabling the timer.
- Treat examples and tests as public material; never add private infrastructure
  details to the public tree.

## Reporting Vulnerabilities

Please report security issues privately to the project maintainer before public
disclosure. Include:

- affected version or commit;
- summary of the impact;
- reproduction steps with sanitized inputs;
- whether the issue can modify records outside the intended scope;
- any suggested mitigation.

Do not include live secrets, private keys, or private network inventories in a
report. Use redacted or representative values.

## Out Of Scope

The project cannot secure an overly broad DNS server update policy. If the DNS
server grants the updater permission to modify unrelated records, fix the server
policy before enabling recurring updates. Tiny detail, enormous blast radius.
