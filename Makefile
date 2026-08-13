PYTHON := .venv/bin/python
PACKAGE_DIRS := \
	plugins/engulf-clab-containers-api \
	plugins/engulf-clab-lab-parser \
	plugins/engulf-clab-lab-writer \
	plugins/engulf-clab-ensure-checkout \
	plugins/engulf-clab-ensure-containerlab \
	plugins/engulf-clab-ensure-vrnetlab \
	plugins/engulf-clab-dockerfile-build \
	plugins/engulf-clab-containers \
	plugins/engulf-clab-containers-core \
	plugins/engulf-clab-vrnetlab-build \
	plugins/engulf-clab-wan \
	plugins/engulf-clab-license-pool \
	plugins/engulf-clab-freeze \
	plugins/engulf-clab-all-plugins \
	engulf-clab \
	mcp-server

.PHONY: environment clean-dist build publish

environment:
	@if [ ! -d .venv ]; then \
		command -v python3.14 >/dev/null 2>&1 || { echo "error: Python 3.14 is required" >&2; exit 1; }; \
		python3.14 -m venv --upgrade-deps .venv; \
	elif [ ! -x "$(PYTHON)" ]; then \
		echo "error: .venv is not a usable virtual environment" >&2; \
		exit 1; \
	fi
	@$(PYTHON) -m pip install \
		'build>=1.5,<2' \
		'hatchling>=1.31,<2' \
		'twine>=7,<8'

clean-dist:
	rm -rf -- dist

build: environment clean-dist
	@set -eu; \
	for package in $(PACKAGE_DIRS); do \
		output="dist/$$(basename "$$package")"; \
		mkdir -p "$$output"; \
		$(PYTHON) -m build --no-isolation --outdir "$$output" "$$package"; \
	done
	@$(PYTHON) -m twine check dist/*/*

publish: build
	@test -n "$${TWINE_REPOSITORY_URL:-}" || { \
		echo "error: TWINE_REPOSITORY_URL is required" >&2; \
		exit 1; \
	}
	@$(PYTHON) -m twine upload --repository-url "$$TWINE_REPOSITORY_URL" dist/*/*
