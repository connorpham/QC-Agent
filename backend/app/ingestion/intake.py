"""Upload validation, file-name sanitising, staging and zip safety (spec 6.3 step 1, 13).

Everything here is framework-free: the API layer passes an async ``read`` callable (an
``UploadFile.read`` fits) and receives ``StagedFile`` records that point into the staging
directory. Blocking file work runs in worker threads.
"""

import asyncio
import hashlib
import re
import stat
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import anyio

ALLOWED_EXTENSIONS = frozenset({"docx", "pdf", "xlsx", "pptx", "md", "txt", "html", "csv", "zip"})
CHUNK_SIZE = 1024 * 1024
MAX_FILENAME_LENGTH = 200
ZIP_MAX_ENTRIES = 200
_EXTENSION_ALIASES = {"htm": "html"}
_UNSAFE_CHARS = re.compile(r"[^\w .()\-]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

ReadChunk = Callable[[int], Awaitable[bytes]]


@dataclass(frozen=True)
class IntakeLimits:
    max_file_bytes: int
    max_batch_bytes: int
    zip_max_entries: int = ZIP_MAX_ENTRIES

    @classmethod
    def from_megabytes(cls, max_file_mb: int, max_batch_mb: int) -> "IntakeLimits":
        return cls(
            max_file_bytes=max_file_mb * 1024 * 1024, max_batch_bytes=max_batch_mb * 1024 * 1024
        )


@dataclass(frozen=True)
class StagedFile:
    name: str  # sanitised original file name
    ext: str
    path: Path  # absolute path inside the staging directory
    size: int
    sha256: str


@dataclass(frozen=True)
class Rejection:
    name: str
    reason: str


def file_extension(name: str) -> str | None:
    suffix = PurePosixPath(name).suffix.lower().lstrip(".")
    if not suffix:
        return None
    return _EXTENSION_ALIASES.get(suffix, suffix)


def sanitize_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable())
    base = _UNSAFE_CHARS.sub("_", base)
    base = _WHITESPACE.sub(" ", base).strip(" .")
    if not base:
        return "file"
    if len(base) > MAX_FILENAME_LENGTH:
        stem, dot, ext = base.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            base = stem[: MAX_FILENAME_LENGTH - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            base = base[:MAX_FILENAME_LENGTH].rstrip(" .")
    return base


def extension_rejection(name: str) -> Rejection | None:
    ext = file_extension(name)
    if ext is None or ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return Rejection(name, f"File type is not supported. Allowed: {allowed}.")
    return None


def size_limit_reason(limits: IntakeLimits) -> str:
    return f"File exceeds the {limits.max_file_bytes // (1024 * 1024)} MB limit."


def batch_limit_reason(limits: IntakeLimits) -> str:
    return f"Upload batch exceeds the {limits.max_batch_bytes // (1024 * 1024)} MB limit."


async def stage_stream(read: ReadChunk, dest: Path, *, max_bytes: int) -> tuple[int, str] | None:
    """Stream to ``dest`` while hashing. Returns (size, sha256) or None when the cap is exceeded
    (the partial file is removed)."""
    await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    async with await anyio.open_file(dest, "wb") as handle:
        while True:
            chunk = await read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                break
            digest.update(chunk)
            await handle.write(chunk)
    if size > max_bytes:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        return None
    return size, digest.hexdigest()


def zip_entry_rejection(info: zipfile.ZipInfo, limits: IntakeLimits) -> Rejection | None:
    raw = info.filename.replace("\\", "/")
    parts = [part for part in raw.split("/") if part]
    if not parts or raw.startswith("/") or _DRIVE_RE.match(raw) or ".." in parts:
        return Rejection(info.filename, "Zip entry path is not allowed.")
    if stat.S_ISLNK(info.external_attr >> 16):
        return Rejection(info.filename, "Symbolic links in zip archives are not allowed.")
    if info.flag_bits & 0x1:
        return Rejection(info.filename, "Encrypted zip entries are not supported.")
    ext = file_extension(parts[-1])
    if ext == "zip":
        return Rejection(info.filename, "Nested zip archives are not extracted.")
    if ext is None or ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS - {"zip"}))
        return Rejection(info.filename, f"File type is not supported. Allowed: {allowed}.")
    if info.file_size > limits.max_file_bytes:
        return Rejection(info.filename, size_limit_reason(limits))
    return None


def _is_hidden(info: zipfile.ZipInfo) -> bool:
    parts = [part for part in info.filename.replace("\\", "/").split("/") if part]
    return not parts or parts[0] == "__MACOSX" or parts[-1].startswith(".")


def _extract_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path, limits: IntakeLimits
) -> tuple[int, str] | None:
    digest = hashlib.sha256()
    size = 0
    with archive.open(info) as source, dest.open("wb") as handle:
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > limits.max_file_bytes:
                break
            digest.update(chunk)
            handle.write(chunk)
    if size > limits.max_file_bytes:
        dest.unlink(missing_ok=True)
        return None
    return size, digest.hexdigest()


def expand_zip(
    staged: StagedFile, dest_dir: Path, limits: IntakeLimits
) -> tuple[list[StagedFile], list[Rejection]]:
    """Extract the safe entries of a zip into ``dest_dir``; every unsafe entry becomes a
    rejection. Hidden entries (``__MACOSX``, dot files) are skipped silently."""
    try:
        archive = zipfile.ZipFile(staged.path)
    except zipfile.BadZipFile:
        return [], [Rejection(staged.name, "File is not a valid zip archive.")]
    with archive:
        entries = [
            info for info in archive.infolist() if not info.is_dir() and not _is_hidden(info)
        ]
        if len(entries) > limits.zip_max_entries:
            reason = f"Zip archive has more than {limits.zip_max_entries} entries."
            return [], [Rejection(staged.name, reason)]
        files: list[StagedFile] = []
        rejections: list[Rejection] = []
        total = 0
        dest_dir.mkdir(parents=True, exist_ok=True)
        for info in entries:
            rejection = zip_entry_rejection(info, limits)
            if rejection is not None:
                rejections.append(rejection)
                continue
            name = sanitize_filename(info.filename.replace("\\", "/").rsplit("/", 1)[-1])
            ext = file_extension(name)
            if ext is None:
                continue
            if total + info.file_size > limits.max_batch_bytes:
                rejections.append(Rejection(info.filename, batch_limit_reason(limits)))
                continue
            dest = dest_dir / f"{uuid.uuid4().hex}.{ext}"
            extracted = _extract_entry(archive, info, dest, limits)
            if extracted is None:
                rejections.append(Rejection(info.filename, size_limit_reason(limits)))
                continue
            size, sha256 = extracted
            total += size
            files.append(StagedFile(name=name, ext=ext, path=dest, size=size, sha256=sha256))
    return files, rejections
