"""Map free-text language names (as the LLM reports them) to ISO 639-1 codes."""

from __future__ import annotations

# Scheduled languages with speech support in at least one backend.
_NAMES = {
    "hi": ("hindi", "हिंदी", "हिन्दी", "hinglish"),
    "bn": ("bengali", "bangla", "বাংলা"),
    "ta": ("tamil", "தமிழ்"),
    "te": ("telugu", "తెలుగు"),
    "mr": ("marathi", "मराठी"),
    "gu": ("gujarati", "ગુજરાતી"),
    "kn": ("kannada", "ಕನ್ನಡ"),
    "ml": ("malayalam", "മലയാളം"),
    "pa": ("punjabi", "panjabi", "ਪੰਜਾਬੀ"),
    "or": ("odia", "oriya", "ଓଡ଼ିଆ"),
    "as": ("assamese", "অসমীয়া"),
    "ur": ("urdu", "اردو"),
    "en": ("english",),
}


def language_code(name: str | None, default: str = "hi") -> str:
    """'Hindi (Devanagari script)' -> 'hi'. Unknown or empty names give ``default``."""
    if not name:
        return default
    lowered = name.strip().lower()
    if lowered in _NAMES:
        return lowered
    for code, aliases in _NAMES.items():
        if any(alias in lowered for alias in aliases):
            return code
    return default
