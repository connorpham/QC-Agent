import hashlib
import zipfile
from pathlib import Path

from app.ingestion.intake import (
    IntakeLimits,
    StagedFile,
    expand_zip,
    extension_rejection,
    file_extension,
    sanitize_filename,
    stage_stream,
    zip_entry_rejection,
)
from tests.helpers.files import bytes_reader, make_zip

LIMITS = IntakeLimits(max_file_bytes=1024, max_batch_bytes=4096, zip_max_entries=5)


def test_sanitize_filename() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\me\\Báo cáo (final).docx") == "Báo cáo (final).docx"
    assert sanitize_filename("  weird\x00name?.pdf  ") == "weirdname_.pdf"
    assert sanitize_filename("...") == "file"
    long_name = "a" * 300 + ".docx"
    assert (
        sanitize_filename(long_name).endswith(".docx") and len(sanitize_filename(long_name)) <= 200
    )


def test_extension_rules() -> None:
    assert file_extension("Report.PDF") == "pdf"
    assert file_extension("page.htm") == "html"
    assert file_extension("noext") is None
    assert extension_rejection("virus.exe") is not None
    assert extension_rejection("ok.docx") is None


async def test_stage_stream_hashes_and_enforces_cap(tmp_path: Path) -> None:
    data = b"x" * 1000
    result = await stage_stream(bytes_reader(data), tmp_path / "in" / "a.bin", max_bytes=1024)
    assert result == (1000, hashlib.sha256(data).hexdigest())
    assert (tmp_path / "in" / "a.bin").read_bytes() == data
    too_big = await stage_stream(
        bytes_reader(b"y" * 2000), tmp_path / "in" / "b.bin", max_bytes=1024
    )
    assert too_big is None and not (tmp_path / "in" / "b.bin").exists()


def _staged(path: Path) -> StagedFile:
    data = path.read_bytes()
    return StagedFile(
        name=path.name,
        ext="zip",
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_zip_safety(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "export.zip",
        {
            "docs/Requirements.md": b"# Req",
            "../evil.md": b"x",
            "/abs.md": b"x",
            "docs/nested.zip": b"PK\x03\x04",
            "docs/script.exe": b"x",
            "__MACOSX/._Requirements.md": b"junk",
            "docs/.DS_Store": b"junk",
            "big.txt": b"z" * 2000,
        },
        symlink="docs/link.md",
    )
    limits = IntakeLimits(max_file_bytes=1024, max_batch_bytes=4096, zip_max_entries=20)
    files, rejections = expand_zip(_staged(archive), tmp_path / "out", limits)
    assert [f.name for f in files] == ["Requirements.md"]
    assert files[0].path.parent == tmp_path / "out" and files[0].path.read_bytes() == b"# Req"
    reasons = {r.name: r.reason for r in rejections}
    assert reasons["../evil.md"] == "Zip entry path is not allowed."
    assert reasons["/abs.md"] == "Zip entry path is not allowed."
    assert reasons["docs/nested.zip"] == "Nested zip archives are not extracted."
    assert reasons["docs/script.exe"].startswith("File type is not supported.")
    assert reasons["docs/link.md"] == "Symbolic links in zip archives are not allowed."
    assert reasons["big.txt"] == "File exceeds the 0 MB limit."
    assert "__MACOSX/._Requirements.md" not in reasons and "docs/.DS_Store" not in reasons


def test_encrypted_entry_rule() -> None:
    info = zipfile.ZipInfo("docs/secret.md")
    info.flag_bits |= 0x1
    rejection = zip_entry_rejection(info, LIMITS)
    assert rejection is not None and rejection.reason == "Encrypted zip entries are not supported."
    assert zip_entry_rejection(zipfile.ZipInfo("docs/fine.md"), LIMITS) is None


def test_zip_entry_count_and_batch_limits(tmp_path: Path) -> None:
    many = make_zip(tmp_path / "many.zip", {f"f{i}.md": b"x" for i in range(6)})
    files, rejections = expand_zip(_staged(many), tmp_path / "out", LIMITS)
    assert files == [] and rejections[0].reason == "Zip archive has more than 5 entries."
    batch = make_zip(tmp_path / "batch.zip", {f"f{i}.md": b"x" * 1000 for i in range(5)})
    files, rejections = expand_zip(_staged(batch), tmp_path / "out2", LIMITS)
    assert len(files) == 4 and rejections[0].reason == "Upload batch exceeds the 0 MB limit."


def test_invalid_zip(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    files, rejections = expand_zip(_staged(broken), tmp_path / "out", LIMITS)
    assert files == [] and rejections == [
        type(rejections[0])("broken.zip", "File is not a valid zip archive.")
    ]
