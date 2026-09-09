from __future__ import annotations

from pathlib import Path

from engulf_api import BeforeGoalAPI, Invocation
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    PluginSchema,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import (
    IMAGE_PROVIDER_CONTEXT,
    DockerfileRecipe,
    ImageProviderPlugin,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
    register_image_provider,
)

IMAGE = "engulf-clab.pki-linux-core/runtime:latest"
PROVIDER_ID = "engulf_clab.pki_linux_core.images"
_ROOT = Path(__file__).resolve().parent


class _Provider:
    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        if requirement.canonical_reference != IMAGE:
            return None
        return ImageProviderResponse(
            ImageProvision(IMAGE, DockerfileRecipe(_ROOT / "asset" / "Dockerfile", _ROOT / "asset")),
            authority=ProvisionAuthority.AUTHORITATIVE,
        )


SCHEMA = (
    PluginSchema("engulf_clab.pki_linux_core", package="engulf_clab_pki_linux_core")
    .add_node_var(
        "ECLAB_PKI_REQUIRED",
        "Fail startup instead of treating a missing PKI mount as a no-op.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_node_var(
        "ECLAB_PKI_SYSTEM_TRUST",
        "Augment the system trust store or isolate supported programs to projected trust.",
        values=("augment", "isolated"),
        default="augment",
    )
    .add_node_var(
        "ECLAB_PKI_IDENTITY_DEFAULT",
        "Select the canonical fallback leaf identity for non-browser adapters.",
        values=ValueType.STRING,
    )
    .add_node_var(
        "ECLAB_PKI_IDENTITY_*",
        "Override the selected identity for one detected non-browser program adapter.",
        values=ValueType.STRING,
    )
    .add_node_var(
        "ECLAB_PKI_BROWSER_CLIENT_CERTS",
        "Map explicit HTTPS origins to browser client identities with a JSON array.",
        values=ValueType.STRING,
    )
    .use_case("Build the distribution-neutral Linux PKI runtime asset image.")
    .use_case("Apply resolved node CA trust to Chrome/Chromium and managed Firefox NSS stores.")
    .reject("Do not use a general identity selector for automatic browser transmission.")
    .refer("USAGE.md")
)


class Plugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.pki_linux_core"
    schema = SCHEMA
    context_reads = frozenset({IMAGE_PROVIDER_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = frozenset({IMAGE_PROVIDER_CONTEXT}) | SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> None:
        del invocation
        record_plugin_schema(api, SCHEMA)
        register_image_provider(api, RegisteredImageProvider(PROVIDER_ID, _PROVIDER))


_PROVIDER = _Provider()
plugin = Plugin()
image_plugin = ImageProviderPlugin(PROVIDER_ID, _PROVIDER)
