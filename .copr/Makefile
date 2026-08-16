NAME    := deckery-hud
VERSION := $(shell awk '/^Version:/{print $$2; exit}' $(CURDIR)/packaging/$(NAME).spec)
outdir  ?= $(CURDIR)/outdir
spec    ?= packaging/$(NAME).spec

.PHONY: srpm builddeps clean

builddeps:
	if command -v dnf >/dev/null 2>&1; then \
	    dnf -y install git rpm-build; \
	fi

srpm: builddeps
	mkdir -p $(outdir)
	git archive --prefix=$(NAME)-$(VERSION)/ -o $(outdir)/$(NAME)-$(VERSION).tar HEAD
	gzip -f $(outdir)/$(NAME)-$(VERSION).tar
	rpmbuild -bs \
	    --define "_sourcedir $(outdir)" \
	    --define "_srcrpmdir $(outdir)" \
	    --define "_topdir $(outdir)/rpmbuild" \
	    $(spec)
	@echo "SRPM written to $(outdir)"

clean:
	rm -rf $(outdir)
