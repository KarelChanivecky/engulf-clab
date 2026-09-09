from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import BeforeGoalAPI
from engulf_docker_image_api import IMAGE_PROVIDER_CONTEXT, ImageRequirement

from engulf_clab_pki_linux_core.plugin import IMAGE, PROVIDER_ID, image_plugin, plugin


def test_provides_only_canonical_runtime_asset() -> None:
    response = image_plugin.provide_image(ImageRequirement(IMAGE), object())
    assert response is not None and response.provision is not None
    assert response.provision.canonical_image == IMAGE
    assert Path(response.provision.recipe.dockerfile).is_file()
    assert image_plugin.provide_image(ImageRequirement("example/other"), object()) is None


def test_registers_provider_with_wrapper_application() -> None:
    api = Mock(spec=BeforeGoalAPI)
    api.get_context.return_value = ()

    with patch("engulf_clab_pki_linux_core.plugin.record_plugin_schema"):
        plugin.before_goal(object(), api)

    context, providers = api.set_context.call_args.args
    assert context == IMAGE_PROVIDER_CONTEXT
    assert tuple(value.provider_id for value in providers) == (PROVIDER_ID,)
