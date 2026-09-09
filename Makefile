# Mac setup: python3 is enough — build.py uses only the standard library.
# The Firebase CLI needs Node. Both come from Homebrew.
#
# This project deploys to its OWN Hosting site via the "cfb" target, never to
# the project default. The Family Dashboard lives on the default site and a
# deploy replaces a site's entire contents, so every firebase command below is
# scoped with :cfb. Do not remove that suffix.

PY   ?= python3
SITE ?= cfb-grid

.PHONY: help setup init-site preview build deploy check clean

help:
	@echo "make setup      - check prerequisites and target wiring"
	@echo "make init-site  - create the Hosting site and bind the cfb target (once)"
	@echo "make preview    - build next Saturday and open it in a browser"
	@echo "make build      - build into public/ (no deploy)"
	@echo "make deploy     - build, then push to the cfb site only"
	@echo "make check      - build a known week and print a summary"
	@echo ""
	@echo "Pin a date on any target:  make preview DATE=2026-09-12"
	@echo "Choose a site name:        make init-site SITE=smith-cfb-grid"

setup:
	@$(PY) -c 'import sys; assert sys.version_info>=(3,9), "need Python 3.9+"; print("python", sys.version.split()[0], "ok")'
	@command -v firebase >/dev/null 2>&1 \
		&& echo "firebase-cli $$(firebase --version) ok" \
		|| { echo "firebase CLI missing:  brew install node && npm i -g firebase-tools"; exit 1; }
	@$(PY) check_target.py

# Run once. Site names are globally unique across all of Firebase, so if this
# fails with "already exists" the name is taken by someone else — pick another.
init-site:
	firebase hosting:sites:create $(SITE)
	firebase target:apply hosting cfb $(SITE)
	@echo "bound cfb -> $(SITE). Your link will be https://$(SITE).web.app"

build:
	$(PY) build.py $(if $(DATE),--date $(DATE),) $(if $(WEEKS),--weeks $(WEEKS),)

preview: build
	open public/index.html

# --only hosting:cfb, never plain 'hosting'. The dashboard is on another site.
deploy: setup build
	firebase deploy --only hosting:cfb

check:
	$(PY) build.py --date 2026-09-12 --weeks 2
	@echo "--- sanity ---"
	@$(PY) -c "import json;d=json.load(open('public/schedule.json'));\
print('generated:', d['generated']);\
[print(' ', w['saturday'], 'networks=%d streaming=%d' % (len(w['rows']), len(w['stream']))) for w in d['weeks']]"

clean:
	rm -rf public/index.html public/schedule.json out __pycache__ .firebase
