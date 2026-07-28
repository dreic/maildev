%global appdir  %{_prefix}/lib/%{name}
%global maildir %{_sharedstatedir}/%{name}

# The payload is a pre-built Node application: pure JavaScript, no compiled
# objects. Nothing to strip, byte-compile or debug-package, and the shebangs
# inside node_modules belong to upstream packages — leave them alone.
%global debug_package %{nil}
%global __brp_mangle_shebangs %{nil}
%global __requires_exclude_from ^%{appdir}/.*$
%global __provides_exclude_from ^%{appdir}/.*$

Name:           maildev
Version:        %{?_maildev_version}%{!?_maildev_version:3.0.0}
Release:        %{?_maildev_release}%{!?_maildev_release:1}%{?dist}
Summary:        SMTP server and web interface for viewing email during development

License:        MIT
URL:            https://github.com/maildev/maildev
Source0:        %{name}-app.tar.gz
Source1:        maildev.service
Source2:        maildev.conf
Source3:        maildev@.service
Source4:        instance.conf.example

# All JavaScript — the same payload runs on any architecture Node supports.
BuildArch:      noarch

BuildRequires:  systemd-rpm-macros

# Rocky 9 ships nodejs 16 (EOL) as the default, non-modular package; 18, 20, 22
# and 24 are AppStream module streams. MailDev needs 20 or newer, so a stream has
# to be enabled before installing:
#
#     dnf module enable -y nodejs:22
#
Requires:       nodejs >= 1:20
Requires(pre):  shadow-utils
%{?systemd_requires}

%description
MailDev is an SMTP server and web interface for reading and testing the email
your application sends during development. Mail is captured rather than
delivered, so nothing reaches real recipients.

This package installs MailDev as a systemd service listening for SMTP on port
1025 and serving its web interface and REST API on port 1080. Adjust those and
other settings in %{_sysconfdir}/%{name}/%{name}.conf.

To run several independent instances on one host — each with its own ports and
mail directory — drop a config file per instance into
%{_sysconfdir}/%{name}/instances/ and use the maildev@.service template.


%prep
%setup -q -c -T
tar -xzf %{SOURCE0} --strip-components=1 -C .


%build
# Nothing to build: the application is compiled and its production dependency
# tree assembled before rpmbuild runs. See packaging/rpm/build.sh.


%install
install -d -m 0755 %{buildroot}%{appdir}
cp -a dist node_modules package.json %{buildroot}%{appdir}/

# Launcher, so `maildev` on PATH behaves the same as the npm-installed CLI
install -d -m 0755 %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{name} <<'EOF'
#!/bin/sh
# MailDev launcher — see `maildev --help`
exec /usr/bin/node %{appdir}/dist/bin/maildev.js "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/%{name}

install -D -m 0644 %{SOURCE1} %{buildroot}%{_unitdir}/%{name}.service
install -D -m 0644 %{SOURCE3} %{buildroot}%{_unitdir}/%{name}@.service
install -D -m 0644 %{SOURCE2} %{buildroot}%{_sysconfdir}/%{name}/%{name}.conf

# One config file per instance goes here, named after the instance
install -d -m 0755 %{buildroot}%{_sysconfdir}/%{name}/instances

# Shipped as documentation rather than an inert file in /etc; %doc below picks it
# up from the build directory
cp -p %{SOURCE4} ./instance.conf.example

# Captured mail lives here; the units also declare StateDirectory=
install -d -m 0750 %{buildroot}%{maildir}


%pre
getent group %{name} >/dev/null || groupadd -r %{name}
getent passwd %{name} >/dev/null || \
    useradd -r -g %{name} -d %{maildir} -s /sbin/nologin \
            -c "MailDev service account" %{name}
exit 0

%post
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service
# The macro above does not expand template instances, so stop them explicitly on
# uninstall. Left running, they would keep serving from a deleted install.
if [ $1 -eq 0 ]; then
    /usr/bin/systemctl stop '%{name}@*.service' >/dev/null 2>&1 || :
fi

%postun
%systemd_postun_with_restart %{name}.service
if [ $1 -ge 1 ]; then
    # Likewise for upgrades: restart whichever instances are running
    /usr/bin/systemctl try-restart '%{name}@*.service' >/dev/null 2>&1 || :
fi


%files
%license LICENSE
%doc README.md instance.conf.example
%{appdir}
%{_bindir}/%{name}
%{_unitdir}/%{name}.service
%{_unitdir}/%{name}@.service
%dir %{_sysconfdir}/%{name}
%dir %{_sysconfdir}/%{name}/instances
%config(noreplace) %{_sysconfdir}/%{name}/%{name}.conf
%attr(0750,%{name},%{name}) %dir %{maildir}


%changelog
* Mon Jul 27 2026 MailDev Contributors - 3.0.0-1
- Initial RPM packaging for Rocky Linux 9 / RHEL 9
