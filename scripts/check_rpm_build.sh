#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

spec="packaging/rpm/dns-shepherd.spec"
name="$(sed -nE 's/^Name:[[:space:]]+//p' "$spec" | head -n 1)"
version="$(sed -nE 's/^Version:[[:space:]]+//p' "$spec" | head -n 1)"

if [[ -z "$name" || -z "$version" ]]; then
  echo "Unable to read Name/Version from $spec" >&2
  exit 1
fi

topdir="$(mktemp -d)"
trap 'rm -rf "$topdir"' EXIT

mkdir -p "$topdir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

archive="$topdir/SOURCES/$name-$version.tar.gz"
tar \
  --exclude-vcs \
  --exclude='./.git' \
  --exclude='./.pytest_cache' \
  --exclude='./__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --transform "s#^./#$name-$version/#" \
  -czf "$archive" \
  .

rpmbuild \
  --quiet \
  --define "_topdir $topdir" \
  -ba "$spec"

find "$topdir/RPMS" "$topdir/SRPMS" -type f -printf '%p\n' | sort
