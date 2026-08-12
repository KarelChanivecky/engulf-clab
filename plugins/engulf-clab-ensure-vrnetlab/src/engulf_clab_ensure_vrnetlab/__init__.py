from __future__ import annotations

from .contract import (
    DEFAULT_APPLICATION_NAME,
    ENSURE_VRNETLAB_PLUGIN_ID,
    LEGACY_VRNETLAB_IMAGE_PATH_ENV,
    LEGACY_VRNETLAB_TYPE_ENV,
    VRNETLAB_IMAGE_PATH_ENV,
    VRNETLAB_PATH_CONTEXT,
    VRNETLAB_REPOSITORY_LEASE,
    VRNETLAB_TYPE_ENV,
    application_prefix_name,
    environment_prefix,
    vrnetlab_image_path_env,
    vrnetlab_type_env,
)
from .plugin import EnsureVrnetlabPlugin

plugin = EnsureVrnetlabPlugin()

__all__ = [
    "DEFAULT_APPLICATION_NAME",
    "ENSURE_VRNETLAB_PLUGIN_ID",
    "LEGACY_VRNETLAB_IMAGE_PATH_ENV",
    "LEGACY_VRNETLAB_TYPE_ENV",
    "VRNETLAB_IMAGE_PATH_ENV",
    "VRNETLAB_PATH_CONTEXT",
    "VRNETLAB_REPOSITORY_LEASE",
    "VRNETLAB_TYPE_ENV",
    "EnsureVrnetlabPlugin",
    "application_prefix_name",
    "environment_prefix",
    "plugin",
    "vrnetlab_image_path_env",
    "vrnetlab_type_env",
]
