# -*- coding: utf-8 -*-
"""Automatic translation engine and language registry helpers.

Translations are generated from the existing English UI source of truth. The
engine is deliberately isolated so the rest of ShopVPN does not depend on a
specific online translation vendor.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import json as _json
import threading
from collections import defaultdict, deque
from functools import lru_cache
from typing import Dict, Iterable, List

from translation_quality import protect, restore, validate

from i18n import LANGUAGE_CATALOG, PARTIAL_MAX_RATIO

BATCH_SIZE = 40
_SHARED_CACHE: Dict[tuple, str] = {}
_SYNC_LOCKS: Dict[tuple, threading.Lock] = {}
_SYNC_LOCKS_GUARD = threading.Lock()
# deep-translator's GoogleTranslator accepts bare ISO codes; MyMemory's free API
# only recognizes locale-qualified codes for most non-English targets.
_MYMEMORY_LANG = {
    "tr": "tr-TR", "ar": "ar-SA", "ru": "ru-RU", "de": "de-DE", "fr": "fr-FR",
    "es": "es-ES", "it": "it-IT", "pt": "pt-PT", "zh": "zh-CN", "ja": "ja-JP",
    "ko": "ko-KR", "nl": "nl-NL", "pl": "pl-PL", "uk": "uk-UA",
}
GLOSSARY = (
    "ShopVPN, VPN, Telegram, Mini App, Stars, USDT stay untranslated. "
    "'Toman' stays 'Toman'. 'Config' means a VPN configuration. "
    "'Reseller' means a partner who resells VPN services. 'Subscription link' means a VPN subscription URL. "
    "'Inbound' and 'Xray' are technical terms and stay untranslated."
)

log = logging.getLogger(__name__)


def _dynamic_sources() -> Dict[str, str]:
    import i18n
    return {fa: i18n.numbered_template(en) for fa, en in i18n._DYNAMIC_PHRASES}


@lru_cache(maxsize=1)
def _source_catalog_cached() -> Dict[str, str]:
    import i18n
    out: Dict[str, str] = {}
    out.update({str(k): str(v) for k, v in i18n._TRANSLATIONS.get("en", {}).items()})
    out.update({str(k): str(v) for k, v in i18n._PHRASE_TRANSLATIONS.items()})
    out.update({str(k): str(v) for k, v in i18n._FRAGMENT_TRANSLATIONS.items()})
    out.update({fa: en for fa, en in _dynamic_sources().items()})
    # The word catalog is useful for short labels that appear independently in
    # the web UI. Exact phrases above always win over these entries.
    out.update({str(k): str(v) for k, v in i18n._WORD_TRANSLATIONS.items()})
    return {k: v for k, v in out.items() if v and v.strip()}


def source_catalog() -> Dict[str, str]:
    return dict(_source_catalog_cached())


@lru_cache(maxsize=1)
def _source_values() -> frozenset:
    return frozenset(_source_catalog_cached().values())


def split_translatable(texts: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split texts into catalog-owned strings and everything else, which must stay verbatim."""
    allowed, verbatim = [], []
    values = _source_values()
    for text in texts:
        text = str(text)
        (allowed if text in values else verbatim).append(text)
    return allowed, verbatim


