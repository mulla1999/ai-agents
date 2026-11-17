"""File locations stored relative to the app's folders, so moving or renaming the install never breaks them.

A file under ``data_dir`` is stored as ``data:masters/1/x.pdf`` and one under ``artifacts_dir`` as
``artifacts:users/1/resumes/...``; reading the column turns it back into a full path under the folders
configured now. Anything else (an older absolute path, a file outside both folders) is stored as given.
Code using these columns keeps seeing ordinary absolute path strings.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

_roots: dict[str, Path] | None = None


def configure(data_dir: Path | str, artifacts_dir: Path | str) -> None:
    """Point stored paths at this install's folders (called when the app or a migration starts)."""
    global _roots
    _roots = {"artifacts": Path(artifacts_dir).absolute(), "data": Path(data_dir).absolute()}


def _current() -> dict[str, Path]:
    if _roots is None:
        from ..config import get_settings

        settings = get_settings()
        configure(settings.data_dir, settings.artifacts_dir)
    assert _roots is not None
    return _roots


def to_stored(path: str | Path | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.is_absolute():
        return str(path)
    for name, root in _current().items():
        if p.is_relative_to(root):
            return f"{name}:{p.relative_to(root).as_posix()}"
    return str(path)


def from_stored(value: str | None) -> str | None:
    if value is None:
        return None
    name, sep, rest = value.partition(":")
    roots = _current()
    if not sep or name not in roots:
        return value  # an absolute path stored as is
    rel = PurePosixPath(rest)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"invalid stored path: {value!r}")
    return str(roots[name].joinpath(*rel.parts))


class StoredPath(TypeDecorator[str]):
    """A String column holding a file location; see the module docstring."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        return to_stored(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        return from_stored(value)
