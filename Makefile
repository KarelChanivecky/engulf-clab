PYTHON := .venv/bin/python
PACKAGES := \
	engulf-clab-schema-api \
	engulf-clab-lab-registry-api \
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
	engulf-clab-sticky-ip \
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
	engulf-clab-license-pool-lib \
	engulf-clab-license-pool \
	engulf-clab-freeze \
	engulf-clab-lab-registry \
	engulf-clab-reclaim \
	engulf-clab-consumption \
	engulf-clab-pki \
	engulf-clab-pki-linux-core \
	engulf-clab-pki-linux-debian \
	engulf-clab-pki-linux-fedora \
	engulf-clab-containers-pki \
	engulf-clab-vrnetlab-fortigate-pki-injector \
	engulf-clab-all-plugins \
	engulf-clab \
	engulf-clab-demo-lab \
	engulf-clab-mcp

# Package name -> source directory
DIR_engulf-clab-schema-api := plugins/engulf-clab-schema-api
DIR_engulf-clab-lab-registry-api := plugins/engulf-clab-lab-registry-api
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
DIR_engulf-clab-sticky-ip := plugins/engulf-clab-sticky-ip
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
DIR_engulf-clab-license-pool-lib := plugins/engulf-clab-license-pool-lib
DIR_engulf-clab-license-pool := plugins/engulf-clab-license-pool
DIR_engulf-clab-freeze := plugins/engulf-clab-freeze
DIR_engulf-clab-lab-registry := plugins/engulf-clab-lab-registry
DIR_engulf-clab-reclaim := plugins/engulf-clab-reclaim
DIR_engulf-clab-consumption := plugins/engulf-clab-consumption
DIR_engulf-clab-pki := plugins/engulf-clab-pki
DIR_engulf-clab-pki-linux-core := plugins/engulf-clab-pki-linux-core
DIR_engulf-clab-pki-linux-debian := plugins/engulf-clab-pki-linux-debian
DIR_engulf-clab-pki-linux-fedora := plugins/engulf-clab-pki-linux-fedora
DIR_engulf-clab-containers-pki := plugins/engulf-clab-containers-pki
DIR_engulf-clab-vrnetlab-fortigate-pki-injector := plugins/engulf-clab-vrnetlab-fortigate-pki-injector
DIR_engulf-clab-all-plugins := plugins/engulf-clab-all-plugins
DIR_engulf-clab := engulf-clab
DIR_engulf-clab-demo-lab := demo-lab
DIR_engulf-clab-mcp := mcp-server

dir_of = $(DIR_$1)

.PHONY: all environment clean-dist build check-skill check-demo-lab

# Default target: build and validate every distribution.
all: build

environment:
	@if [ ! -d .venv ]; then \
		command -v python3.12 >/dev/null 2>&1 || { echo "error: Python 3.12 is required" >&2; exit 1; }; \
		python3.12 -m venv --upgrade-deps .venv; \
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

check-skill:
	@$(PYTHON) -m pytest -q \
		plugins/engulf-clab-schema-api/tests \
		plugins/engulf-clab-schema/tests \
		plugins/engulf-clab-develop-eclab-lab/tests

check-demo-lab:
	@PYTHONPATH=demo-lab/src $(PYTHON) -m pytest -q demo-lab/tests

# --- Per-package build rules ------------------------------------------------
#
# dist/<pkg>/.built stamps a successful build (rebuilt only when the package's
# own files change). `make build-<pkg>` builds one package; `make build` covers
# all of them.

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

endef

$(foreach pkg,$(PACKAGES),$(eval $(call package_rules,$(pkg))))
