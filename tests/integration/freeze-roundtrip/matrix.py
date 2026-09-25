"""Deterministic coverage of all feasible pairs; no host access at import time."""

from dataclasses import asdict, dataclass
from itertools import combinations, product

DIMENSIONS = {
    "runtime": ("prepare", "deferred"),
    "environment": ("env", "export", "initialize"),
    "pki": (
        "workspace-regenerate",
        "workspace-export",
        "user-auto",
        "user-explicit",
        "user-export",
    ),
    "destination": ("fresh", "force"),
}
IMAGES = {
    "lean": ("default", "external"),
    "runtime": ("default", "external"),
    "offline": (
        "default-deferred",
        "default-load",
        "default-explicit",
        "bundle-deferred",
        "bundle-load",
        "bundle-explicit",
    ),
}
FAILURES = (
    "removed-lean",
    "mode-conflict",
    "image-conflict",
    "missing-image",
    "bad-passphrase",
    "missing-binding",
    "bad-binding",
)


@dataclass(frozen=True)
class Case:
    id: str
    mode: str
    runtime: str = "prepare"
    environment: str = "env"
    pki: str = "workspace-regenerate"
    destination: str = "fresh"
    image: str = "default"
    focus: str = ""

    def row(self):
        return tuple(getattr(self, name) for name in (*DIMENSIONS, "image"))

    def public(self):
        return asdict(self)

    @property
    def scope(self):
        return "user" if self.pki.startswith("user") else "workspace"

    @property
    def encrypted(self):
        return self.pki.endswith("export")

    @property
    def archive_key(self):
        # Recipient runtime, env, binding and destination do not affect freeze.
        image = self.image.split("-", 1)[0]
        return f"{self.mode}-{self.scope}-{'export' if self.encrypted else 'public'}-{image}"


def pairs(row):
    return frozenset(
        (a, row[a], b, row[b]) for a, b in combinations(range(len(row)), 2)
    )


def feasible_rows(mode):
    # Runtime preparation is also intentionally varied in lean mode (a no-op).
    # Capture and load choices are combined: external+offline is infeasible and
    # belongs in focused failures, while all six offline combinations are valid.
    return tuple(product(*DIMENSIONS.values(), IMAGES[mode]))


def matrix(mode):
    candidates = feasible_rows(mode)
    uncovered = set().union(*(pairs(row) for row in candidates))
    selected = []
    scored = [(row, pairs(row)) for row in candidates]
    while uncovered:
        row, covered = max(scored, key=lambda item: len(item[1] & uncovered))
        selected.append(row)
        uncovered.difference_update(covered)
        scored = [(r, p) for r, p in scored if r != row]
    return [
        Case(f"{mode}-{index:03d}", mode, **dict(zip((*DIMENSIONS, "image"), row)))
        for index, row in enumerate(selected, 1)
    ]


def cases(mode):
    image = IMAGES[mode][0]
    result = matrix(mode)
    result += [
        Case(f"{mode}-{name}", mode, image=image, focus=name)
        for name in ("defaults", "unrelated-cwd", *FAILURES)
    ]
    if mode == "lean":
        result.append(Case("lean-warnings", mode, focus="warnings"))
    if mode == "runtime":
        result.append(Case("runtime-tool-mismatch", mode, focus="tool-mismatch"))
    if mode == "offline":
        result.append(Case("offline-incomplete", mode, image=image, focus="incomplete"))
    return result


def coverage(mode, selected):
    required = set().union(*(pairs(row) for row in feasible_rows(mode)))
    covered = set().union(*(pairs(case.row()) for case in selected if not case.focus))
    names = (*DIMENSIONS, "image")

    def describe(pair):
        a, av, b, bv = pair
        return [names[a], av, names[b], bv]

    return {
        "required": len(required),
        "covered": len(required & covered),
        "missing": [describe(p) for p in sorted(required - covered)],
        "pairs": [describe(p) for p in sorted(required & covered)],
    }