class RateLimiter:
    """Small in-memory sliding-window limiter."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._hits: Dict[object, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


runtime_limiter = RateLimiter(limit=20, window=60.0)


@lru_cache(maxsize=1)
def _contexts_cached() -> Dict[str, list[dict]]:
    return source_catalog_contexts()


def source_catalog_contexts() -> Dict[str, list[dict]]:
    """Return stable context metadata for each source string.

    The existing English catalog remains the source of truth; this metadata is
    additive and never changes Persian or English UI text.
    """
    import i18n
    buckets: Dict[str, list[dict]] = {}
    catalogs = [
        ("ui", i18n._TRANSLATIONS.get("en", {})),
        ("phrase", i18n._PHRASE_TRANSLATIONS),
        ("fragment", i18n._FRAGMENT_TRANSLATIONS),
        ("word", i18n._WORD_TRANSLATIONS),
        ("dynamic", _dynamic_sources()),
    ]
    for kind, mapping in catalogs:
        for key, value in mapping.items():
            value = str(value).strip()
            if not value:
                continue
            buckets.setdefault(value, []).append({
                "key": str(key),
                "kind": kind,
                "context": _context_for_key(str(key), kind),
            })
    return buckets


def _context_for_key(key: str, kind: str) -> str:
    key_l = key.lower()
    if any(x in key_l for x in ("error", "failed", "failure", "خطا", "ناموفق")):
        return "System error or failure message shown to the user."
    if any(x in key_l for x in ("button", "menu", "select", "choose", "انتخاب", "دکمه", "منو")):
        return "Short user-interface label, button or menu action."
    if any(x in key_l for x in ("notification", "notify", "alert", "اعلان", "هشدار")):
        return "User notification or alert."
    if any(x in key_l for x in ("payment", "invoice", "پرداخت", "فاکتور")):
        return "Payment or invoice UI message."
    if any(x in key_l for x in ("product", "service", "محصول", "سرویس")):
        return "Product or service related UI text."
    if any(x in key_l for x in ("admin", "reseller", "مدیریت", "نمایندگی")):
        return "Administrative or reseller interface text."
    return f"ShopVPN {kind} UI text."


def context_for_text(text: str) -> list[dict]:
    return _contexts_cached().get(str(text), [])


class TranslationProviderError(RuntimeError):
    """Provider failed; the caller may safely try the next provider."""


class _Provider:
    name = "unknown"

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        raise NotImplementedError


class _DeepTranslatorProvider(_Provider):
    """Wraps a deep-translator provider with per-item pacing and retry.

    The free unofficial APIs behind these providers (Google's web endpoint,
    MyMemory) enforce tight per-second rate limits (Google: ~5 req/s). Calling
    the library's own translate_batch fires requests back-to-back with no
    delay and trips that limit almost immediately once the catalog has more
    than a handful of missing strings, so translation is done one item at a
    time with throttling and a short backoff-retry on rate-limit errors.
    """

    def __init__(self, provider_cls, name: str, lang_map: Dict[str, str] | None = None,
                 min_interval: float = 0.0, max_retries: int = 2):
        self.provider_cls = provider_cls
        self.name = name
        self.lang_map = lang_map or {}
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_call = 0.0
        self._pace_lock = threading.Lock()

    def _throttle(self):
        if self.min_interval <= 0:
            return
        with self._pace_lock:
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        target_code = self.lang_map.get(target, target)
        try:
            translator = self.provider_cls(source="en", target=target_code)
        except Exception as exc:
            raise TranslationProviderError(f"{self.name}: {exc}") from exc
        out: list[str] = []
        for text in texts:
            last_exc: Exception | None = None
            for attempt in range(self.max_retries + 1):
                self._throttle()
                try:
                    out.append(translator.translate(text))
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc).lower()
                    if attempt < self.max_retries and ("too many requests" in msg or "429" in msg):
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    break
            if last_exc is not None:
                raise TranslationProviderError(f"{self.name}: {last_exc}") from last_exc
        return out


class _LibreTranslateProvider(_Provider):
    name = "libretranslate"

    def __init__(self, endpoint: str, api_key: str | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        out = []
        for text in texts:
            payload = {"q": text, "source": "en", "target": target, "format": "text"}
            if self.api_key:
                payload["api_key"] = self.api_key
            req = urllib.request.Request(
                self.endpoint + "/translate",
                data=urllib.parse.urlencode(payload).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ShopVPN/1.0"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    data = _json.loads(response.read().decode("utf-8"))
                value = data.get("translatedText") if isinstance(data, dict) else None
                if not value:
                    raise RuntimeError("empty translatedText")
                out.append(str(value))
            except Exception as exc:
                raise TranslationProviderError(f"{self.name}: {exc}") from exc
        return out


class _GeminiProvider(_Provider):
    name = "gemini"

    def __init__(self, keys: list[str], model: str, client_factory=None):
        self.keys = keys
        self.model = model
        self.client_factory = client_factory

    def _client(self, key: str):
        if self.client_factory:
            return self.client_factory(key)
        from google import genai
        return genai.Client(api_key=key)

    def _config(self, target: str):
        from google.genai import types
        name = LANGUAGE_CATALOG.get(target, {}).get("name", target)
        instruction = (
            f"You translate UI strings of a VPN sales Telegram bot from English to {name}. "
            "Input is a JSON list of {id, text, context}. Return only a JSON list of {id, text} with the translation of each item. "
            "Keep tokens like __SHOPVPN_TOKEN_000__, emoji, line breaks and leading/trailing punctuation exactly as in the source. "
            "Use short natural wording for buttons. " + GLOSSARY
        )
        return types.GenerateContentConfig(system_instruction=instruction, response_mime_type="application/json")

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        contexts = contexts or {}
        payload = json.dumps(
            [{"id": i, "text": t, "context": contexts.get(t, "")} for i, t in enumerate(texts)],
            ensure_ascii=False,
        )
        last: Exception | None = None
        for key in self.keys:
            try:
                response = self._client(key).models.generate_content(
                    model=self.model, contents=payload, config=self._config(target)
                )
                data = json.loads(response.text)
                by_id = {int(item["id"]): str(item["text"]) for item in data}
                return [by_id.get(i, "") for i in range(len(texts))]
            except Exception as exc:
                last = exc
        raise TranslationProviderError(f"gemini: {last}")


def _provider_order() -> list[str]:
    raw = os.getenv("SHOPVPN_TRANSLATION_PROVIDERS", "gemini,google,mymemory,libretranslate")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _split_keys(raw: str) -> list[str]:
    return [k.strip() for k in (raw or "").replace("\n", ",").split(",") if k.strip()]


def _db_setting(db, key: str) -> str:
    """Best-effort read of a global setting; never fails a translation run."""
    if db is None:
        return ""
    try:
        return db.get_setting(key, "") or ""
    except Exception:
        return ""


def _gemini_keys(db=None) -> list[str]:
    """Admin-panel key (stored in the main bot's database) wins; env vars are the fallback."""
    from_db = _split_keys(_db_setting(db, "translation_gemini_api_key"))
    if from_db:
        return from_db
    raw = os.getenv("SHOPVPN_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    return _split_keys(raw)


def gemini_key_source(db=None) -> str:
    """Where the Gemini key used for translation currently comes from, for admin UIs."""
    if _split_keys(_db_setting(db, "translation_gemini_api_key")):
        return "panel"
    if os.getenv("SHOPVPN_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY"):
        return "env"
    return "none"


def _providers(target: str, db=None) -> list[_Provider]:
    providers: list[_Provider] = []
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except Exception:
        GoogleTranslator = MyMemoryTranslator = None
    for name in _provider_order():
        if name == "gemini":
            keys = _gemini_keys(db)
            if keys:
                providers.append(_GeminiProvider(keys, os.getenv("SHOPVPN_TRANSLATION_MODEL", "gemini-2.5-flash")))
        elif name == "google" and GoogleTranslator:
            # Google's free web endpoint allows ~5 req/s; stay safely under that.
            providers.append(_DeepTranslatorProvider(GoogleTranslator, "google", min_interval=0.3))
        elif name in {"mymemory", "my-memory"} and MyMemoryTranslator:
            providers.append(_DeepTranslatorProvider(
                MyMemoryTranslator, "mymemory", lang_map=_MYMEMORY_LANG, min_interval=1.0,
            ))
        elif name == "libretranslate":
            endpoint = os.getenv("SHOPVPN_LIBRETRANSLATE_URL", "").strip()
            if endpoint:
                providers.append(_LibreTranslateProvider(endpoint, os.getenv("SHOPVPN_LIBRETRANSLATE_API_KEY")))
    return providers


def provider_status(db=None) -> list[dict]:
    """Describe configured providers without making network calls."""
    return [{"name": p.name, "configured": True} for p in _providers("tr", db)]


def _normalize_target(target: str) -> str:
    return (target or "").lower().split("-", 1)[0]


def translate_many_partial(texts: Iterable[str], target: str, *, cached: Dict[str, str] | None = None, db=None) -> tuple[Dict[str, str], list[str]]:
    """Translate as many strings as possible; return (translations, failure messages)."""
    target = _normalize_target(target)
    if target in {"fa", "en"}:
        return {str(x): str(x) for x in texts}, []
    if target not in LANGUAGE_CATALOG:
        raise ValueError(f"Unsupported language: {target}")
    values = list(dict.fromkeys(str(x) for x in texts if str(x).strip()))
    result: Dict[str, str] = {}
    cached = cached or {}
    for value in values:
        for candidate in (cached.get(value), _SHARED_CACHE.get((target, value))):
            if candidate and str(candidate).strip() and validate(value, str(candidate), target)[0]:
                result[value] = str(candidate)
                break
    remaining = [x for x in values if x not in result]
    if not remaining:
        return result, []
    providers = _providers(target, db)
    if not providers:
        raise RuntimeError("No translation provider is configured. Install deep-translator, set GEMINI_API_KEY or configure LibreTranslate.")
    failures: list[str] = []
    for provider in providers:
        if not remaining:
            break
        protected = {value: protect(value) for value in remaining}
        contexts = {}
        for value in remaining:
            found = context_for_text(value)
            if found:
                contexts[protected[value][0]] = found[0]["context"]
        still: list[str] = []
        provider_failed = False
        for i in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[i:i + BATCH_SIZE]
            if provider_failed:
                still.extend(batch)
                continue
            try:
                translated = provider.translate_batch([protected[v][0] for v in batch], target, contexts)
                if not translated or len(translated) != len(batch):
                    raise TranslationProviderError(f"{provider.name}: incomplete batch")
            except Exception as exc:
                failures.append(str(exc))
                log.warning("Translation provider %s failed for %s: %s", provider.name, target, exc)
                provider_failed = True
                still.extend(batch)
                continue
            for src, dst in zip(batch, translated):
                restored = restore(str(dst or ""), protected[src][1])
                ok, reason = validate(src, restored, target)
                if ok:
                    result[src] = restored
                    _SHARED_CACHE[(target, src)] = restored
                else:
                    failures.append(f"{provider.name}: rejected {src!r}: {reason}")
                    still.append(src)
        remaining = still
    return result, failures


def translate_many(texts: Iterable[str], target: str, *, cached: Dict[str, str] | None = None, db=None) -> Dict[str, str]:
    """Translate every string or raise; use translate_many_partial to keep partial progress."""
    texts = [str(x) for x in texts]
    result, failures = translate_many_partial(texts, target, cached=cached, db=db)
    values = list(dict.fromkeys(x for x in texts if x.strip()))
    missing = [x for x in values if x not in result]
    if missing and _normalize_target(target) not in {"fa", "en"}:
        raise RuntimeError("All translation providers failed; missing %d item(s): %s" % (len(missing), "; ".join(failures[-3:])))
    return result


def catalog_version(source: Dict[str, str] | None = None) -> str:
    """Return a stable fingerprint of the current English source catalog."""
    source = source if source is not None else source_catalog()
    payload = json.dumps(sorted(source.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _missing_ratio(info: dict) -> float:
    return info["missing_count"] / info["source_count"] if info.get("source_count") else 1.0


def inspect_language(db, language: str) -> dict:
    language = _normalize_target(language)
    source = source_catalog()
    version = catalog_version(source)
    catalog = db.translation_catalog(language) if language not in {"fa", "en"} else {}
    source_values = set(source.values())
    translated_values = set(catalog.keys())
    missing = sorted(source_values - translated_values)
    obsolete = sorted(translated_values - source_values)
    status = "current" if not missing else "pending"
    if language in {"fa", "en"}:
        status = "builtin"
        missing = []
        obsolete = []
    return {
        "language": language, "catalog_version": version,
        "source_count": len(source_values), "translated_count": len(source_values & translated_values),
        "missing_count": len(missing), "obsolete_count": len(obsolete),
        "missing": missing, "obsolete": obsolete, "status": status,
    }


def _sync_lock(db, language: str) -> threading.Lock:
    key = (getattr(db, "db_path", None) or id(db), language)
    with _SYNC_LOCKS_GUARD:
        return _SYNC_LOCKS.setdefault(key, threading.Lock())


def sync_language(db, language: str, *, allow_network: bool = True) -> dict:
    """Incrementally synchronize one language; keeps partial progress and never runs concurrently per language."""
    language = _normalize_target(language)
    info = inspect_language(db, language)
    if language in {"fa", "en"}:
        info["generated_count"] = 0
        db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                       info["source_count"], 0, 0, "builtin")
        return info
    if not allow_network and info["missing_count"]:
        info["generated_count"] = 0
        db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                       info["translated_count"], info["missing_count"], info["obsolete_count"], "pending")
        return info
    if not info["missing_count"]:
        info["generated_count"] = 0
        db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                       info["translated_count"], 0, info["obsolete_count"], "current")
        return info
    lock = _sync_lock(db, language)
    if not lock.acquire(blocking=False):
        info["generated_count"] = 0
        info["status"] = "busy"
        return info
    try:
        try:
            generated, failures = translate_many_partial(info["missing"], language, cached=db.translation_catalog(language), db=db)
        except Exception as exc:
            db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                           info["translated_count"], info["missing_count"], info["obsolete_count"], "error", str(exc)[:500])
            db.add_translation_history(language, info["catalog_version"], info["source_count"],
                                       info["translated_count"], 0, info["obsolete_count"], "error")
            raise
        if generated:
            db.upsert_translations(language, generated, source="machine")
        info = inspect_language(db, language)
        info["generated_count"] = len(generated)
        error = None
        if info["missing_count"]:
            info["status"] = "partial" if _missing_ratio(info) <= PARTIAL_MAX_RATIO else "pending"
            error = "; ".join(failures[-3:])[:500] or None
        db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                       info["translated_count"], info["missing_count"], info["obsolete_count"], info["status"], error)
        db.add_translation_history(language, info["catalog_version"], info["source_count"],
                                   info["translated_count"], len(generated), info["obsolete_count"], info["status"])
        return info
    finally:
        lock.release()


