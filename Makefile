PREFIX ?= /usr/local
DESTDIR ?=
VERSION := 3.0.0
APP := io.github.aether.Editor

PYTHON ?= $(shell for p in /usr/bin/python3 python3 /usr/bin/python3.1[0-9]; do $$p -c 'import gi' 2>/dev/null && { echo $$p; break; }; done)

all:
	@echo "Nothing to compile (pure Python). Try: make install [PREFIX=/usr] [DESTDIR=...] | make check | make test | make deb | make rpm | make dist"

install:
	install -d $(DESTDIR)$(PREFIX)/bin $(DESTDIR)$(PREFIX)/share/aether
	install -m755 bin/aether $(DESTDIR)$(PREFIX)/bin/aether
	cp -r aether data $(DESTDIR)$(PREFIX)/share/aether/
	find $(DESTDIR)$(PREFIX)/share/aether -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(DESTDIR)$(PREFIX)/share/aether/data/icons $(DESTDIR)$(PREFIX)/share/aether/data/*.desktop $(DESTDIR)$(PREFIX)/share/aether/data/*.metainfo.xml
	install -d $(DESTDIR)$(PREFIX)/share/icons $(DESTDIR)$(PREFIX)/share/applications $(DESTDIR)$(PREFIX)/share/metainfo
	cp -r data/icons/hicolor $(DESTDIR)$(PREFIX)/share/icons/
	install -m644 data/$(APP).desktop $(DESTDIR)$(PREFIX)/share/applications/
	install -m644 data/$(APP).metainfo.xml $(DESTDIR)$(PREFIX)/share/metainfo/
	install -Dm644 LICENSE $(DESTDIR)$(PREFIX)/share/licenses/aether/LICENSE
	-gtk-update-icon-cache -q -t $(DESTDIR)$(PREFIX)/share/icons/hicolor 2>/dev/null
	-update-desktop-database -q $(DESTDIR)$(PREFIX)/share/applications 2>/dev/null

uninstall:
	rm -rf $(DESTDIR)$(PREFIX)/share/aether $(DESTDIR)$(PREFIX)/bin/aether \
	  $(DESTDIR)$(PREFIX)/share/applications/$(APP).desktop $(DESTDIR)$(PREFIX)/share/metainfo/$(APP).metainfo.xml
	find $(DESTDIR)$(PREFIX)/share/icons -name aether.* -delete

dist:
	mkdir -p dist
	tar czf dist/aether-$(VERSION).tar.gz --transform 's,^\.,aether-$(VERSION),' \
	  --exclude=./dist --exclude=./.github --exclude=__pycache__ --exclude='*.pyc' --exclude=./.git .
	@echo dist/aether-$(VERSION).tar.gz

deb:
	sh packaging/build-deb.sh

rpm: dist
	rpmbuild -ta dist/aether-$(VERSION).tar.gz --define "_rpmdir $(CURDIR)/dist" --define "_srcrpmdir $(CURDIR)/dist"

check:
	PYTHONPATH=. $(PYTHON) -c 'import sys; from aether.doctor import main; sys.exit(main())'

test:
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests -v

run:
	./bin/aether

.PHONY: all install uninstall dist deb rpm check test run
