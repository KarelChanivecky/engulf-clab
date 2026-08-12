from __future__ import annotations

import re

from engulf_api import ApplicationMetadata

ENSURE_VRNETLAB_PLUGIN_ID = "engulf_clab.ensure_vrnetlab"
VRNETLAB_PATH_CONTEXT = "engulf_clab.vrnetlab.path"
VRNETLAB_REPOSITORY_LEASE = "repository-cache:vrnetlab"
VRNETLAB_IMAGE_PATH_ENV = "ECLAB_VRNETLAB_IMG_PATH"
DEFAULT_APPLICATION_NAME = "eclab"
VRNETLAB_TYPE_ENV = "ECLAB_VRNETLAB_TYPE"
LEGACY_VRNETLAB_TYPE_ENV = "ECLAB_VRNETLAB_TYPE"
LEGACY_VRNETLAB_IMAGE_PATH_ENV = "ECLAB_VRNETLAB_IMG_PATH"

_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


def environment_prefix(application_name: str) -> str:
    """Derive a portable uppercase environment prefix from an application name."""
    normalized = _NON_ALPHANUMERIC.sub("_", application_name.upper()).strip("_")
    if not normalized:
        raise ValueError(
            f"cannot derive an environment prefix from application name {application_name!r}"
        )
    return normalized


def application_prefix_name(application: ApplicationMetadata) -> str:
    """Select the short product name, falling back for older metadata."""
    short_name = getattr(application, "short_product_name", None)
    if isinstance(short_name, str) and short_name.strip():
        return short_name
    product = application.product
    if isinstance(product, str) and product.strip():
        return product
    raise ValueError("application product metadata must be a nonempty string")


def vrnetlab_type_env(application_name: str) -> str:
    return f"{environment_prefix(application_name)}_VRNETLAB_TYPE"


def vrnetlab_image_path_env(application_name: str) -> str:
    return f"{environment_prefix(application_name)}_VRNETLAB_IMG_PATH"
