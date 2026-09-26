# -*- coding: utf-8 -*-
"""Quality guards for machine-generated ShopVPN translations.

Structural tokens (placeholders, URLs, markup, code) are replaced by sentinels
before translation and verified after it; obvious provider failures are rejected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TranslationContext:
    key: str
    text: str
    context: str


_PLACEHOLDER_RE = re.compile(
    r"\{\{[^{}]+\}\}|\{[^{}]+\}|%\([^)]+\)[#0+\- ]?(?:\d+)?(?:\.\d+)?[a-zA-Z]|%\d*\$?[a-zA-Z]|%s|%d"
)
_URL_RE = re.compile(r"https?://[^\s)<>]+|tg://[^\s)<>]+|mailto:[^\s)<>]+", re.I)
_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>|<!--.*?-->", re.S)
_CODE_RE = re.compile(r"`[^`\n]+`")
_MARKDOWN_LINK_URL_RE = re.compile(r"\]\(([^)]+)\)")
_PROTECT_RE = re.compile(
    "|".join(f"(?:{p.pattern})" for p in (_URL_RE, _HTML_RE, _CODE_RE, _PLACEHOLDER_RE)),
    re.S | re.I,
)
_SENTINEL_RE = re.compile(r"_{1,2}\s*SHOPVPN\s*_?\s*TOKEN\s*_?\s*(\d+)\s*_{1,2}", re.I)
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF]")
_PERSIAN_LETTERS_RE = re.compile(r"[\u067e\u0686\u0698\u06af\u06a9\u06cc]")
_LETTER_RE = re.compile(r"[^\W\d_]", re.U)
_PERSIAN_TARGETS = {"fa", "ar", "ur", "ps"}
_PROVIDER_ERROR_MARKERS = (
    "MYMEMORY WARNING",
    "YOU USED ALL AVAILABLE FREE TRANSLATIONS",
    "QUERY LENGTH LIMIT EXCEEDED",
    "PLEASE SELECT TWO DISTINCT LANGUAGES",
    "INVALID EMAIL PROVIDED",
    "NO CONTENT AVAILABLE",
)


def structural_tokens(text: str) -> list[str]:
    """Return structural tokens whose spelling must survive translation."""
    tokens: list[str] = []
    for pattern in (_PLACEHOLDER_RE, _URL_RE, _HTML_RE, _CODE_RE):
        tokens.extend(pattern.findall(text or ""))
    tokens.extend(_MARKDOWN_LINK_URL_RE.findall(text or ""))
    return tokens


def protect(text: str) -> tuple[str, dict[str, str]]:
    """Replace structural tokens with provider-safe sentinels in a single pass."""
    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}

    def sentinel_for(original: str) -> str:
        if original in reverse:
            return reverse[original]
        sentinel = f"__SHOPVPN_TOKEN_{len(mapping):03d}__"
        mapping[sentinel] = original
        reverse[original] = sentinel
        return sentinel

    def link_repl(match: re.Match) -> str:
        return "](" + sentinel_for(match.group(1)) + ")"

    out = _MARKDOWN_LINK_URL_RE.sub(link_repl, text or "")
    out = _PROTECT_RE.sub(lambda m: sentinel_for(m.group(0)), out)
    return out, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """Restore sentinels, tolerating case changes and stray spaces added by providers."""
    by_index = {int(re.search(r"(\d+)", key).group(1)): value for key, value in mapping.items()}
    return _SENTINEL_RE.sub(lambda m: by_index.get(int(m.group(1)), m.group(0)), text or "")


def validate(source: str, translated: str, target: str | None = None) -> tuple[bool, str]:
    """Validate a translation structurally and reject obvious provider failures."""
    if not source or not translated or not translated.strip():
        return False, "empty_translation"
    if _SENTINEL_RE.search(translated):
        return False, "unrestored_sentinel"
    upper = translated.upper()
    if any(marker in upper for marker in _PROVIDER_ERROR_MARKERS) and not any(m in source.upper() for m in _PROVIDER_ERROR_MARKERS):
        return False, "provider_error_payload"
    if sorted(structural_tokens(source)) != sorted(structural_tokens(translated)):
        return False, "structural_token_mismatch"
    if _EMOJI_RE.findall(source) != _EMOJI_RE.findall(translated):
        return False, "emoji_mismatch"
    if translated.strip() == source.strip() and len(_LETTER_RE.findall(source)) >= 8 and len(source.split()) >= 3:
        return False, "untranslated_copy"
    if target and target.split("-", 1)[0] not in _PERSIAN_TARGETS:
        letters = len(_LETTER_RE.findall(translated)) or 1
        if len(_PERSIAN_LETTERS_RE.findall(translated)) / letters > 0.3:
            return False, "source_language_leak"
    return True, "ok"


def validate_many(pairs: Iterable[tuple[str, str]], target: str | None = None) -> list[tuple[str, str, str]]:
    errors = []
    for source, translated in pairs:
        ok, reason = validate(source, translated, target)
        if not ok:
            errors.append((source, translated, reason))
    return errors
