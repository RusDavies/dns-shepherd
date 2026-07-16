# Releases

`dns-shepherd` is pre-1.0. Release notes should describe user-visible behavior,
packaging changes, compatibility notes, and security-relevant fixes.

## Versioning

Before 1.0, minor versions may change configuration shape or command behavior.
Patch versions should be bug fixes, packaging fixes, or documentation-only
updates.

## Release Checklist

- `scripts/check.sh` passes from a clean checkout.
- RPM build verification produces a binary RPM and source RPM.
- Public examples use only documentation domains and reserved IP ranges.
- Public docs contain no private hostnames, private domains, private IPs, live
  key paths, or site-specific operational history.
- `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, and installation docs reflect
  the release behavior.
- The changelog or release notes summarize upgrade impact.

## Packaging Notes

The Fedora RPM installs the CLI, Python module, and systemd service/timer units.
Site-local configuration and TSIG keys remain deployment-owned and are not
packaged.
