"""Choice of translation (DATABASE_SCHEMA.md §2.2, API_SPECIFICATION.md §1.3).

Fallback order: the `language` parameter -> the authenticated user's
`preferred_language` -> `ru` -> the first available translation (by
language code, so the result is stable).
"""

from collections.abc import Mapping
from typing import Literal

LanguageCode = Literal["ru", "ky", "uz"]
DEFAULT_LANGUAGE = "ru"


def language_chain(requested: str | None, user_language: str | None) -> tuple[str, ...]:
    chain: list[str] = []
    for code in (requested, user_language, DEFAULT_LANGUAGE):
        if code and code not in chain:
            chain.append(code)
    return tuple(chain)


def pick[T](translations: Mapping[str, T], chain: tuple[str, ...]) -> T | None:
    for code in chain:
        if code in translations:
            return translations[code]
    for code in sorted(translations):
        return translations[code]
    return None
