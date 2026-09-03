PYTHON := .venv/bin/python
PACKAGES := \
	engulf-clab-schema-api \
	engulf-clab-freeze-api \
	engulf-clab-pki-api \
	engulf-clab-schema \
	engulf-clab-develop-eclab-lab \
	engulf-clab-develop-eclab-lab-static \
	engulf-docker-image-api \
	engulf-docker-image-core \
	engulf-clab-containers-api \
	engulf-clab-lab-parser \
	engulf-clab-lab-writer \
	engulf-clab-ensure-checkout \
	engulf-clab-ensure-containerlab \
	engulf-clab-ensure-vrnetlab \
	engulf-clab-image-build \
	engulf-clab-dockerfile-build \
	engulf-clab-image-archive \
	engulf-clab-containers \
	engulf-clab-containers-core \
	engulf-clab-vrnetlab-build \
	engulf-clab-wan \
	engulf-clab-license-pool \
	engulf-clab-freeze \
	engulf-clab-pki \
	engulf-clab-vrnetlab-fortigate-pki-injector \
	engulf-clab-all-plugins \
	engulf-clab \
	engulf-clab-demo-lab \
	engulf-clab-mcp

# Package name -> source directory
DIR_engulf-clab-schema-api := plugins/engulf-clab-schema-api
DIR_engulf-clab-freeze-api := plugins/engulf-clab-freeze-api
DIR_engulf-clab-pki-api := plugins/engulf-clab-pki-api
DIR_engulf-clab-schema := plugins/engulf-clab-schema
DIR_engulf-clab-develop-eclab-lab := plugins/engulf-clab-develop-eclab-lab
DIR_engulf-clab-develop-eclab-lab-static := skills/engulf-clab-develop-eclab-lab-static
DIR_engulf-docker-image-api := plugins/engulf-docker-image-api
DIR_engulf-docker-image-core := plugins/engulf-docker-image-core
DIR_engulf-clab-containers-api := plugins/engulf-clab-containers-api
DIR_engulf-clab-lab-parser := plugins/engulf-clab-lab-parser
DIR_engulf-clab-lab-writer := plugins/engulf-clab-lab-writer
DIR_engulf-clab-ensure-checkout := plugins/engulf-clab-ensure-checkout
DIR_engulf-clab-ensure-containerlab := plugins/engulf-clab-ensure-containerlab
DIR_engulf-clab-ensure-vrnetlab := plugins/engulf-clab-ensure-vrnetlab
DIR_engulf-clab-image-build := plugins/engulf-clab-image-build
DIR_engulf-clab-dockerfile-build := plugins/engulf-clab-dockerfile-build
DIR_engulf-clab-image-archive := plugins/engulf-clab-image-archive
DIR_engulf-clab-containers := plugins/engulf-clab-containers
DIR_engulf-clab-containers-core := plugins/engulf-clab-containers-core
DIR_engulf-clab-vrnetlab-build := plugins/engulf-clab-vrnetlab-build
DIR_engulf-clab-wan := plugins/engulf-clab-wan
DIR_engulf-clab-license-pool := plugins/engulf-clab-license-pool
DIR_engulf-clab-freeze := plugins/engulf-clab-freeze
DIR_engulf-clab-pki := plugins/engulf-clab-pki
DIR_engulf-clab-vrnetlab-fortigate-pki-injector := plugins/engulf-clab-vrnetlab-fortigate-pki-injector
DIR_engulf-clab-all-plugins := plugins/engulf-clab-all-plugins
DIR_engulf-clab := engulf-clab
DIR_engulf-clab-demo-lab := demo-lab
DIR_engulf-clab-mcp := mcp-server

dir_of = $(DIR_$1)

.PHONY: all environment clean-dist build publish check-skill check-demo-lab

# Default target: build everything, then upload whatever was not published yet.
all: build publish

