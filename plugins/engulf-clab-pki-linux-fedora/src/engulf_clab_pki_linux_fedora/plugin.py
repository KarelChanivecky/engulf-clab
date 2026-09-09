from __future__ import annotations

from pathlib import Path

from engulf_api import BeforeGoalAPI, Invocation
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    PluginSchema,
    SchemaBackedPlugin,
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

IMAGE = "engulf-clab.pki-linux-fedora/installer:latest"
PROVIDER_ID = "engulf_clab.pki_linux_fedora.images"
_ASSET = Path(__file__).resolve().parent / "asset"
class _Provider:
    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        if requirement.canonical_reference != IMAGE:
            return None
        return ImageProviderResponse(ImageProvision(IMAGE, DockerfileRecipe(_ASSET / "Dockerfile", _ASSET)), authority=ProvisionAuthority.AUTHORITATIVE)
SCHEMA = (
    PluginSchema("engulf_clab.pki_linux_fedora", package="engulf_clab_pki_linux_fedora")
    .use_case("Build the Fedora-family Linux PKI installer asset.")
    .refer("USAGE.md")
)
class Plugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.pki_linux_fedora"
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
