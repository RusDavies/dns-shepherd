# Contributing

`dns-shepherd` is intended to remain a generic public tool. Keep changes free of
private infrastructure details and make examples runnable without access to any
specific private network.

## Development Setup

Run checks from the repository root:

```bash
scripts/check.sh
```

The check gate runs:

- Python bytecode compilation;
- the unittest suite;
- RPM build verification through `scripts/check_rpm_build.sh`.

## Public-Safe Examples

Use only documentation domains and reserved IP ranges in committed examples and
tests:

- `example.invalid`
- `example.net`
- `192.0.2.0/24`
- `198.51.100.0/24`
- `203.0.113.0/24`

Do not commit private hostnames, private domains, private IP addresses, live
TSIG key paths, operational transcripts, or deployment runbooks.

## Change Guidelines

- Keep planner behavior covered by tests.
- Add adapter-specific tests when adding DNS backends.
- Keep packaged paths aligned with Fedora conventions.
- Prefer small changes with clear docs updates.
- Validate configs and dry-run behavior before changing update semantics.

## Reporting Issues

For security-sensitive reports, follow [SECURITY.md](SECURITY.md). For ordinary
bugs or feature ideas, include the command, sanitized configuration shape, and
expected versus actual behavior.
