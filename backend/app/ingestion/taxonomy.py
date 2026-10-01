"""Document taxonomy loaded from ``templates/taxonomy.yaml`` (spec 5.2).

The taxonomy is data, not code: folders, document types, which types are required,
which are normalised and where ``multi`` types live. Every folder implicitly accepts an
``other`` type whose key is ``<folder-id>/other``.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

OTHER = "other"
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DIR_RE = re.compile(r"^[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*$")
_FOLDER_KEYS = {"id", "dir", "stage", "doc_types"}
_DOC_TYPE_KEYS = {"id", "title", "required", "template", "normalize", "multi", "subdir"}


class TaxonomyError(ValueError):
    """The taxonomy file is missing, malformed or inconsistent."""


class UnknownDocType(KeyError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass(frozen=True)
class DocType:
    id: str
    key: str
    title: str
    folder_id: str
    folder_dir: str
    required: bool = False
    template: str | None = None
    normalize: bool = True
    multi: bool = False
    subdir: str | None = None

    @property
    def is_other(self) -> bool:
        return self.id == OTHER

    @property
    def document_dir(self) -> str:
        """Storage folder (relative to the project root) that holds this type's files."""
        if self.multi and self.subdir:
            return f"{self.folder_dir}/{self.subdir}"
        return self.folder_dir


@dataclass(frozen=True)
class Folder:
    id: str
    dir: str
    stage: str
    doc_types: tuple[DocType, ...]


@dataclass(frozen=True)
class Taxonomy:
    version: int
    folders: tuple[Folder, ...]
    templates_dir: Path

    @property
    def doc_types(self) -> list[DocType]:
        return [doc_type for folder in self.folders for doc_type in folder.doc_types]

    def resolve(self, key: str) -> DocType:
        for doc_type in self.doc_types:
            if doc_type.key == key:
                return doc_type
        raise UnknownDocType(key)

    def folder(self, folder_id: str) -> Folder:
        for folder in self.folders:
            if folder.id == folder_id:
                return folder
        raise TaxonomyError(f"Unknown folder {folder_id!r}.")

    def required_types(self) -> list[DocType]:
        return [doc_type for doc_type in self.doc_types if doc_type.required]

    def template_text(self, doc_type: DocType) -> str:
        if doc_type.template is None:
            raise TaxonomyError(f"Document type {doc_type.key!r} has no template.")
        return (self.templates_dir / "doc-templates" / doc_type.template).read_text(
            encoding="utf-8"
        )


def default_templates_dir() -> Path:
    """``<repository root>/templates`` (this file lives in ``backend/app/ingestion/``)."""
    return Path(__file__).resolve().parents[3] / "templates"


