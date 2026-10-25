# Local overlay ebuild: put in <overlay>/app-editors/aether/ then `ebuild aether-3.1.0.ebuild manifest`
EAPI=8
PYTHON_COMPAT=( python3_{10..13} )
inherit python-single-r1 xdg

DESCRIPTION="Fast IDE for Linux with projects, gdb debugger, LSP and git"
HOMEPAGE="https://github.com/rxvy-dev/aether"
SRC_URI="https://github.com/rxvy-dev/aether/archive/refs/tags/v${PV}.tar.gz -> ${P}.tar.gz"
LICENSE="MIT"
SLOT="0"
KEYWORDS="~amd64 ~arm64"
REQUIRED_USE="${PYTHON_REQUIRED_USE}"
RDEPEND="${PYTHON_DEPS}
	$(python_gen_cond_dep 'dev-python/pygobject[cairo,${PYTHON_USEDEP}]')
	gui-libs/gtk:4[introspection]
	gui-libs/gtksourceview:5[introspection]"

src_compile() { :; }
src_install() {
	emake DESTDIR="${D}" PREFIX=/usr install
	python_fix_shebang "${ED}"/usr/bin/aether
}
