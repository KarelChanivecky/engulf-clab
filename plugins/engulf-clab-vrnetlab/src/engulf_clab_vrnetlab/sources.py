from __future__ import annotations

import hashlib
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .errors import VrnetlabError


def _archive_destination(output_dir: Path, member_name: str) -> Path:
    basename = PurePosixPath(member_name).name
    if not basename:
        raise VrnetlabError(f"archive qcow2 member has no basename: {member_name}")
    return output_dir / basename


def _extract_zip(source: Path, output_dir: Path) -> Path:
    try:
        with zipfile.ZipFile(source) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".qcow2")
            ]
            if len(members) != 1:
                raise VrnetlabError(f"{source} must contain exactly one qcow2 file")
            destination = _archive_destination(output_dir, members[0].filename)
            with archive.open(members[0]) as source_file, destination.open("wb") as output:
                shutil.copyfileobj(source_file, output)
            return destination
    except zipfile.BadZipFile as error:
        raise VrnetlabError(f"invalid zip archive {source}: {error}") from error


def _extract_tar(source: Path, output_dir: Path) -> Path:
    try:
        with tarfile.open(source, "r:*") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.lower().endswith(".qcow2")
            ]
            if len(members) != 1:
                raise VrnetlabError(f"{source} must contain exactly one qcow2 file")
            destination = _archive_destination(output_dir, members[0].name)
            extracted = archive.extractfile(members[0])
            if extracted is None:
                raise VrnetlabError(f"could not extract {members[0].name} from {source}")
            with extracted, destination.open("wb") as output:
                shutil.copyfileobj(extracted, output)
            return destination
    except tarfile.TarError as error:
        raise VrnetlabError(f"invalid tar archive {source}: {error}") from error


@contextmanager
def prepared_qcow2(source: Path) -> Iterator[Path]:
    if not source.is_file():
        raise VrnetlabError(f"image source does not exist or is not a file: {source}")

    lower_name = source.name.lower()
    if lower_name.endswith(".qcow2"):
        yield source
        return

    with tempfile.TemporaryDirectory(prefix="engulf-clab-vrnetlab-source-") as directory:
        output_dir = Path(directory)
        if lower_name.endswith(".zip"):
            yield _extract_zip(source, output_dir)
            return
        if lower_name.endswith((".tar", ".tar.gz", ".tgz")):
            yield _extract_tar(source, output_dir)
            return

    raise VrnetlabError("image source must be .qcow2, .zip, .tar, .tar.gz, or .tgz")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