def _require_str(mapping: Mapping[str, Any], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaxonomyError(f"{where}: {key!r} must be a non-empty string.")
    return value


def _optional_bool(mapping: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise TaxonomyError(f"{where}: {key!r} must be true or false.")
    return value


def _parse_doc_type(raw: Any, folder_id: str, folder_dir: str, templates_dir: Path) -> DocType:
    where = f"folder {folder_id!r}"
    if not isinstance(raw, Mapping):
        raise TaxonomyError(f"{where}: each doc_type must be a mapping.")
    unknown = set(raw) - _DOC_TYPE_KEYS
    if unknown:
        raise TaxonomyError(f"{where}: unknown doc_type keys {sorted(unknown)}.")
    doc_id = _require_str(raw, "id", where)
    where = f"doc type {doc_id!r}"
    if not _ID_RE.fullmatch(doc_id) or doc_id == OTHER:
        raise TaxonomyError(f"{where}: id must be lowercase letters, digits and hyphens.")
    template = _require_str(raw, "template", where)
    if not template.endswith(".md") or "/" in template:
        raise TaxonomyError(f"{where}: template must be a .md file name.")
    if not (templates_dir / "doc-templates" / template).is_file():
        raise TaxonomyError(f"{where}: template file {template!r} does not exist.")
    multi = _optional_bool(raw, "multi", False, where)
    subdir = raw.get("subdir")
    if multi:
        if not isinstance(subdir, str) or not _ID_RE.fullmatch(subdir):
            raise TaxonomyError(f"{where}: multi types need a 'subdir' (lowercase, hyphens).")
    elif subdir is not None:
        raise TaxonomyError(f"{where}: 'subdir' is only allowed with multi: true.")
    return DocType(
        id=doc_id,
        key=doc_id,
        title=_require_str(raw, "title", where),
        folder_id=folder_id,
        folder_dir=folder_dir,
        required=_optional_bool(raw, "required", False, where),
        template=template,
        normalize=_optional_bool(raw, "normalize", True, where),
        multi=multi,
        subdir=subdir if multi else None,
    )


def _other_type(folder_id: str, folder_dir: str) -> DocType:
    return DocType(
        id=OTHER,
        key=f"{folder_id}/{OTHER}",
        title="Other",
        folder_id=folder_id,
        folder_dir=folder_dir,
        required=False,
        template=None,
        normalize=False,
    )


def _parse_folder(raw: Any, templates_dir: Path) -> Folder:
    if not isinstance(raw, Mapping):
        raise TaxonomyError("each folder must be a mapping.")
    unknown = set(raw) - _FOLDER_KEYS
    if unknown:
        raise TaxonomyError(f"folder: unknown keys {sorted(unknown)}.")
    folder_id = _require_str(raw, "id", "folder")
    where = f"folder {folder_id!r}"
    if not _ID_RE.fullmatch(folder_id):
        raise TaxonomyError(f"{where}: id must be lowercase letters, digits and hyphens.")
    folder_dir = _require_str(raw, "dir", where)
    if not _DIR_RE.fullmatch(folder_dir):
        raise TaxonomyError(f"{where}: dir must look like '02-requirements'.")
    stage = _require_str(raw, "stage", where)
    raw_types = raw.get("doc_types")
    if not isinstance(raw_types, list) or not raw_types:
        raise TaxonomyError(f"{where}: doc_types must be a non-empty list.")
    doc_types = [_parse_doc_type(t, folder_id, folder_dir, templates_dir) for t in raw_types]
    doc_types.append(_other_type(folder_id, folder_dir))
    return Folder(id=folder_id, dir=folder_dir, stage=stage, doc_types=tuple(doc_types))


def parse_taxonomy(data: Any, templates_dir: Path) -> Taxonomy:
    if not isinstance(data, Mapping):
        raise TaxonomyError("taxonomy.yaml must be a mapping with 'version' and 'folders'.")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TaxonomyError("'version' must be a positive integer.")
    raw_folders = data.get("folders")
    if not isinstance(raw_folders, list) or not raw_folders:
        raise TaxonomyError("'folders' must be a non-empty list.")
    folders = tuple(_parse_folder(f, templates_dir) for f in raw_folders)
    seen_ids: set[str] = set()
    seen_dirs: set[str] = set()
    seen_types: set[str] = set()
    for folder in folders:
        if folder.id in seen_ids or folder.dir in seen_dirs:
            raise TaxonomyError(f"folder {folder.id!r}: duplicate id or dir.")
        seen_ids.add(folder.id)
        seen_dirs.add(folder.dir)
        for doc_type in folder.doc_types:
            if doc_type.is_other:
                continue
            if doc_type.id in seen_types:
                raise TaxonomyError(f"doc type {doc_type.id!r} is defined twice.")
            seen_types.add(doc_type.id)
    return Taxonomy(version=version, folders=folders, templates_dir=templates_dir)


def load_taxonomy(templates_dir: Path | None = None) -> Taxonomy:
    root = templates_dir or default_templates_dir()
    path = root / "taxonomy.yaml"
    if not path.is_file():
        raise TaxonomyError(f"Taxonomy file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaxonomyError(f"Taxonomy file is not valid YAML: {exc}") from exc
    return parse_taxonomy(data, root)
