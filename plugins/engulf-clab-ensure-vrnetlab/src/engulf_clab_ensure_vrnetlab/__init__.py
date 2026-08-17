from __future__ import annotations

from .contract import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    LABEL_PREFIX,
    LEGACY_VRNETLAB_IMAGE_PATH_ENV,
    LEGACY_VRNETLAB_TYPE_ENV,
    VRNETLAB_IMAGE_PATH_ENV,
    VRNETLAB_PATH_CONTEXT,
    VRNETLAB_REPOSITORY_LEASE,
    VRNETLAB_TYPE_ENV,
    vrnetlab_image_path_env,
    vrnetlab_type_env,
)
from .plugin import EnsureVrnetlabPlugin

plugin = EnsureVrnetlabPlugin()

__all__ = [
    "ENSURE_VRNETLAB_PLUGIN_ID",
    "LABEL_PREFIX",
    "LEGACY_VRNETLAB_IMAGE_PATH_ENV",
    "LEGACY_VRNETLAB_TYPE_ENV",
    "VRNETLAB_IMAGE_PATH_ENV",
    "VRNETLAB_PATH_CONTEXT",
    "VRNETLAB_REPOSITORY_LEASE",
    "VRNETLAB_TYPE_ENV",
    "EnsureVrnetlabPlugin",
    "plugin",
    "vrnetlab_image_path_env",
    "vrnetlab_type_env",
]
