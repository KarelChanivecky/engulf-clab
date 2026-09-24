"""User-visible vrnetlab source names owned by this provider."""

LABEL_PREFIX = "ECLAB"
VRNETLAB_TYPE_ENV = f"{LABEL_PREFIX}_VRNETLAB_TYPE"
VRNETLAB_IMAGE_PATH_ENV = f"{LABEL_PREFIX}_VRNETLAB_IMG_PATH"
LEGACY_VRNETLAB_IMAGE_PATH_ENV = VRNETLAB_IMAGE_PATH_ENV


def vrnetlab_type_env() -> str:
    return VRNETLAB_TYPE_ENV


def vrnetlab_image_path_env() -> str:
    return VRNETLAB_IMAGE_PATH_ENV
