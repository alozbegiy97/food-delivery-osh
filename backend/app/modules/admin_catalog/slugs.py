"""Server-generated slugs from the Russian name (DEC-145).

Slugs are technical identifiers (the site uses ids in URLs): lowercase Latin
letters, digits and hyphens. Cyrillic (Russian and Kyrgyz letters) is
transliterated; a numeric suffix keeps them unique.
"""

import re
import unicodedata

SLUG_MAX_LENGTH = 100
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ң": "ng", "ө": "o", "ү": "u",
}  # fmt: skip


def slugify(text: str, max_length: int = SLUG_MAX_LENGTH) -> str:
    """'Пицца «Маргарита» 30 см' -> 'pitstsa-margarita-30-sm'."""
    lowered = "".join(_CYRILLIC.get(ch, ch) for ch in text.lower())
    ascii_only = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug[:max_length].rstrip("-") or "item"


def unique_slug(base: str, taken: set[str], max_length: int = SLUG_MAX_LENGTH) -> str:
    """`base`, or `base-2`, `base-3`, ... whichever is not in `taken`."""
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = f"{base[: max_length - len(suffix)].rstrip('-')}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1
