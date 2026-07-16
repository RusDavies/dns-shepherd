Name:           dns-shepherd
Version:        0.1.0
Release:        1%{?dist}
Summary:        Configuration-driven DNS failover updater

License:        MIT
URL:            https://github.com/RusDavies/dns-shepherd
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  systemd-rpm-macros

Requires:       bind-utils
Requires:       systemd

%description
dns-shepherd checks ordered address candidates for configured hosts and updates
their canonical DNS A records through RFC2136-compatible dynamic DNS updates.
It is intended for local authoritative DNS failover where update credentials
are scoped to the managed records.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files dns_shepherd

install -Dpm0644 deploy/systemd/dns-shepherd.service \
  %{buildroot}%{_unitdir}/dns-shepherd.service
install -Dpm0644 deploy/systemd/dns-shepherd.timer \
  %{buildroot}%{_unitdir}/dns-shepherd.timer

%check
%pyproject_check_import
PYTHONPATH=%{buildroot}%{python3_sitelib} %{python3} -m unittest discover -s tests

%files -f %{pyproject_files}
%license LICENSE
%doc README.md docs examples
%{_bindir}/dns-shepherd
%{_unitdir}/dns-shepherd.service
%{_unitdir}/dns-shepherd.timer

%changelog
* Thu Jul 16 2026 Russ Davies <russ@example.invalid> - 0.1.0-1
- Initial Fedora RPM package metadata.
