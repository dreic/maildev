# MailDev RPM for Rocky Linux 9 / RHEL 9

Packages MailDev as a systemd service for the RHEL 9 family.

## Building

Only Docker is needed on the build host — no Node, pnpm or `rpm-build`:

```bash
packaging/rpm/build.sh
```

The RPM lands in `dist/rpm/`. The build runs in two containers: `node:22` compiles
every workspace package and assembles the CLI's production dependency tree, then
`rockylinux:9` turns that tree into the package.

The result is **noarch** — the payload is pure JavaScript with no compiled
objects, so one package serves x86_64 and aarch64 alike.

## Installing

> **Rocky 9 ships Node.js 16 (end-of-life) as its default.** Versions 18 through
> 24 are AppStream *module streams*, and dnf hides them until a stream is
> enabled. MailDev needs Node 20 or newer, so `dnf install` fails with
> "package nodejs ... is filtered out by modular filtering" unless you enable one
> first. This is a property of the distribution, not of this package.

```bash
sudo dnf module enable -y nodejs:22
sudo dnf install ./maildev-*.noarch.rpm
sudo systemctl enable --now maildev
```

Verify:

```bash
systemctl status maildev
curl http://localhost:1080/api/healthz
```

Then point your application's mail transport at port 1025 and open
<http://localhost:1080> to read what it sends.

## Layout

| Path | Contents |
| --- | --- |
| `/usr/lib/maildev/` | Application and its production dependencies |
| `/usr/bin/maildev` | Launcher; behaves like the npm-installed CLI |
| `/etc/maildev/maildev.conf` | Configuration, read by the unit as an `EnvironmentFile` |
| `/usr/lib/systemd/system/maildev.service` | Service unit |
| `/var/lib/maildev/` | Captured mail, owned by the `maildev` system user |

## Configuring

Edit `/etc/maildev/maildev.conf` and restart. Every setting has a command-line
equivalent — see `maildev --help`. The file is marked `%config(noreplace)`, so
upgrades leave your edits alone.

```bash
sudoedit /etc/maildev/maildev.conf
sudo systemctl restart maildev
```

The defaults listen for SMTP on 1025 and serve the web interface on 1080, on all
interfaces. **There is no authentication by default** — MailDev is a development
tool and captured mail is readable by anyone who can reach the port. On a shared
host, either bind to localhost (`MAILDEV_WEB_IP=127.0.0.1`, `MAILDEV_IP=127.0.0.1`)
or set `MAILDEV_WEB_USER` and `MAILDEV_WEB_PASS`.

### Ports below 1024

The unit runs with no capabilities at all, which is fine for the unprivileged
default ports. To listen on port 25, also grant the capability:

```ini
# /etc/systemd/system/maildev.service.d/override.conf
[Service]
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
```

### Storage limit

`MAILDEV_MAX_EMAILS` (default 1000) caps how much mail is kept. Older messages
are discarded along with their files, which keeps both memory use and
`/var/lib/maildev` bounded. Setting it to `0` removes the limit — memory and disk
then grow until the host runs out of one of them.

## Known behaviour

**Captured mail is not reloaded when the service restarts.** The `.eml` files
stay in `/var/lib/maildev`, but MailDev only reads them back on request, so the
web interface starts empty after `systemctl restart maildev`. To restore the
previous contents:

```bash
curl http://localhost:1080/api/reloadMailsFromDirectory
```

## Firewall

```bash
sudo firewall-cmd --permanent --add-port=1025/tcp --add-port=1080/tcp
sudo firewall-cmd --reload
```

## SELinux

The package installs into standard locations and the service runs unconfined, so
no policy changes are needed on a default Rocky 9 install. If you relocate the
mail directory, restore its context with
`restorecon -Rv /path/to/maildev`.

## Uninstalling

```bash
sudo dnf remove maildev
```

Captured mail in `/var/lib/maildev` is left behind — remove it by hand if you
want it gone.
