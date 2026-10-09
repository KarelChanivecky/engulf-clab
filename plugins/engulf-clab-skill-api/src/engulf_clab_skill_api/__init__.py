"""Path-based skill contributions for eclab plugins."""

from .context import (
    SKILL_CONTEXTS,
    SKILL_PATHS_CONTEXT,
    SKILL_TRACKED_TARGETS_CONTEXT,
    publish_tracked_skill_targets,
    record_skill,
    skill_paths,
    tracked_skill_names,
    tracked_skill_targets,
)
from .static import (
    INSTALL_COMMAND,
    SKILL_CONTRIBUTION_CONTEXTS,
    contribute_static_skill,
    explicit_install,
    skip_contribution,
    tracked_target_exists,
)
from .temporary import (
    SKILL_TEMPORARY_PATHS_CONTEXT,
    record_temporary_skill,
    temporary_skill_paths,
)

__all__ = [
    "INSTALL_COMMAND",
    "SKILL_CONTEXTS",
    "SKILL_CONTRIBUTION_CONTEXTS",
    "SKILL_PATHS_CONTEXT",
    "SKILL_TEMPORARY_PATHS_CONTEXT",
    "SKILL_TRACKED_TARGETS_CONTEXT",
    "contribute_static_skill",
    "explicit_install",
    "publish_tracked_skill_targets",
    "record_skill",
    "record_temporary_skill",
    "skill_paths",
    "skip_contribution",
    "temporary_skill_paths",
    "tracked_skill_names",
    "tracked_skill_targets",
    "tracked_target_exists",
]
