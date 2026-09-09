from unittest.mock import Mock, patch

from engulf_api import BeforeGoalAPI
from engulf_docker_image_api import IMAGE_PROVIDER_CONTEXT, ImageRequirement
from engulf_docker_image_core import dockerfile_requirements

from engulf_clab_pki_linux_fedora.plugin import IMAGE, PROVIDER_ID, image_plugin, plugin


def test_installer_depends_on_core_runtime_asset() -> None:
    response = image_plugin.provide_image(ImageRequirement(IMAGE), object())
    assert response is not None and response.provision is not None
    dependencies = dockerfile_requirements(response.provision.recipe)
    assert "engulf-clab.pki-linux-core/runtime:latest" in {
        value.canonical_reference for value in dependencies
    }


def test_registers_provider_with_wrapper_application() -> None:
    api = Mock(spec=BeforeGoalAPI)
    api.get_context.return_value = ()

    with patch("engulf_clab_pki_linux_fedora.plugin.record_plugin_schema"):
        plugin.before_goal(object(), api)

    context, providers = api.set_context.call_args.args
    assert context == IMAGE_PROVIDER_CONTEXT
    assert tuple(value.provider_id for value in providers) == (PROVIDER_ID,)
