"""Allowlists for translation-quality heuristics (identical-to-default / identical across locales).

Three layers:

1. :data:`GLOBALLY_SHARED_IDENTICAL_VALUES` — same spelling OK in every locale (units, brands).
2. :data:`EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE` — English default + expected loanwords per target language.
3. :data:`CROSS_LANGUAGE_SHARED_IDENTICAL_VALUES` — non-default locales that may share the same
   translation without implying a copy error (independent of English).
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Sequence

# Values that may stay identical to the default (or across locales) in any language.
GLOBALLY_SHARED_IDENTICAL_VALUES: frozenset[str] = frozenset(
    {
        "celsius",
        "fahrenheit",
        "kelvin",
    }
)

# When default locale is English: loanwords / cognates per target language that may match en.
EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE: Dict[str, frozenset[str]] = {
    "de": frozenset(
        {
            "AM/PM",
            "api",
            "April",
            "August",
            "email",
            "e-mail",
            "emoji",
            "global",
            "id",
            "json",
            "info",
            "minute",
            "name",
            "navigation",
            "November",
            "plan",
            "September",
            "signal",
            "status",
            "url",
            "version",
            "xml",
        }
    ),
    "fr": frozenset(
        {
            "absent",
            "action",
            "actions",
            "alliance",
            "alliances",
            "api",
            "avatar",
            "cuisine",
            "date",
            "description",
            "descriptions",
            "document",
            "documentation",
            "documents",
            "e-mail",
            "email",
            "emoji",
            "etc",
            "exclusion",
            "exclusions",
            "format",
            "id",
            "info",
            "json",
            "locale",
            "locales",
            "menu",
            "messages",
            "messsage",
            "minute",
            "minutes",
            "navigation",
            "note",
            "notes",
            "notification",
            "notifications",
            "page",
            "pages",
            "participant",
            "participants",
            "plan",
            "restaurant",
            "restaurants",
            "service",
            "services",
            "signal",
            "status",
            "terrible",
            "total",
            "type",
            "url",
            "version",
            "vote",
            "votes",
            "xml",
        }
    ),
    "es": frozenset(
        {
            "api",
            "email",
            "e-mail",
            "emoji",
            "error",
            "etc",
            "general",
            "global",
            "id",
            "info",
            "json",
            "locales",
            "no",
            "personal",
            "terrible",
            "total",
            "url",
            "xml",
        }
    ),
    "it": frozenset(
        {
            "AM/PM",
            "api",
            "email",
            "e-mail",
            "emoji",
            "id",
            "info",
            "json",
            "no",
            "password",
            "status",
            "url",
            "xml",
        }
    ),
    "pt": frozenset(
        {
            "AM/PM",
            "api",
            "email",
            "e-mail",
            "emoji",
            "id",
            "info",
            "json",
            "no",
        }
    ),
}

# Base-language groups → normalized values that may be identical across those locales
# (even when they differ from the English default). Extend with real project findings.
CROSS_LANGUAGE_SHARED_IDENTICAL_VALUES: Dict[FrozenSet[str], frozenset[str]] = {
    frozenset({"de", "fr"}): frozenset(
        {
            "minute",
            "name",
            "navigation",
            "note",
            "profil",
            "restaurant",
            "service",
        }
    ),
    frozenset({"es", "fr"}): frozenset(
        {
            "bien",
            "error",
            "general",
            "global",
            "no",
            "personal",
            "terrible",
            "total",
        }
    ),
    frozenset({"es", "it"}): frozenset(
        {
            "compartir",
            "no",
            "personal",
            "terrible",
        }
    ),
    frozenset({"es", "fr", "it"}): frozenset(
        {
            "no",
            "personal",
            "terrible",
            "total",
        }
    ),
    frozenset({"es", "fr", "it", "pt"}): frozenset(
        {
            "no",
            "personal",
        }
    ),
}


def base_language(locale: str) -> str:
    if not locale:
        return ""
    return locale.replace("-", "_").split("_", 1)[0].strip().lower()


def is_globally_shared_identical_value(text: str) -> bool:
    return (text or "").strip().lower() in GLOBALLY_SHARED_IDENTICAL_VALUES


def is_allowed_cross_locale_identical_cluster(
    locales: Sequence[str], text: str
) -> bool:
    """True when ``text`` may legitimately be the same across all ``locales`` in the cluster."""
    if len(locales) < 2:
        return False
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    langs = frozenset(base_language(loc) for loc in locales if loc)
    if len(langs) < 2:
        return False
    for group_langs, allowed_values in CROSS_LANGUAGE_SHARED_IDENTICAL_VALUES.items():
        if langs <= group_langs and normalized in allowed_values:
            return True
    return False
