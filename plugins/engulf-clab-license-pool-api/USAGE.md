# License-pool metadata contributor contract

Install this API alongside `engulf-clab-license-pool` when adding an edition
or plugin that needs to store metadata beside a license pool.

Publish one object in the `engulf_clab.license_pool.metadata.v1` entry-point
group. Its entry-point name must match the object's `contributor_id`. Implement
`collect_metadata(context)`, returning a JSON-compatible mapping of changed
fields or `None` when no change is needed. Optionally expose a tuple of
`LicensePoolVariable` declarations as `metadata_variables`; the shared pool
collector then validates, prompts for, and stores those fields for you.

```python
from typing import Any, Mapping

from engulf_clab_license_pool_api import (
    LicensePoolMetadataContext,
    LicensePoolVariable,
    LicensePoolVariableType,
)


class ExampleMetadata:
    contributor_id = "example.edition"
    metadata_variables = (
        LicensePoolVariable(
            name="region",
            type=LicensePoolVariableType.CHOICE,
            description="Select the license region",
            choices=("west", "central", "east"),
            default="west",
        ),
        LicensePoolVariable(
            name="allowed-products",
            type=LicensePoolVariableType.STRING_LIST,
            description="Enter allowed product names",
            default=("router", "switch"),
        ),
    )

    def resolve_variable_values(
        self, context: LicensePoolMetadataContext
    ) -> Mapping[str, Any]:
        # Resolve this contributor's explicit values from its own CLI flags
        # or environment. Values must match the declared Python types.
        region = context.environment.get("EXAMPLE_REGION")
        return {"region": region} if region is not None else {}

    def collect_metadata(self, context):
        # All resolved values are in context.variable_values and are written
        # by the collector; return only additional contributor-owned fields.
        return None
```

Supported declaration types are `string`, `string-list`, `choice`,
`multi-choice`, `boolean`, `integer`, and `float`. `choices` is required for
the two choice types. A `default` may be supplied for any type; it is shown in
interactive prompts and used automatically in noninteractive calls. Values
are saved as JSON strings, arrays of strings, booleans, integers, or floats.
Set `optional=True` to allow a missing value: Enter skips a missing optional
variable interactively, and a noninteractive call omits it when no default is
declared. On `--eclab-update`, an existing value is shown as the prompt default
and Enter keeps it. A declared default still applies to an optional variable.

The context includes the canonical pool directory, selected node kind, raw
`init-license-pool` arguments, invocation environment and current working
directory, your namespace's existing metadata, legacy flat metadata, and
`update` / `interactive` flags. Reuse your own stored fields on ordinary init;
a metadata file created by a different contributor does not imply that your
namespace is initialized. `--eclab-update` explicitly requests existing
metadata again. `context.variable_values` contains read-only typed values for
the declarations owned by this contributor. While calling the optional
`resolve_variable_values(context)`, it contains generic CLI overrides only;
when calling `collect_metadata(context)`, it contains every resolved value.
The collector writes those values after `collect_metadata()` returns, so
return only any additional metadata fields. Explicit CLI values remain usable
without update mode.

`resolve_variable_values(context)` is an optional contributor method that
returns typed values from contributor-specific flags, environment variables,
or other explicit sources. Return only declared variable names; unknown names
and values with the wrong declared type fail initialization. The resolution
order is:

1. `--eclab-licence-pool-var NAME=VALUE`.
2. Values returned by `resolve_variable_values(context)`.
3. Stored values on ordinary init.
4. An interactive answer when a value is missing or `--eclab-update` is used.
5. The declared default.

Its public signature is:

```python
def resolve_variable_values(
    self, context: LicensePoolMetadataContext
) -> Mapping[str, Any]: ...
```

On update, the stored value is shown as the prompt default. Without update,
stored values are reused without prompting.

The collector prompts for missing declarations on an interactive
`init-license-pool`, then reuses them on ordinary calls. A missing optional
declaration can be skipped with Enter. `--eclab-update` asks again; an existing
value is the prompt default, while a declared default is used for a missing
value and on noninteractive calls. A noninteractive missing required value
with no default must be provided explicitly:

```bash
eclab init-license-pool ./licenses \
  --eclab-licence-pool-var region=east \
  --eclab-licence-pool-var allowed-products='router;switch'
```

Repeat the flag for multiple variables. Use the bare variable name when it is
unique among installed contributors, or `contributor_id.variable` when names
overlap. `string-list` and `multi-choice` values use `;` between entries and
`;;` for a literal semicolon. Choice values must match a declared option;
booleans accept `true`/`false`, `yes`/`no`, `y`/`n`, and `1`/`0`.

The shared `.lic-pool` file uses this versioned structure after a contributor
adds metadata:

```json
{
  "version": 1,
  "contributors": {
    "example.edition": {
      "region": "lab-a"
    }
  }
}
```

Fields belong to the contributor namespace. Omitted fields keep their current
values; returning `null` for a field removes it. Existing unversioned flat
objects remain available to contributors as `legacy` and are preserved when
the collector writes an update. The collector performs the only shared-file
write, under the pool-registration lease, and writes atomically before it
registers the pool.

Do not write license contents, credentials, private license paths, or other
secrets into `.lic-pool`. A contributor must not mutate registry state or
perform registration itself.
