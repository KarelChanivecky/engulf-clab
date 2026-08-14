#!/usr/bin/env python3
"""Synchronize and validate the repository-owned develop-eclab-lab skill."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SKILL_RELATIVE = Path("skills/develop-eclab-lab")
FORBIDDEN = re.compile(r"forti", re.IGNORECASE)

LOCAL_SOURCES = {
    "README.md": "eclab.md",
    "AGENTS.md": "eclab-development.md",
    "CONTRIBUTING.md": "eclab-contributing.md",
    "engulf-clab/README.md": "eclab-wrapper.md",
    "mcp-server/README.md": "eclab-mcp.md",
    "mcp-server/AGENTS.md": "eclab-mcp-development.md",
    "mcp-server/etc/eclab-mcp/config.toml.example": "eclab-mcp-config.md",
    "plugins/engulf-clab-containers-api/README.md": "eclab-containers-api.md",
    "plugins/engulf-clab-containers-core/README.md": "eclab-containers-core.md",
    (
        "plugins/engulf-clab-containers-core/src/engulf_clab_containers_core/"
        "containers/host-connector/README.md"
    ): "eclab-container-host-connector.md",
    (
        "plugins/engulf-clab-containers-core/src/engulf_clab_containers_core/"
        "containers/ldap-389ds/README.md"
    ): "eclab-container-ldap-389ds.md",
    (
        "plugins/engulf-clab-containers-core/src/engulf_clab_containers_core/"
        "containers/proxy-node/README.md"
    ): "eclab-container-proxy-node.md",
    (
        "plugins/engulf-clab-containers-core/src/engulf_clab_containers_core/"
        "containers/ubuntu-firefox-gui/README.md"
    ): "eclab-container-ubuntu-firefox-gui.md",
    "plugins/engulf-clab-containers/README.md": "eclab-containers.md",
    "plugins/engulf-clab-dockerfile-build/README.md": "eclab-dockerfile-build.md",
    "plugins/engulf-clab-ensure-checkout/README.md": "eclab-ensure-checkout.md",
    "plugins/engulf-clab-ensure-containerlab/README.md": "eclab-ensure-containerlab.md",
    "plugins/engulf-clab-ensure-vrnetlab/README.md": "eclab-ensure-vrnetlab.md",
    "plugins/engulf-clab-freeze/README.md": "eclab-freeze.md",
    "plugins/engulf-clab-lab-parser/README.md": "eclab-lab-parser.md",
    "plugins/engulf-clab-lab-writer/README.md": "eclab-lab-writer.md",
    "plugins/engulf-clab-license-pool/README.md": "eclab-license-pool.md",
    "plugins/engulf-clab-vrnetlab-build/README.md": "eclab-vrnetlab-build.md",
    "plugins/engulf-clab-wan/README.md": "eclab-wan.md",
    "plugins/engulf-clab-all-plugins/README.md": "eclab-all-plugins.md",
    "plugins/engulf-clab-all-plugins/AGENTS.md": "eclab-all-plugins-development.md",
    "plugins/engulf-clab-containers-api/AGENTS.md": "eclab-containers-api-development.md",
    "plugins/engulf-clab-containers-core/AGENTS.md": "eclab-containers-core-development.md",
    "plugins/engulf-clab-containers/AGENTS.md": "eclab-containers-development.md",
    "plugins/engulf-clab-dockerfile-build/AGENTS.md": "eclab-dockerfile-build-development.md",
    "plugins/engulf-clab-ensure-checkout/AGENTS.md": "eclab-ensure-checkout-development.md",
    "plugins/engulf-clab-ensure-containerlab/AGENTS.md": "eclab-ensure-containerlab-development.md",
    "plugins/engulf-clab-ensure-vrnetlab/AGENTS.md": "eclab-ensure-vrnetlab-development.md",
    "plugins/engulf-clab-freeze/AGENTS.md": "eclab-freeze-development.md",
    "plugins/engulf-clab-lab-parser/AGENTS.md": "eclab-lab-parser-development.md",
    "plugins/engulf-clab-lab-writer/AGENTS.md": "eclab-lab-writer-development.md",
    "plugins/engulf-clab-license-pool/AGENTS.md": "eclab-license-pool-development.md",
    "plugins/engulf-clab-vrnetlab-build/AGENTS.md": "eclab-vrnetlab-build-development.md",
    "plugins/engulf-clab-wan/AGENTS.md": "eclab-wan-development.md",
}

ENGULF_SOURCES = {
    "AGENTS.md": "engulf-development.md",
    "engulf-api/README.md": "engulf-api.md",
    "engulf/README.md": "engulf-runtime.md",
    "engulf-executable-wrapper-api/README.md": "executable-wrapper-api.md",
    "engulf-executable-wrapper/README.md": "executable-wrapper.md",
    "plugins/engulf-plugin-list/README.md": "engulf-plugin-list.md",
}

NORMALIZATIONS = {
    "eclab-container-ldap-389ds.md": (
        ("FortiGate/EMS", "an appliance or management system"),
        ("FortiGate", "appliance"),
    ),
    "eclab-container-proxy-node.md": (
        ("FortiGate", "traffic-path appliance"),
    ),
    "eclab-license-pool.md": (
        ("    fgt:\n", "    router:\n"),
        ("vrnetlab/vr-fortios:latest", "vrnetlab/vr-router:latest"),
        ("FORTIGATE_LICENSES", "ROUTER_LICENSES"),
        ("licenses/fortigate", "licenses/router"),
    ),
    "eclab-vrnetlab-build.md": (
        ("    fgt:\n", "    router:\n"),
        ("kind: fortinet_fortigate", "kind: vendor_router"),
        ("vrnetlab/vr-fortios:8.0.0", "vrnetlab/vr-router:1.0.0"),
        ("fortinet/fortigate", "vendor/router"),
        ("fortios.qcow2", "router.qcow2"),
        ("`fgt-1`", "`router-1`"),
        ("MY_LAB_FGT_1_IMAGE_SOURCE", "MY_LAB_ROUTER_1_IMAGE_SOURCE"),
    ),
    "eclab-mcp.md": (
        ("FORTIGATE_LICENSES", "ROUTER_LICENSES"),
        ("licenses/fortigate", "licenses/router"),
        ("](etc/eclab-mcp/config.toml.example)",
         "](eclab-mcp-config.md)"),
    ),
    "eclab.md": (
        ("legacy\n`.forticlab` state", "managed\nlegacy state"),
        ("](mcp-server/README.md)", "](eclab-mcp.md)"),
        ("](CONTRIBUTING.md)", "](eclab-contributing.md)"),
        (
            "[`skills/README.md`](skills/README.md)",
            "`skills/README.md` in a source checkout",
        ),
    ),
    "eclab-freeze.md": (
        ("legacy `.forticlab` state", "legacy wrapper state"),
    ),
    "eclab-wan-development.md": (
        (
            (
                "- Do not create, read, migrate, or delete a topology-local "
                "`.forticlab/`\n  directory. Existing Forticlab state belongs to "
                "Forticlab.\n"
            ),
            (
                "- Do not create, read, migrate, or delete topology-local state owned "
                "by a\n  different wrapper.\n"
            ),
        ),
    ),
    "executable-wrapper.md": (
        (
            "](../engulf-executable-wrapper-api/README.md)",
            "](executable-wrapper-api.md)",
        ),
    ),
    "engulf-api.md": (
        (
            "](../engulf/README.md#authoring-a-diagnostic-extension)",
            "](engulf-runtime.md#authoring-a-diagnostic-extension)",
        ),
    ),
    "engulf-runtime.md": (
        (
            "](../plugins/engulf-plugin-list/README.md)",
            "](engulf-plugin-list.md)",
        ),
    ),
    "engulf-plugin-list.md": (
        (
            "](../../engulf/README.md#authoring-a-diagnostic-extension)",
            "](engulf-runtime.md#authoring-a-diagnostic-extension)",
        ),
    ),
}

MARKDOWN_WRAPPERS = {
    "eclab-mcp-config.md": (
        (
            "# eclab MCP configuration example\n\n"
            "This is the complete packaged example for the root-owned local service.\n\n"
            "```toml\n"
        ),
        "```\n",
    ),
}

_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_MIRRORED_ROOTS = (Path("engulf-clab"), Path("mcp-server"), Path("plugins"))
_IGNORED_DOCUMENT_PARTS = frozenset(
    {".git", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "build", "dist"}
)


class SkillError(RuntimeError):
    pass


def run_git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        check=check,
        capture_output=True,
    )


def normalize_reference(destination: str, text: str) -> str:
    for old, new in NORMALIZATIONS.get(destination, ()):
        text = text.replace(old, new)
    if destination in MARKDOWN_WRAPPERS:
        prefix, suffix = MARKDOWN_WRAPPERS[destination]
        text = prefix + text.rstrip() + "\n" + suffix
    match = FORBIDDEN.search(text)
    if match:
        line = text.count("\n", 0, match.start()) + 1
        raise SkillError(
            f"{destination}:{line}: vendor-specific text must be normalized before syncing"
        )
    return text.rstrip() + "\n"


def validate_markdown_links(root: Path, candidates: list[Path]) -> None:
    resolved_root = root.resolve()
    for candidate in sorted(candidates):
        text = candidate.read_text(encoding="utf-8")
        for match in _MARKDOWN_LINK.finditer(text):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and raw_target.endswith(">"):
                raw_target = raw_target[1:-1]
            target_without_fragment = raw_target.split("#", 1)[0]
            if not target_without_fragment:
                continue
            parsed = urlparse(target_without_fragment)
            if parsed.scheme or target_without_fragment.startswith("//"):
                continue
            relative = Path(unquote(target_without_fragment))
            resolved = (candidate.parent / relative).resolve()
            if not resolved.is_relative_to(resolved_root) or not resolved.exists():
                line = text.count("\n", 0, match.start()) + 1
                raise SkillError(
                    f"{candidate}:{line}: unresolved local Markdown link {raw_target!r}"
                )


def validate_reference_links(skill: Path) -> None:
    validate_markdown_links(skill, list(skill.rglob("*.md")))


def validate_repository_links(repo: Path) -> None:
    sources = [
        repo / source for source in LOCAL_SOURCES if source.endswith(".md")
    ]
    sources.append(repo / "skills" / "README.md")
    validate_markdown_links(repo, sources)


def validate_source_coverage(repo: Path) -> None:
    discovered: set[str] = set()
    for relative_root in _MIRRORED_ROOTS:
        root = repo / relative_root
        if not root.is_dir():
            continue
        for name in ("README.md", "AGENTS.md"):
            discovered.update(
                path.relative_to(repo).as_posix()
                for path in root.rglob(name)
                if not _IGNORED_DOCUMENT_PARTS.intersection(path.relative_to(root).parts)
            )
    missing = sorted(discovered - set(LOCAL_SOURCES))
    if missing:
        raise SkillError(
            "documentation is not bundled into the skill:\n  " + "\n  ".join(missing)
        )


def validate_text(path: str, text: str) -> None:
    match = FORBIDDEN.search(text)
    if match:
        line = text.count("\n", 0, match.start()) + 1
        raise SkillError(f"{path}:{line}: vendor-specific text is not allowed")


def validate_skill(skill: Path) -> None:
    definition = skill / "SKILL.md"
    if not definition.is_file():
        raise SkillError(f"missing {definition}")
    text = definition.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\nname: develop-eclab-lab\n" not in text:
        raise SkillError(f"{definition}: invalid skill frontmatter")
    for relative in (Path("SKILL.md"), Path("agents"), Path("references")):
        path = skill / relative
        paths = path.rglob("*") if path.is_dir() else (path,)
        for candidate in sorted(paths):
            if candidate.is_file():
                validate_text(str(candidate), candidate.read_text(encoding="utf-8"))
    source_index = skill / "references" / "source-index.md"
    if not source_index.is_file():
        raise SkillError(f"missing {source_index}")
    indexed = source_index.read_text(encoding="utf-8")
    destinations = set(LOCAL_SOURCES.values()) | set(ENGULF_SOURCES.values())
    missing_index = sorted(
        destination for destination in destinations if f"`{destination}`" not in indexed
    )
    if missing_index:
        raise SkillError(
            f"{source_index}: missing reference entries:\n  "
            + "\n  ".join(missing_index)
        )
    validate_reference_links(skill)


def synchronize(repo: Path, engulf: Path, check_only: bool, require_engulf: bool) -> None:
    validate_source_coverage(repo)
    validate_repository_links(repo)
    references = repo / SKILL_RELATIVE / "references"
    stale: list[str] = []
    mappings: list[tuple[Path, str]] = [
        (repo / source, destination) for source, destination in LOCAL_SOURCES.items()
    ]
    if engulf.is_dir():
        mappings.extend(
            (engulf / source, destination)
            for source, destination in ENGULF_SOURCES.items()
        )
    elif require_engulf:
        raise SkillError(f"Engulf source directory does not exist: {engulf}")
    else:
        print(f"note: skipping unavailable Engulf sources at {engulf}", file=sys.stderr)

    for source, destination_name in mappings:
        if not source.is_file():
            raise SkillError(f"missing reference source: {source}")
        expected = normalize_reference(
            destination_name, source.read_text(encoding="utf-8")
        )
        destination = references / destination_name
        actual = destination.read_text(encoding="utf-8") if destination.is_file() else None
        if actual == expected:
            continue
        if check_only:
            stale.append(f"{source} -> {destination}")
        else:
            destination.write_text(expected, encoding="utf-8")
            print(f"updated {destination.relative_to(repo)}")

    if stale:
        details = "\n  ".join(stale)
        raise SkillError(
            "skill references are stale:\n  "
            + details
            + "\nRun: ./scripts/update-develop-eclab-lab"
        )
    validate_skill(repo / SKILL_RELATIVE)


def staged_paths(repo: Path) -> set[str]:
    result = run_git(
        repo,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMRD",
        "-z",
    )
    return {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}


def index_text(repo: Path, path: str) -> str:
    result = run_git(repo, "show", f":{path}", check=False)
    if result.returncode:
        raise SkillError(f"staged file is unavailable: {path}")
    return result.stdout.decode("utf-8")


def validate_staged(repo: Path) -> None:
    changed = staged_paths(repo)
    for path in sorted(changed):
        candidate = Path(path)
        if (
            candidate.name in {"README.md", "AGENTS.md"}
            and candidate.parts
            and Path(candidate.parts[0]) in _MIRRORED_ROOTS
            and path not in LOCAL_SOURCES
        ):
            raise SkillError(
                f"{path} is not bundled into develop-eclab-lab; add a source mapping"
            )
    for source, destination_name in LOCAL_SOURCES.items():
        if source not in changed:
            continue
        destination = str(SKILL_RELATIVE / "references" / destination_name)
        if destination not in changed:
            raise SkillError(
                f"{source} changed without its skill reference {destination}\n"
                "Run: ./scripts/update-develop-eclab-lab"
            )
        expected = normalize_reference(destination_name, index_text(repo, source))
        if index_text(repo, destination) != expected:
            raise SkillError(
                f"staged skill reference does not match {source}: {destination}\n"
                "Run the updater and stage both files."
            )

    skill_prefix = f"{SKILL_RELATIVE}/"
    for path in sorted(item for item in changed if item.startswith(skill_prefix)):
        if run_git(repo, "cat-file", "-e", f":{path}", check=False).returncode != 0:
            continue
        validate_text(path, index_text(repo, path))


def affects_skill(path: str) -> bool:
    if path in LOCAL_SOURCES:
        return True
    if path.startswith(("skills/", "scripts/", ".githooks/")):
        return False
    if "/tests/" in path or path.startswith("tests/"):
        return False
    if path in {"README.md", "AGENTS.md"}:
        return True
    roots = ("engulf-clab/", "plugins/", "mcp-server/")
    if not path.startswith(roots):
        return False
    return path.endswith(("README.md", "AGENTS.md", "pyproject.toml")) or "/src/" in path


def validate_commit_message(repo: Path, message_path: Path) -> None:
    relevant = sorted(path for path in staged_paths(repo) if affects_skill(path))
    if not relevant:
        return
    message = message_path.read_text(encoding="utf-8")
    trailers = re.findall(
        r"^Skill-Impact:\s*(updated|none)\s*$", message, flags=re.IGNORECASE | re.MULTILINE
    )
    if len(trailers) != 1:
        raise SkillError(
            "this commit changes eclab behavior or documentation; add exactly one trailer:\n"
            "  Skill-Impact: updated\n"
            "or:\n"
            "  Skill-Impact: none"
        )
    if trailers[0].lower() == "updated":
        prefix = f"{SKILL_RELATIVE}/"
        if not any(path.startswith(prefix) for path in staged_paths(repo)):
            raise SkillError(
                "Skill-Impact: updated requires a staged change under " + str(SKILL_RELATIVE)
            )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Synchronize and validate the repository-owned develop-eclab-lab skill."
    )
    result.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: inferred from this script)",
    )
    subparsers = result.add_subparsers(dest="command", required=True)
    update = subparsers.add_parser(
        "update", help="refresh reference snapshots or check that they are current"
    )
    update.add_argument(
        "--check", action="store_true", help="report stale snapshots without rewriting them"
    )
    update.add_argument(
        "--engulf-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "ENGULF_DIR", Path(__file__).resolve().parent.parent.parent / "engulf"
            )
        ),
        help="Engulf checkout used for bundled API/runtime references",
    )
    update.add_argument(
        "--require-engulf",
        action="store_true",
        help="fail instead of skipping unavailable Engulf source references",
    )
    subparsers.add_parser("validate", help="validate source coverage and the canonical skill")
    subparsers.add_parser("staged", help="validate staged source/reference parity")
    commit_message = subparsers.add_parser(
        "commit-message", help="validate the Skill-Impact trailer for staged changes"
    )
    commit_message.add_argument("path", type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    repo = arguments.repo.resolve()
    try:
        if arguments.command == "update":
            synchronize(
                repo,
                arguments.engulf_dir.resolve(),
                arguments.check,
                arguments.require_engulf,
            )
        elif arguments.command == "validate":
            validate_source_coverage(repo)
            validate_repository_links(repo)
            validate_skill(repo / SKILL_RELATIVE)
        elif arguments.command == "staged":
            validate_staged(repo)
        else:
            validate_commit_message(repo, arguments.path)
    except (OSError, UnicodeError, SkillError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
