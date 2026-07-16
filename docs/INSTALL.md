# Fedora Installation

This document describes the RPM-managed installation shape for `dns-shepherd`.
It assumes a Fedora-style package installation and a BIND/RFC2136 deployment
using `nsupdate`.

## Installed Files

The RPM-managed paths are:

```text
/usr/bin/dns-shepherd
/usr/lib/systemd/system/dns-shepherd.service
/usr/lib/systemd/system/dns-shepherd.timer
/usr/share/doc/dns-shepherd/
/usr/share/licenses/dns-shepherd/
```

Site-local files are deliberately not owned by the RPM:

```text
/etc/dns-shepherd/config.toml
/etc/dns-shepherd/rfc2136.key
```

The package depends on `bind-utils` for `dig` and `nsupdate`.

## Site Configuration

Create the configuration directory and install local files with permissions that
allow the service account to read them:

```bash
sudo install -d -m 0750 -o root -g named /etc/dns-shepherd
sudo install -m 0640 -o root -g named config.toml /etc/dns-shepherd/config.toml
sudo install -m 0640 -o root -g named rfc2136.key /etc/dns-shepherd/rfc2136.key
```

Do not store TSIG secrets in `config.toml`. Keep them in the key file and scope
the DNS server update policy to only the records managed by `dns-shepherd`.

## Validation

Validate the site configuration before enabling recurring updates:

```bash
dns-shepherd validate --config /etc/dns-shepherd/config.toml
dns-shepherd dry-run --config /etc/dns-shepherd/config.toml
```

If the service account is not allowed to read the config or key file, the
systemd unit will fail before making any DNS changes because both paths are
declared with `ConditionPathExists=`.

## Systemd Timer

The RPM installs `dns-shepherd.service` and `dns-shepherd.timer` under
`/usr/lib/systemd/system/`. Enable the timer only after validation and dry-run
checks pass:

```bash
sudo systemctl enable --now dns-shepherd.timer
systemctl list-timers dns-shepherd.timer
```

Run a one-shot update manually when you need an immediate check:

```bash
sudo systemctl start dns-shepherd.service
sudo journalctl -u dns-shepherd.service -n 100 --no-pager
```

Disable recurring updates without removing the package:

```bash
sudo systemctl disable --now dns-shepherd.timer
```

## Service Account

The packaged unit runs as `User=named` and `Group=named` because the first
target deployment is a local authoritative DNS host. If a site uses another
least-privileged account, add a systemd drop-in rather than editing the RPM
owned unit file:

```bash
sudo systemctl edit dns-shepherd.service
```

Example drop-in:

```ini
[Service]
User=dns-shepherd
Group=dns-shepherd
```

After changing the service account, update ownership or ACLs for
`/etc/dns-shepherd/config.toml` and `/etc/dns-shepherd/rfc2136.key`, then rerun
`validate` and `dry-run`.

## Manual Unit Installation

For source-tree testing without an RPM, copy the unit files into
`/etc/systemd/system/` or another local override path and reload systemd:

```bash
sudo install -m 0644 deploy/systemd/dns-shepherd.service /etc/systemd/system/dns-shepherd.service
sudo install -m 0644 deploy/systemd/dns-shepherd.timer /etc/systemd/system/dns-shepherd.timer
sudo systemctl daemon-reload
```

RPM installations should use the packaged files under `/usr/lib/systemd/system/`
and should not require manual unit copying.
