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
install -D -m 0644 %{SOURCE2} %{buildroot}%{_sysconfdir}/%{name}/%{name}.conf

# Captured mail lives here; the service also declares StateDirectory=maildev
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

%postun
%systemd_postun_with_restart %{name}.service


%files
%license LICENSE
%doc README.md
%{appdir}
%{_bindir}/%{name}
%{_unitdir}/%{name}.service
%dir %{_sysconfdir}/%{name}
%config(noreplace) %{_sysconfdir}/%{name}/%{name}.conf
%attr(0750,%{name},%{name}) %dir %{maildir}


%changelog
* Mon Jul 27 2026 MailDev Contributors - 3.0.0-1
- Initial RPM packaging for Rocky Linux 9 / RHEL 9
