"""eclab adapter for application-neutral Docker image resolution."""

from .plugin import IMAGE_BUILD_PLUGIN_ID, ImageBuildPlugin, image_build_jobs, plugin

__all__ = ["IMAGE_BUILD_PLUGIN_ID", "ImageBuildPlugin", "image_build_jobs", "plugin"]
