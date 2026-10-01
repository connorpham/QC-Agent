from app.core.slugs import slugify, unique_slug


def test_vietnamese_is_transliterated() -> None:
    assert slugify("Dự án Cổng Khách hàng") == "du-an-cong-khach-hang"
    assert slugify("Quản lý Đơn hàng") == "quan-ly-don-hang"


def test_symbols_collapse_and_trim() -> None:
    assert slugify("  SRS v2.1 (final)!! ") == "srs-v2-1-final"


def test_empty_becomes_untitled() -> None:
    assert slugify("!!!") == "untitled"


def test_max_length_does_not_end_with_hyphen() -> None:
    slug = slugify("a" * 79 + " b", max_len=80)
    assert len(slug) <= 80
    assert not slug.endswith("-")


def test_unique_slug_adds_suffix() -> None:
    assert unique_slug("demo", set()) == "demo"
    assert unique_slug("demo", {"demo"}) == "demo-2"
    assert unique_slug("demo", {"demo", "demo-2"}) == "demo-3"


def test_unique_slug_respects_max_length() -> None:
    base = "x" * 80
    result = unique_slug(base, {base})
    assert result.endswith("-2")
    assert len(result) == 80