def translation_health(db, language: str | None = None) -> dict | list[dict]:
    """Return operational health for one language or all managed languages."""
    source = source_catalog()
    version = catalog_version(source)
    rows = db.list_languages(enabled_only=False)
    out = []
    for row in rows:
        code = row["code"]
        if code in {"fa", "en"}:
            continue
        if language and code != language:
            continue
        manifest = db.get_translation_manifest(code)
        info = inspect_language(db, code)
        out.append({
            "language": code,
            "enabled": bool(row["enabled"]),
            "auto_quarantined": bool(row["translation_auto_quarantined"] or 0),
            "retry_count": int(row["translation_retry_count"] or 0),
            "last_failure": row["translation_last_failure"],
            "catalog_version": version,
            "manifest_status": manifest["status"] if manifest else None,
            "missing_count": info["missing_count"],
            "obsolete_count": info["obsolete_count"],
            "healthy": info["missing_count"] == 0 and (not manifest or manifest["status"] in {"current", "builtin"}),
        })
    return out[0] if language and out else out


def sync_enabled_languages(db, *, allow_network: bool = True) -> list[dict]:
    """Sync enabled languages; quarantine only languages with too many missing strings and auto-recover them."""
    results = []
    rows = db.list_translation_recovery_languages() if hasattr(db, "list_translation_recovery_languages") else db.list_languages(enabled_only=True)
    for row in rows:
        code = row["code"]
        if code in {"fa", "en"}:
            continue
        quarantined = bool(row.get("translation_auto_quarantined", 0) if hasattr(row, "get") else row["translation_auto_quarantined"])
        try:
            result = sync_language(db, code, allow_network=allow_network)
            if result.get("status") == "busy":
                result["health"] = "busy"
            elif result["missing_count"] and _missing_ratio(result) > PARTIAL_MAX_RATIO:
                error = f"{result['missing_count']} translation(s) missing"
                db.disable_language(code, automatic=True, error=error)
                result["disabled"] = True
                result["recovered"] = False
                result["health"] = "quarantined"
            else:
                if quarantined or bool(row["enabled"]):
                    db.enable_language(code, generated=True, automatic=True)
                result["disabled"] = False
                result["recovered"] = quarantined
                result["health"] = "partial" if result["missing_count"] else ("recovered" if quarantined else "healthy")
            results.append(result)
        except Exception as exc:
            error = str(exc)[:500]
            db.disable_language(code, automatic=True, error=error)
            results.append({"language": code, "status": "error", "error": error, "disabled": True, "recovered": False, "health": "quarantined"})
    return results


