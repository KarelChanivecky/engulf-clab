"""Install the skill embedded in the wheel into a Codex skills directory."""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
import time
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import NoReturn

SKILL_NAME = "engulf-clab-develop-eclab-lab"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def bundled_skill() -> Traversable | Path:
    bundle = resources.files("develop_eclab_lab_skill").joinpath("bundle")
    if bundle.is_dir():
        return bundle
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "SKILL.md").is_file():
        return source_root
    fail("the installed package does not contain its bundled skill")


def copy_traversable(source: Traversable | Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            if child.name in {"agents", "references"}:
                copy_traversable(child, target)
        elif child.name == "SKILL.md" or child.name.endswith((".md", ".yaml")):
            with child.open("rb") as source_file, target.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)


def same_tree(left: Path, right: Path) -> bool:
    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    if any(
        not filecmp.cmp(left / name, right / name, shallow=False)
        for name in comparison.common_files
    ):
        return False
    return all(same_tree(left / name, right / name) for name in comparison.common_dirs)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="engulf-clab-develop-eclab-lab-install",
        description=__doc__,
        epilog=(
            "Defaults may also be set with DEVELOP_ECLAB_LAB_SKILLS_DIR and "
            "DEVELOP_ECLAB_LAB_BACKUP_DIR. Otherwise the skills directory is "
            "$CODEX_HOME/skills, falling back to ~/.codex/skills. Explicit "
            "options take precedence."
        ),
    )
    configured_skills = os.environ.get("DEVELOP_ECLAB_LAB_SKILLS_DIR")
    if configured_skills is not None:
        default_skills = Path(configured_skills)
    else:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        default_skills = codex_home / "skills"
    default_backups = Path(
        os.environ.get(
            "DEVELOP_ECLAB_LAB_BACKUP_DIR",
            Path.home() / ".local" / "state" / SKILL_NAME / "backups",
        )
    )
    result.add_argument(
        "--skills-dir",
        type=Path,
        default=default_skills,
        help=f"parent directory for installed skills (default: {default_skills})",
    )
    result.add_argument(
        "--backup-dir",
        type=Path,
        default=default_backups,
        help=f"directory for recognized previous installations (default: {default_backups})",
    )
    result.add_argument(
        "--check",
        action="store_true",
        help="compare the installed tree with this package without replacing it",
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    source = bundled_skill()
    skills_dir = arguments.skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME

    if arguments.check:
        if not target.is_dir() or target.is_symlink():
            fail(f"{target} is not a standalone installed skill")
        staging = skills_dir / f".{SKILL_NAME}.check"
        if staging.exists():
            fail(f"temporary path already exists: {staging}")
        try:
            copy_traversable(source, staging)
            if not same_tree(staging, target):
                fail(f"{target} differs from the packaged skill")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"{target} is current")
        return 0

    skills_dir.mkdir(parents=True, exist_ok=True)
    staging = skills_dir / f".{SKILL_NAME}.installing"
    if staging.exists():
        fail(f"temporary path already exists: {staging}")
    copy_traversable(source, staging)

    try:
        if target.is_dir() and not target.is_symlink() and same_tree(staging, target):
            print(f"{target} is already installed and current")
            return 0
        if target.exists() or target.is_symlink():
            definition = target / "SKILL.md" if target.is_dir() else None
            if (
                definition is None
                or not definition.is_file()
                or "name: engulf-clab-develop-eclab-lab" not in definition.read_text(encoding="utf-8")
            ):
                fail(f"refusing to replace unrecognized path: {target}")
            arguments.backup_dir.mkdir(parents=True, exist_ok=True)
            backup = arguments.backup_dir / f"{SKILL_NAME}-{os.getpid()}-{time.time_ns()}"
            if backup.exists():
                fail(f"backup path already exists: {backup}")
            target.replace(backup)
            print(f"backed up the previous installation to {backup}")
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(f"installed {SKILL_NAME} to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
