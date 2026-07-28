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
| `/etc/maildev/maildev.conf` | Configuration for the single-instance service |
| `/etc/maildev/instances/` | One config file per instance, for `maildev@.service` |
| `/usr/lib/systemd/system/maildev.service` | Single-instance unit |
| `/usr/lib/systemd/system/maildev@.service` | Template unit for multiple instances |
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

## Running multiple instances

Use the `maildev@.service` template to run several independent instances on one
host — one per project, environment or team. Each gets its own ports, its own
mail directory and its own captured mail.

Create a config file per instance, named after the instance:

```bash
sudo cp /usr/share/doc/maildev/instance.conf.example /etc/maildev/instances/dev.conf
sudo cp /usr/share/doc/maildev/instance.conf.example /etc/maildev/instances/staging.conf
```

Give each one unused ports:

```ini
# /etc/maildev/instances/dev.conf
MAILDEV_SMTP_PORT=2025
MAILDEV_WEB_PORT=2080

# /etc/maildev/instances/staging.conf
MAILDEV_SMTP_PORT=3025
MAILDEV_WEB_PORT=3080
```

Then start them:

```bash
sudo systemctl enable --now maildev@dev maildev@staging
systemctl status 'maildev@*'
```

Mail lands in `/var/lib/maildev/dev` and `/var/lib/maildev/staging`, created
automatically. Nothing is shared between instances.

The instance config is **not** optional — the unit refuses to start without
`/etc/maildev/instances/<name>.conf`, rather than silently colliding with another
instance on the default ports. If two instances are given the same port, the
second fails with `EADDRINUSE`, visible in `journalctl -u maildev@<name>`.

The single-instance `maildev.service` and the template can coexist, but they both
default to ports 1025/1080, so don't enable `maildev.service` alongside an
instance using those. For a purely multi-instance host, leave `maildev.service`
disabled and use only the template.

### Behind one reverse proxy

To reach several instances through a single hostname, give each one a path and
tell it what that path is. Two rules, and they must agree:

1. `proxy_pass` takes **no trailing slash**, so the prefix is forwarded to
   MailDev rather than stripped.
2. Each instance sets `MAILDEV_BASE_PATHNAME` to the same prefix, without a
   trailing slash.

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name mailcatcher.example.com;

    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;

    location /dev/corehr/     { proxy_pass http://localhost:2080; }
    location /qa/corehr/      { proxy_pass http://localhost:3080; }
    location /staging/corehr/ { proxy_pass http://localhost:4080; }
}
```

```ini
# /etc/maildev/instances/dev.conf
MAILDEV_SMTP_PORT=2025
MAILDEV_WEB_PORT=2080
MAILDEV_BASE_PATHNAME=/dev/corehr
```

If the two disagree the page still loads while everything it then requests —
assets, REST calls, the websocket — resolves to the wrong path and 404s. A
trailing slash on `proxy_pass` is the usual cause.

Point health checks at `/<prefix>/api/healthz`, not at `/<prefix>/`. The base path
root is served by the single-page-app fallback, which only answers requests that
accept `text/html`; a browser gets the page, but a probe sending the usual
`Accept: */*` gets a 404 and will read the service as down. `api/healthz` answers
regardless:

```bash
curl -fsS https://mailcatcher.example.com/dev/corehr/api/healthz
```

Equivalent command-line form, if you would rather not use systemd at all — the
v2 flags all still work:

```bash
maildev --smtp 2025 --web 2080 --mail-directory /srv/maildev/dev
```

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

A side effect: mail left from before a restart is not tracked by the running
instance, so `MAILDEV_MAX_EMAILS` will not evict it and the file count on disk can
exceed the count shown in the web interface. It stays bounded — the mail directory
is trimmed to the newest `MAILDEV_MAX_EMAILS` files at every start — but expect up
to roughly twice that many files between restarts. Reloading as above, or clearing
the inbox from the web interface, brings the two back into line.

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
