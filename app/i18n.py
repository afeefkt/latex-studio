# ── Phase 1: Language registry ──
#
# Frozen registry of supported output languages.  Served from /api/i18n/languages
# so the frontend's language dropdown is always data-driven — same argument as the
# template picker.
#
# Latin script only this phase.  Clear Sans and Latin Modern have no CJK/Arabic/
# Cyrillic glyphs, so selecting a non-Latin language would compile to tofu.

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str          # ISO 639-1
    english_name: str
    native_name: str
    babel: str         # babel package option (e.g. "ngerman")
    script: str        # "latin" | "cjk" | "arabic" | "cyrillic"


SUPPORTED: list[Language] = [
    Language("en", "English",           "English",      "english",  "latin"),
    Language("de", "German",            "Deutsch",      "ngerman",  "latin"),
    Language("fr", "French",            "Français",     "french",   "latin"),
    Language("es", "Spanish",           "Español",      "spanish",  "latin"),
    Language("it", "Italian",           "Italiano",     "italian",  "latin"),
    Language("pt", "Portuguese",        "Português",    "portuguese", "latin"),
    Language("nl", "Dutch",             "Nederlands",   "dutch",    "latin"),
    Language("sv", "Swedish",           "Svenska",      "swedish",  "latin"),
    Language("no", "Norwegian",         "Norsk",        "norsk",    "latin"),
    Language("da", "Danish",            "Dansk",        "danish",   "latin"),
]

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in SUPPORTED}


def get_language(code: str) -> Language | None:
    return _BY_CODE.get(code)


def to_dict(lang: Language) -> dict:
    return {
        "code": lang.code,
        "english_name": lang.english_name,
        "native_name": lang.native_name,
        "script": lang.script,
    }
