from __future__ import annotations

ENSURE_VRNETLAB_PLUGIN_ID = "engulf_clab.ensure_vrnetlab"
VRNETLAB_PATH_CONTEXT = "engulf_clab.vrnetlab.path"
VRNETLAB_REPOSITORY_LEASE = "repository-cache:vrnetlab"

# Fixed across every edition, matching engulf-clab-wan's LABEL_PREFIX
# convention: labels/env vars must stay portable regardless of the active
# application's product metadata.
LABEL_PREFIX = "ECLAB"
VRNETLAB_TYPE_ENV = f"{LABEL_PREFIX}_VRNETLAB_TYPE"
VRNETLAB_IMAGE_PATH_ENV = f"{LABEL_PREFIX}_VRNETLAB_IMG_PATH"

# Distinct, older alias names kept for backward compatibility; unrelated to
# the edition-prefix question above.
LEGACY_VRNETLAB_TYPE_ENV = VRNETLAB_TYPE_ENV
LEGACY_VRNETLAB_IMAGE_PATH_ENV = VRNETLAB_IMAGE_PATH_ENV


def vrnetlab_type_env() -> str:
    return VRNETLAB_TYPE_ENV


def vrnetlab_image_path_env() -> str:
    return VRNETLAB_IMAGE_PATH_ENV