environment:
	@if [ ! -d .venv ]; then \
		command -v python3.14 >/dev/null 2>&1 || { echo "error: Python 3.14 is required" >&2; exit 1; }; \
		python3.14 -m venv --upgrade-deps .venv; \
	elif [ ! -x "$(PYTHON)" ]; then \
		echo "error: .venv is not a usable virtual environment" >&2; exit 1; \
	fi
	@$(PYTHON) -m pip install \
		'build>=1.5,<2' \
		'hatchling>=1.31,<2' \
		'twine>=7,<8'

clean-dist:
	rm -rf -- dist

build: $(PACKAGES:%=dist/%/.built)

publish: $(PACKAGES:%=publish-%)

check-skill:
	@$(PYTHON) -m pytest -q \
		plugins/engulf-clab-schema-api/tests \
		plugins/engulf-clab-schema/tests \
		plugins/engulf-clab-develop-eclab-lab/tests

check-demo-lab:
	@PYTHONPATH=demo-lab/src $(PYTHON) -m pytest -q demo-lab/tests

# --- Per-package build / publish rules --------------------------------------
#
# dist/<pkg>/.built stamps a successful build (rebuilt only when the package's
# own files change); dist/<pkg>/.published stamps a successful upload of that
# build and is wiped by every rebuild. Stamps can lie (switched
# TWINE_REPOSITORY_URL, wiped/rebuilt server), so check-<pkg>-published — an
# order-only phony prerequisite of .published — runs on every publish
# invocation and re-validates the stamp against the live PEP 503 index,
# deleting it when the server does not host the built files. Once the checker
# has run, Make's mtime logic decides: stamp present and newer than .built →
# skip the upload; stamp removed or wiped by a rebuild → upload. The upload
# still passes --skip-existing as the final arbiter.
# `make build-<pkg>` / `make publish-<pkg>` work on a single package;
# `make build` / `make publish` cover all of them.

define package_rules

.PHONY: build-$1

$1_files := $(shell find $(DIR_$1) -type f -not -path '*/__pycache__/*' -not -name '*.pyc')

dist/$1/.built: $$($1_files) | environment
	@rm -rf -- dist/$1
	@mkdir -p dist/$1
	$(PYTHON) -m build --no-isolation --outdir dist/$1 $(DIR_$1)
	@$(PYTHON) -m twine check dist/$1/*
	@touch $$@

build-$1: dist/$1/.built

# Order-only phony checker: re-validate the publish against what the server
# actually hosts (simple-index anchors carry the exact file names, version
# included, so this detects "server has 0.1, local has 0.2"; it never clears
# the stamp for the wrong server because the URL is part of the query). An
# unreachable server keeps the stamp — the upload's --skip-existing is the
# final arbiter anyway.
.PHONY: check-$1-published publish-$1

check-$1-published:
	@test -n "$$$${TWINE_REPOSITORY_URL:-}" || { echo "error: TWINE_REPOSITORY_URL is required" >&2; exit 1; }
	@[ -d dist/$1 ] || exit 0
	@$(PYTHON) check_published.py "$$$$TWINE_REPOSITORY_URL" $1 dist/$1 || \
		if [ $$$$? -eq 1 ]; then rm -f dist/$1/.published; else exit 0; fi

dist/$1/.published: dist/$1/.built | check-$1-published
	@test -n "$$$${TWINE_USERNAME:-}" || { echo "error: TWINE_USERNAME and TWINE_PASSWORD are required (or run through publish.sh with the managed repository)" >&2; exit 1; }
	@test -n "$$$${TWINE_PASSWORD:-}" || { echo "error: TWINE_USERNAME and TWINE_PASSWORD are required (or run through publish.sh with the managed repository)" >&2; exit 1; }
	$(PYTHON) twine_upload.py upload --skip-existing --repository-url "$$$$TWINE_REPOSITORY_URL" dist/$1/*
	@touch $$@

publish-$1: dist/$1/.published

endef

$(foreach pkg,$(PACKAGES),$(eval $(call package_rules,$(pkg))))
