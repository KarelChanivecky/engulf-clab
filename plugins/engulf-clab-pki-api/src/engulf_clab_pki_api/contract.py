from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

PKI_NODE_PROJECTIONS_CONTEXT = "engulf_clab.pki.node_projections.v2"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class AuthorityClassification(StrEnum):
    TRUST_ANCHOR = "trust_anchor"
    INTERMEDIATE = "intermediate"


def _name(value: str, label: str) -> None:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError(f"{label} must be a nonempty PKI identifier")


def _node_name(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(character in value for character in ("/", "\\", ":", ";", "\x00"))
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("node name must be a nonempty path-safe Containerlab identifier")


def _fingerprint(value: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT.fullmatch(value) is None:
        raise ValueError("fingerprint_sha256 must contain 64 lowercase hexadecimal characters")


def _tuple(values: object, expected: type[object], label: str) -> None:
    if type(values) is not tuple or any(not isinstance(item, expected) for item in values):
        raise TypeError(f"{label} must be a tuple of {expected.__name__} values")


@dataclass(frozen=True, slots=True)
class ProjectedFile:
    host_path: Path
    container_path: PurePosixPath

    def __post_init__(self) -> None:
        if not isinstance(self.host_path, Path) or not self.host_path.is_absolute():
            raise ValueError("projected host path must be an absolute Path")
        path = self.container_path
        if (
            not isinstance(path, PurePosixPath)
            or not path.is_absolute()
            or path == PurePosixPath("/")
        ):
            raise ValueError("projected container path must be an absolute non-root PurePosixPath")
        text = str(path)
        if ".." in path.parts or any(character in text for character in (":", ";", "\x00")):
            raise ValueError("projected container path is unsafe for path-list injection")
        if any(ord(character) < 32 or ord(character) == 127 for character in text):
            raise ValueError("projected container path must not contain control characters")


@dataclass(frozen=True, slots=True)
class PublicAuthorityProjection:
    scope: str
    name: str
    variant: str
    fingerprint_sha256: str
    classification: AuthorityClassification
    certificate: ProjectedFile
    chain: ProjectedFile
    full_chain: ProjectedFile

    def __post_init__(self) -> None:
        if self.scope not in {"global", "local"}:
            raise ValueError("authority scope must be 'global' or 'local'")
        _name(self.name, "authority name")
        _name(self.variant, "authority variant")
        _fingerprint(self.fingerprint_sha256)
        if not isinstance(self.classification, AuthorityClassification):
            raise TypeError("authority classification has an invalid type")
        for value in (self.certificate, self.chain, self.full_chain):
            if not isinstance(value, ProjectedFile):
                raise TypeError("authority artifact fields must be ProjectedFile values")

    @property
    def identity_id(self) -> str:
        suffix = f"/{self.variant}" if self.variant != "default" else ""
        return f"{self.scope}/{self.name}{suffix}"


@dataclass(frozen=True, slots=True)
class RequestedAuthorityProjection:
    scope: str
    name: str
    variant: str
    fingerprint_sha256: str
    certificate: ProjectedFile
    chain: ProjectedFile
    full_chain: ProjectedFile
    private_key: ProjectedFile | None = None

    def __post_init__(self) -> None:
        if self.scope not in {"global", "local"}:
            raise ValueError("authority scope must be 'global' or 'local'")
        _name(self.name, "authority name")
        _name(self.variant, "authority variant")
        _fingerprint(self.fingerprint_sha256)
        for value in (self.certificate, self.chain, self.full_chain):
            if not isinstance(value, ProjectedFile):
                raise TypeError("authority artifact fields must be ProjectedFile values")
        if self.private_key is not None and not isinstance(self.private_key, ProjectedFile):
            raise TypeError("authority private_key must be a ProjectedFile or None")

    @property
    def identity_id(self) -> str:
        suffix = f"/{self.variant}" if self.variant != "default" else ""
        return f"{self.scope}/{self.name}{suffix}"


@dataclass(frozen=True, slots=True)
class IssuedIdentityProjection:
    request_name: str
    fingerprint_sha256: str
    certificate: ProjectedFile
    private_key: ProjectedFile
    chain: ProjectedFile
    full_chain: ProjectedFile

    def __post_init__(self) -> None:
        parts = self.request_name.split("/")
        if len(parts) != 2 or parts[0] not in {"global", "local"}:
            raise ValueError("issued request name must be a canonical global/name or local/name")
        _name(parts[1], "issued request name")
        _fingerprint(self.fingerprint_sha256)
        for value in (self.certificate, self.private_key, self.chain, self.full_chain):
            if not isinstance(value, ProjectedFile):
                raise TypeError("issued artifact fields must be ProjectedFile values")

    @property
    def identity_id(self) -> str:
        return self.request_name


@dataclass(frozen=True, slots=True)
class NodePkiProjection:
    node_name: str
    node_kind: str
    staged_view: Path
    mount_target: PurePosixPath
    public_authorities: tuple[PublicAuthorityProjection, ...] = ()
    trusted_authorities: tuple[PublicAuthorityProjection, ...] = ()
    requested_authorities: tuple[RequestedAuthorityProjection, ...] = ()
    issued_identities: tuple[IssuedIdentityProjection, ...] = ()

    def __post_init__(self) -> None:
        _node_name(self.node_name)
        if not isinstance(self.node_kind, str) or not self.node_kind:
            raise ValueError("node kind must be a nonempty string")
        if not isinstance(self.staged_view, Path) or not self.staged_view.is_absolute():
            raise ValueError("staged_view must be an absolute Path")
        if (
            not isinstance(self.mount_target, PurePosixPath)
            or not self.mount_target.is_absolute()
            or self.mount_target == PurePosixPath("/")
        ):
            raise ValueError("mount_target must be an absolute non-root PurePosixPath")
        _tuple(self.public_authorities, PublicAuthorityProjection, "public_authorities")
        _tuple(self.trusted_authorities, PublicAuthorityProjection, "trusted_authorities")
        _tuple(self.requested_authorities, RequestedAuthorityProjection, "requested_authorities")
        _tuple(self.issued_identities, IssuedIdentityProjection, "issued_identities")
        for artifact in self.files():
            try:
                host_relative = artifact.host_path.relative_to(self.staged_view)
                guest_relative = artifact.container_path.relative_to(self.mount_target)
            except ValueError as error:
                raise ValueError("projected artifact escapes its node view or mount") from error
            if PurePosixPath(*host_relative.parts) != guest_relative:
                raise ValueError("projected host and container artifact paths do not correspond")

    def files(self) -> tuple[ProjectedFile, ...]:
        values: list[ProjectedFile] = []
        for public_authority in self.public_authorities:
            values.extend(
                (public_authority.certificate, public_authority.chain, public_authority.full_chain)
            )
        for trusted_authority in self.trusted_authorities:
            values.extend(
                (trusted_authority.certificate, trusted_authority.chain, trusted_authority.full_chain)
            )
        for requested_authority in self.requested_authorities:
            values.extend(
                (
                    requested_authority.certificate,
                    requested_authority.chain,
                    requested_authority.full_chain,
                )
            )
            if requested_authority.private_key is not None:
                values.append(requested_authority.private_key)
        for identity in self.issued_identities:
            values.extend(
                (identity.certificate, identity.private_key, identity.chain, identity.full_chain)
            )
        return tuple(values)


@dataclass(frozen=True, slots=True)
class PkiNodeProjections:
    nodes: tuple[NodePkiProjection, ...]

    def __post_init__(self) -> None:
        _tuple(self.nodes, NodePkiProjection, "nodes")
        names = tuple(node.node_name for node in self.nodes)
        if len(set(names)) != len(names):
            raise ValueError("node projections must have unique node names")
        if names != tuple(sorted(names)):
            raise ValueError("node projections must be sorted by node name")
