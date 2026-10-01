import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 80) -> str:
    replaced = text.replace("đ", "d").replace("Đ", "D")
    ascii_text = unicodedata.normalize("NFKD", replaced).encode("ascii", "ignore").decode()
    slug = _NON_ALNUM.sub("-", ascii_text.lower()).strip("-")
    slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def unique_slug(base: str, taken: set[str], max_len: int = 80) -> str:
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_len - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
        n += 1
