# NixOS / nix:   nix-shell --run ./bin/aether
{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [ wrapGAppsHook4 gobject-introspection ];
  buildInputs = with pkgs; [
    (python3.withPackages (ps: [ ps.pygobject3 ps.pycairo ]))
    gtk4 gtksourceview5 vte-gtk4 gsettings-desktop-schemas
    gdb gcc gnumake git
  ];
  shellHook = ''
    export AETHER_PYTHON=$(command -v python3)
    export XDG_DATA_DIRS=${pkgs.gsettings-desktop-schemas}/share/gsettings-schemas/${pkgs.gsettings-desktop-schemas.name}:${pkgs.gtk4}/share/gsettings-schemas/${pkgs.gtk4.name}:$XDG_DATA_DIRS
    echo "Aether dev shell — run: ./bin/aether"
  '';
}