def generate_language(db, language: str) -> int:
    """Backward-compatible entry point; performs an incremental sync."""
    info = sync_language(db, language, allow_network=True)
    return int(info.get("source_count", 0) - info.get("translated_count", 0)) if info.get("status") == "error" else int(info.get("generated_count", 0) or 0)


def prewarm_language(db, language: str) -> dict:
    """Materialize a language catalog; usable when complete or missing at most PARTIAL_MAX_RATIO of strings."""
    code = _normalize_target(language)
    result = sync_language(db, code, allow_network=True)
    result["prewarmed"] = result.get("missing_count", 0) == 0 or (
        result.get("status") in {"partial", "busy"} and _missing_ratio(result) <= PARTIAL_MAX_RATIO
    )
    result["cache_entries"] = len(db.translation_catalog(code)) if code not in {"fa", "en"} else 0
    if not result["prewarmed"]:
        raise RuntimeError(f"Language {code} is not fully prewarmed")
    return result


def prewarm_enabled_languages(db) -> list[dict]:
    """Prewarm all enabled dynamic languages; quarantine those that cannot be completed."""
    results = []
    rows = db.list_languages(enabled_only=True)
    for row in rows:
        code = row["code"]
        if code in {"fa", "en"}:
            continue
        try:
            result = prewarm_language(db, code)
            result["health"] = "warm"
            results.append(result)
        except Exception as exc:
            error = str(exc)[:500]
            db.disable_language(code, automatic=True, error=error)
            results.append({"language": code, "prewarmed": False, "health": "quarantined", "error": error})
    return results
