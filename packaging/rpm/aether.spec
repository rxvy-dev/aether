# Fedora / RHEL 9+ (EPEL) / openSUSE:
#   make dist && rpmbuild -ta dist/aether-3.0.0.tar.gz      (or: make rpm)
Name:           aether
Version:        3.0.0
Release:        1%{?dist}
Summary:        Fast IDE for Linux
License:        MIT
URL:            https://github.com/rxvy-dev/aether
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  make
Requires:       python3 >= 3.9
%if 0%{?suse_version}
Requires:       python3-gobject python3-gobject-cairo python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-GtkSource-5
Recommends:     typelib-1_0-Vte-3_91 gdb gcc make git
%else
Requires:       python3-gobject python3-cairo gtk4 >= 4.8 gtksourceview5 >= 5.6
Recommends:     vte291-gtk4 gdb gcc gcc-c++ make git
%endif

%description
Projects and builds (Make, CMake, Meson, Cargo, Go, Zig, npm), a gdb debugger
with breakpoints, variables and call stack, language servers, git, code folding,
multiple cursors, an outline, 39 themes and a built-in terminal.

%prep
%autosetup

%build

%install
make install DESTDIR=%{buildroot} PREFIX=%{_prefix}

%files
%{_bindir}/aether
%{_datadir}/aether/
%{_datadir}/applications/io.github.aether.Editor.desktop
%{_datadir}/metainfo/io.github.aether.Editor.metainfo.xml
%{_datadir}/icons/hicolor/*/*/aether*
%{_datadir}/licenses/aether/
