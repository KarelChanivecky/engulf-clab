from __future__ import annotations

from pathlib import Path

from engulf_api import BeforeGoalAPI, GoalResult, Invocation
from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerImageProvider,
    ContainerNodeRequirements,
    RegisteredContainerCollection,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    ExplainedValue,
    LifecycleStage,
    PluginSchema,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import ImageProviderPlugin

_PACKAGE = Path(__file__).resolve().parent
_CONTEXT = _PACKAGE

DEBIAN = ContainerDefinition(
    name="debian",
    summary="Debian 13 base with eclab PKI trust bootstrap",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "debian" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(kind="linux"),
)

FEDORA = ContainerDefinition(
    name="fedora",
    summary="Fedora 44 base with eclab PKI trust bootstrap",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "fedora" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(kind="linux"),
)

PLUGIN_SCHEMA = (
    PluginSchema("eclab.containers.pki", package="engulf_clab_containers_pki")
    .add_node_prop(
        "image",
        "Select an ordinary image reference or a packaged PKI base.",
        values=(
            ValueType.IMAGE_REFERENCE,
            ExplainedValue(
                "eclab.containers.pki/debian",
                "Provide a Debian 13 base that applies projected eclab PKI trust at startup.",
            ),
            ExplainedValue(
                "eclab.containers.pki/fedora",
                "Provide a Fedora 44 base that applies projected eclab PKI trust at startup.",
            ),
        ),
    )
    .use_case("Use a PKI base directly or inherit it in a trust-aware application image.")
    .reject("Do not replace the inherited PKI entrypoint without preserving its wrapper.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "The collection is registered before the container manager resolves packaged images.",
        before=("engulf_clab.containers",),
    )
    .route(
        "build-pki-container",
        "USAGE.md",
        "Read the base-image inheritance and PKI runtime contract.",
    )
    .refer("USAGE.md")
    .refer("containers/debian/USAGE.md", title="Debian PKI base")
    .refer("containers/fedora/USAGE.md", title="Fedora PKI base")
)


class PkiContainerCollectionPlugin(ContainerCollectionPlugin):
    context_reads = ContainerCollectionPlugin.context_reads | SCHEMA_CONTEXTS
    context_writes = ContainerCollectionPlugin.context_writes | SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        result = super().before_goal(invocation, api)
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return result


_CONTAINERS = (DEBIAN, FEDORA)
plugin = PkiContainerCollectionPlugin("eclab.containers.pki", _CONTAINERS)
image_plugin = ImageProviderPlugin(
    "eclab.containers.pki.images",
    ContainerImageProvider(
        (RegisteredContainerCollection("eclab.containers.pki", _CONTAINERS),)
    ),
)
