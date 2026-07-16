# Fedora RPM Packaging

This directory contains Fedora RPM packaging metadata for `dns-shepherd`.

The spec expects a release source archive named:

```text
dns-shepherd-0.1.0.tar.gz
```

Build from a clean source tree with standard Fedora tooling:

```bash
rpmbuild -ba packaging/rpm/dns-shepherd.spec
```

The package installs:

- `/usr/bin/dns-shepherd`
- `/usr/lib/systemd/system/dns-shepherd.service`
- `/usr/lib/systemd/system/dns-shepherd.timer`
- Python package files for `dns_shepherd`
- README, examples, docs, and MIT license metadata

Site-local configuration and TSIG key files are deliberately not packaged. A
deployment overlay should create `/etc/dns-shepherd/config.toml` and
`/etc/dns-shepherd/rfc2136.key` with local ownership and permissions.

See `docs/INSTALL.md` for the Fedora installation shape, service account
expectations, validation steps, and systemd timer operations.
