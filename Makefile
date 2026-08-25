PYTHON := .venv/bin/python
SKILL_PACKAGE_DIR := plugins/engulf-clab-develop-lab-skill
SKILL_DISTRIBUTION := engulf-clab-develop-eclab-lab
STATIC_SKILL_PACKAGE_DIR := skills/engulf-clab-develop-eclab-lab-static
STATIC_SKILL_DISTRIBUTION := engulf-clab-develop-eclab-lab-static
PACKAGE_DIRS := \
	plugins/engulf-clab-schema-api \
	plugins/engulf-clab-schema \
	plugins/engulf-clab-develop-lab-skill \
	skills/engulf-clab-develop-eclab-lab-static \
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

.PHONY: environment clean-dist build publish check-skill

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
	@test -n "$$(find "dist/$$(basename "$(SKILL_PACKAGE_DIR)")" -maxdepth 1 -type f -name 'engulf_clab_develop_eclab_lab-*.whl' -print -quit)" || { \
		echo "error: $(SKILL_DISTRIBUTION) wheel is missing from the release artifacts" >&2; \
		exit 1; \
	}
	@test -n "$$(find "dist/$$(basename "$(SKILL_PACKAGE_DIR)")" -maxdepth 1 -type f -name 'engulf_clab_develop_eclab_lab-*.tar.gz' -print -quit)" || { \
		echo "error: $(SKILL_DISTRIBUTION) sdist is missing from the release artifacts" >&2; \
		exit 1; \
	}
	@test -n "$$(find "dist/$$(basename "$(STATIC_SKILL_PACKAGE_DIR)")" -maxdepth 1 -type f -name 'engulf_clab_develop_eclab_lab_static-*.whl' -print -quit)" || { \
		echo "error: $(STATIC_SKILL_DISTRIBUTION) wheel is missing from the release artifacts" >&2; \
		exit 1; \
	}
	@test -n "$$(find "dist/$$(basename "$(STATIC_SKILL_PACKAGE_DIR)")" -maxdepth 1 -type f -name 'engulf_clab_develop_eclab_lab_static-*.tar.gz' -print -quit)" || { \
		echo "error: $(STATIC_SKILL_DISTRIBUTION) sdist is missing from the release artifacts" >&2; \
		exit 1; \
	}
	@$(PYTHON) -m twine upload --repository-url "$$TWINE_REPOSITORY_URL" dist/*/*

check-skill:
	@$(PYTHON) -m pytest -q \
		plugins/engulf-clab-schema-api/tests \
		plugins/engulf-clab-schema/tests \
		plugins/engulf-clab-develop-lab-skill/tests
