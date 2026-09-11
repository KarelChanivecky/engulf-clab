# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, source, schema, help, and tests together.
- Own persistence and deploy/redeploy observation in this plugin.
- Expose records only through `engulf-clab-lab-registry-api`.
- Keep transactions short and never change a goal result because tracking failed.
- Retain records on destroy and avoid recursive filesystem discovery.
- Keep Docker observation read-only and mock it in tests.
- Declare ordering in packaging and run registry, API, consumer, and skill tests.
