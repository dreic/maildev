#!/usr/bin/env bash
#
# Build an RPM of MailDev for Rocky Linux 9 / RHEL 9.
#
# Runs entirely in containers, so the only host requirement is Docker — no Node,
# pnpm or rpm-build needed locally:
#
#   1. node:22        builds every workspace package and assembles the CLI's
#                     production dependency tree
#   2. rockylinux:9   turns that tree into an RPM
#
# Usage:
#   packaging/rpm/build.sh              # build the RPM
#   OUTPUT_DIR=/tmp/rpms  ...           # where to write it (default: dist/rpm)
#
# The result is a noarch RPM: the payload is pure JavaScript, so it installs on
# x86_64 and aarch64 alike. It requires nodejs >= 20, which on Rocky 9 means
# enabling an AppStream module stream first — see packaging/rpm/README.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/dist/rpm}"
BUILD_DIR="$REPO_ROOT/dist/rpm-build"

NODE_IMAGE="${NODE_IMAGE:-node:22}"
ROCKY_IMAGE="${ROCKY_IMAGE:-rockylinux:9}"

# npm-style version (e.g. 3.0.0-rc.1) split into RPM's Version and Release.
# RPM forbids '-' in Version, and a prerelease must sort *below* the eventual
# final release, which is what the 0.N. prefix achieves.
NPM_VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$REPO_ROOT/packages/cli/package.json" | head -1)"
RPM_VERSION="${NPM_VERSION%%-*}"
if [ "$NPM_VERSION" = "$RPM_VERSION" ]; then
  RPM_RELEASE="1"
else
  # 3.0.0-rc.1 -> 0.1.rc1
  RPM_RELEASE="0.1.$(printf '%s' "${NPM_VERSION#*-}" | tr -d '.-')"
fi

echo "==> MailDev ${NPM_VERSION}  ->  RPM ${RPM_VERSION}-${RPM_RELEASE}"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"

# ── Stage 1: build the app and its production dependency tree ────────────────
# `pnpm deploy` resolves the workspace: protocol links into a real, isolated
# tree with dev dependencies and sources omitted. --legacy is required because
# this workspace does not set inject-workspace-packages.
echo "==> Stage 1: building application tree ($NODE_IMAGE)"
docker run --rm \
  -v "$REPO_ROOT:/src:ro" \
  -v "$BUILD_DIR:/out" \
  -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
  -e CI=1 \
  -w /build \
  "$NODE_IMAGE" \
  bash -euo pipefail -c '
    corepack enable
    cp -a /src/. /build/
    rm -rf /build/node_modules /build/packages/*/node_modules /build/dist
    pnpm install --frozen-lockfile
    pnpm build
    # Deployed straight into its final directory name. Do not be tempted to tar
    # this up with --transform to rename it: tar rewrites symlink *targets* as
    # well as member names, which silently breaks every symlink in pnpm'"'"'s
    # node_modules layout.
    pnpm --filter=maildev deploy --prod --legacy /stage/maildev-app

    # tsc emits each package'"'"'s tests, declarations and source maps into dist.
    # None of it is read at runtime, and shipping compiled tests to production
    # hosts is just noise.
    find /stage/maildev-app -type d -name __tests__ -prune -exec rm -rf {} +
    find /stage/maildev-app -type f \( -name "*.map" -o -name "*.d.ts" \) -delete

    cp /build/LICENSE /stage/maildev-app/LICENSE
    tar -czf /out/maildev-app.tar.gz -C /stage maildev-app

    # Fail loudly here rather than at install time if the layout is broken
    node -e "
      const { execSync } = require(\"child_process\");
      const broken = execSync(\"find /stage/maildev-app -xtype l\").toString().trim();
      if (broken) { console.error(\"dangling symlinks:\\n\" + broken); process.exit(1) }
    "
  '

echo "    tree: $(du -h "$BUILD_DIR/maildev-app.tar.gz" | cut -f1)"

# ── Stage 2: build the RPM ──────────────────────────────────────────────────
echo "==> Stage 2: building RPM ($ROCKY_IMAGE)"
docker run --rm \
  -v "$REPO_ROOT/packaging/rpm:/spec:ro" \
  -v "$BUILD_DIR:/in:ro" \
  -v "$OUTPUT_DIR:/out" \
  -e RPM_VERSION="$RPM_VERSION" \
  -e RPM_RELEASE="$RPM_RELEASE" \
  "$ROCKY_IMAGE" \
  bash -euo pipefail -c '
    dnf -q -y install rpm-build rpmdevtools systemd-rpm-macros >/dev/null
    rpmdev-setuptree
    cp /in/maildev-app.tar.gz ~/rpmbuild/SOURCES/
    cp /spec/maildev.service /spec/maildev.conf ~/rpmbuild/SOURCES/
    cp /spec/maildev.spec ~/rpmbuild/SPECS/
    rpmbuild -bb ~/rpmbuild/SPECS/maildev.spec \
      --define "_maildev_version $RPM_VERSION" \
      --define "_maildev_release $RPM_RELEASE"
    cp ~/rpmbuild/RPMS/noarch/*.rpm /out/
  '

echo
echo "==> Built:"
ls -lh "$OUTPUT_DIR"/*.rpm | sed 's/^/    /'
