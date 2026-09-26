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
import re
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
# Keep provider defaults current. These can always be overridden with the
# corresponding SHOPVPN_TRANSLATION_*_MODEL environment variables.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_OPENROUTER_MODEL = "google/gemini-3.8-flash"
DEFAULT_PROVIDER_ORDER = "argos,libretranslate,google,mymemory,gemini,openrouter"
_SHARED_CACHE: Dict[tuple, str] = {}
_PROVIDER_RUNTIME: Dict[str, dict] = {}
_SYNC_LOCKS: Dict[tuple, threading.Lock] = {}
_SYNC_LOCKS_GUARD = threading.Lock()

# --- Live progress/log feed for the admin panel ----------------------------
# One entry per language, holding a bounded rolling log of what the sync is
# doing right now (which provider, which batch, how many succeeded) plus a
# done/total counter. This is in-memory only (per-process), which is fine
# since sync_language already only ever runs one job per language at a time
# (see _SYNC_LOCKS above) and the admin panel polls the same process.
_PROGRESS: Dict[str, dict] = {}
_PROGRESS_LOCK = threading.Lock()
_PROGRESS_LOG_MAX = 300


def _progress_state(language: str) -> dict:
    return _PROGRESS.setdefault(language, {
        "run_id": 0, "running": False, "total": 0, "done": 0,
        "started_at": None, "finished_at": None, "seq": 0,
        "entries": deque(maxlen=_PROGRESS_LOG_MAX),
    })


def _progress_start(language: str, total: int) -> None:
    with _PROGRESS_LOCK:
        state = _progress_state(language)
        state["run_id"] += 1
        state["running"] = True
        state["total"] = total
        state["done"] = 0
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["entries"].clear()
    _progress_log(language, f"شروع همگام‌سازی: {total} مورد ناقص", level="info")


def _progress_log(language: str, message: str, *, level: str = "info", done_delta: int = 0) -> None:
    with _PROGRESS_LOCK:
        state = _progress_state(language)
        state["seq"] += 1
        if done_delta:
            state["done"] = min(state.get("total", 0) or (state["done"] + done_delta), state["done"] + done_delta)
        state["entries"].append({
            "seq": state["seq"], "ts": time.time(), "level": level, "message": str(message),
        })


def _progress_finish(language: str, status: str) -> None:
    with _PROGRESS_LOCK:
        state = _progress_state(language)
        state["running"] = False
        state["finished_at"] = time.time()
    _progress_log(language, f"پایان همگام‌سازی — وضعیت: {status}", level=("error" if status == "error" else "done"))


def get_progress(language: str, since: int = 0) -> dict:
    """Snapshot of the live sync log for one language, for the admin panel to poll."""
    language = _normalize_target(language)
    with _PROGRESS_LOCK:
        state = _PROGRESS.get(language)
        if not state:
            return {"running": False, "total": 0, "done": 0, "seq": 0, "entries": [], "run_id": 0}
        entries = [dict(e) for e in state["entries"] if e["seq"] > since]
        return {
            "running": state["running"], "total": state["total"], "done": state["done"],
            "seq": state["seq"], "run_id": state["run_id"], "entries": entries,
        }
# deep-translator's GoogleTranslator accepts bare ISO codes; MyMemory's free API
# only recognizes locale-qualified codes for most non-English targets.
_MYMEMORY_LANG = {
    "tr": "tr-TR", "ar": "ar-SA", "ru": "ru-RU", "de": "de-DE", "fr": "fr-FR",
    "es": "es-ES", "it": "it-IT", "pt": "pt-PT", "zh": "zh-CN", "ja": "ja-JP",
    "ko": "ko-KR", "nl": "nl-NL", "pl": "pl-PL", "uk": "uk-UA",
}
# LibreTranslate's argos-translate models expose Chinese under the code
# "zh-Hans" (per its own /languages endpoint), not the bare "zh" the rest of
# ShopVPN's catalog uses; without this, every Chinese request 404s/errors on
# a self-hosted LibreTranslate instance even though the model is installed.
_LIBRETRANSLATE_LANG = {"zh": "zh-Hans"}
GLOSSARY = (
    "ShopVPN, VPN, Telegram, Mini App, Stars, USDT stay untranslated. "
    "'Toman' stays 'Toman'. 'Config' means a VPN configuration. "
    "'Reseller' means a partner who resells VPN services. 'Subscription link' means a VPN subscription URL. "
    "'Inbound' and 'Xray' are technical terms and stay untranslated."
)

log = logging.getLogger(__name__)

# Argos/Stanza are extremely chatty at INFO level (sentence segmentation,
# tokenization and beam-search hypotheses). ShopVPN only needs the final
# translation, so suppress their internal trace while a local translation is
# running. The temporary global INFO suppression is protected by a lock so it
# cannot interleave between concurrent translation jobs.
for _logger_name in ("argostranslate", "argostranslate.utils", "stanza", "stanza.pipeline"):
    _logger = logging.getLogger(_logger_name)
    _logger.setLevel(logging.WARNING)
    _logger.propagate = False

_ARGOS_LOG_LOCK = threading.Lock()

_TOKEN_RE = re.compile(
    r"_{1,2}\s*SHOPVPN\s*_?\s*TOKEN\s*_?\s*(\d+)\s*_{1,2}",
    re.I,
)

def _argos_translate_preserving_tokens(translation, text: str) -> str:
    """Translate only human-readable segments; never send ShopVPN tokens to Argos.

    ``translation_engine`` protects URLs/placeholders/markup before calling a
    provider. Argos/Stanza must not see those sentinels at all: it tokenizes
    values such as ``__SHOPVPN_TOKEN_000__`` and may alter them. We therefore
    split the protected string into ordinary-text segments and translate each
    segment independently, then stitch the untouched sentinel back in.
    """
    value = str(text or "")
    matches = list(_TOKEN_RE.finditer(value))

    def _translate_segment(segment: str) -> str:
        if not segment or not segment.strip():
            return segment
        # Argos/Stanza logs at INFO from several internal logger names. Disable
        # INFO globally only for the short synchronous model call.
        with _ARGOS_LOG_LOCK:
            previous_disable = logging.root.manager.disable
            logging.disable(logging.INFO)
            try:
                return str(translation.translate(segment))
            finally:
                logging.disable(previous_disable)

    if not matches:
        return _translate_segment(value)

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(_translate_segment(value[cursor:match.start()]))
        # The sentinel is copied byte-for-byte; it is never passed to Argos.
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(_translate_segment(value[cursor:]))
    return "".join(pieces)


def _mark_provider(name: str, *, ok: bool, error: str | None = None) -> None:
    state = _PROVIDER_RUNTIME.setdefault(name, {"attempts": 0, "successes": 0, "failures": 0, "last_error": None, "last_status": None})
    state["attempts"] += 1
    if ok:
        state["successes"] += 1
        state["last_status"] = "ok"
        state["last_error"] = None
    else:
        state["failures"] += 1
        state["last_status"] = "error"
        state["last_error"] = str(error or "provider failed")[:500]


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
                 min_interval: float = 0.0, max_retries: int = 2, source: str = "en"):
        self.provider_cls = provider_cls
        self.name = name
        self.lang_map = lang_map or {}
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.source = source
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
            translator = self.provider_cls(source=self.source, target=target_code)
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

    def __init__(self, endpoint: str, api_key: str | None = None, source: str = "en"):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.source = source

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        target = _LIBRETRANSLATE_LANG.get(target, target)
        out = []
        for text in texts:
            payload = {"q": text, "source": self.source, "target": target, "format": "text"}
            if self.api_key:
                payload["api_key"] = self.api_key
            req = urllib.request.Request(
                self.endpoint + "/translate",
                data=urllib.parse.urlencode(payload).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ShopVPN/1.0"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    data = _json.loads(response.read().decode("utf-8"))
                value = data.get("translatedText") if isinstance(data, dict) else None
                if not value:
                    raise RuntimeError("empty translatedText")
                out.append(str(value))
            except Exception as exc:
                raise TranslationProviderError(f"{self.name}: {exc}") from exc
        return out




class _ArgosProvider(_Provider):
    """Local/offline Argos Translate provider.

    It never contacts the network. Translation model packages must already be
    installed on the host; if a direct pair is unavailable Argos may use an
    installed pivot language.
    """
    name = "argos"

    def __init__(self, source: str = "en"):
        self.source = source
        try:
            import argostranslate.translate as _argos_translate
        except Exception as exc:
            raise TranslationProviderError(f"argos: package not installed: {exc}") from exc
        self._argos_translate = _argos_translate

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        target = _normalize_target(target)
        try:
            translation = self._argos_translate.get_translation_from_codes(self.source, target)
        except Exception as exc:
            raise TranslationProviderError(
                f"argos: no installed model for {self.source}->{target}: {exc}"
            ) from exc
        out = []
        for text in texts:
            try:
                value = _argos_translate_preserving_tokens(translation, text)
            except Exception as exc:
                raise TranslationProviderError(f"argos: {exc}") from exc
            if value is None or not str(value).strip():
                raise TranslationProviderError("argos: empty translation")
            out.append(str(value))
        return out


class _GeminiProvider(_Provider):
    name = "gemini"

    def __init__(self, keys: list[str], model: str, client_factory=None, source_name: str = "English"):
        self.keys = keys
        self.model = model
        self.client_factory = client_factory
        self.source_name = source_name

    def _client(self, key: str):
        if self.client_factory:
            return self.client_factory(key)
        from google import genai
        return genai.Client(api_key=key)

    def _config(self, target: str):
        from google.genai import types
        name = "English" if target == "en" else LANGUAGE_CATALOG.get(target, {}).get("name", target)
        instruction = (
            f"You translate UI strings of a VPN sales Telegram bot from {self.source_name} to {name}. "
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


def _extract_json_array(text: str) -> str:
    """Pull the JSON array out of a model reply that may be wrapped in markdown fences or prose."""
    text = text.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array found in response")
    return text[start:end + 1]


class _OpenRouterProvider(_Provider):
    """LLM-based translation via OpenRouter's OpenAI-compatible chat API.

    Unlike Gemini, this needs no Google Cloud project — just an API key from
    openrouter.ai — which makes it a usable fallback where creating a GCP
    project is blocked (e.g. by Google's own regional restrictions).
    """
    name = "openrouter"

    def __init__(self, keys: list[str], model: str, source_name: str = "English"):
        self.keys = keys
        self.model = model
        self.source_name = source_name

    def _instruction(self, target: str) -> str:
        name = "English" if target == "en" else LANGUAGE_CATALOG.get(target, {}).get("name", target)
        return (
            f"You translate UI strings of a VPN sales Telegram bot from {self.source_name} to {name}. "
            "Input is a JSON list of {id, text, context}. Reply with ONLY a JSON array of {id, text} "
            "containing the translation of each item — no markdown fences, no extra commentary. "
            "Keep tokens like __SHOPVPN_TOKEN_000__, emoji, line breaks and leading/trailing punctuation "
            "exactly as in the source. Use short natural wording for buttons. " + GLOSSARY
        )

    def translate_batch(self, texts: list[str], target: str, contexts: Dict[str, str] | None = None) -> list[str]:
        contexts = contexts or {}
        payload = json.dumps(
            [{"id": i, "text": t, "context": contexts.get(t, "")} for i, t in enumerate(texts)],
            ensure_ascii=False,
        )
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._instruction(target)},
                {"role": "user", "content": payload},
            ],
        }).encode("utf-8")
        last: Exception | None = None
        for key in self.keys:
            try:
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as response:
                    data = _json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(_extract_json_array(content))
                by_id = {int(item["id"]): str(item["text"]) for item in parsed}
                return [by_id.get(i, "") for i in range(len(texts))]
            except Exception as exc:
                last = exc
        raise TranslationProviderError(f"openrouter: {last}")


def _provider_order() -> list[str]:
    raw = os.getenv("SHOPVPN_TRANSLATION_PROVIDERS", DEFAULT_PROVIDER_ORDER)
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


def _openrouter_keys(db=None) -> list[str]:
    """Admin-panel key (stored in the main bot's database) wins; env vars are the fallback."""
    from_db = _split_keys(_db_setting(db, "translation_openrouter_api_key"))
    if from_db:
        return from_db
    raw = os.getenv("SHOPVPN_OPENROUTER_API_KEY") or ""
    return _split_keys(raw)


def openrouter_key_source(db=None) -> str:
    """Where the OpenRouter key used for translation currently comes from, for admin UIs."""
    if _split_keys(_db_setting(db, "translation_openrouter_api_key")):
        return "panel"
    if os.getenv("SHOPVPN_OPENROUTER_API_KEY"):
        return "env"
    return "none"


def _public_translation_allowed() -> bool:
    return os.getenv("SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS", "0").strip().lower() in {"1", "true", "yes", "on"}


def _is_local_endpoint(endpoint: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("192.168.") or host.startswith("10.")
    except Exception:
        return False


def _providers(target: str, db=None, *, local_only: bool = False) -> list[_Provider]:
    providers: list[_Provider] = []
    public_allowed = _public_translation_allowed() and not local_only
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except Exception:
        GoogleTranslator = MyMemoryTranslator = None
    for name in _provider_order():
        if name == "argos":
            try:
                providers.append(_ArgosProvider(source="en"))
            except Exception:
                pass
        elif name == "gemini" and public_allowed:
            keys = _gemini_keys(db)
            if keys:
                providers.append(_GeminiProvider(keys, os.getenv("SHOPVPN_TRANSLATION_MODEL", DEFAULT_GEMINI_MODEL)))
        elif name == "openrouter" and public_allowed:
            keys = _openrouter_keys(db)
            if keys:
                providers.append(_OpenRouterProvider(
                    keys, os.getenv("SHOPVPN_TRANSLATION_OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
                ))
        elif name == "google" and GoogleTranslator and public_allowed:
            # Google's free web endpoint allows ~5 req/s; stay safely under that.
            providers.append(_DeepTranslatorProvider(GoogleTranslator, "google", min_interval=0.3))
        elif name in {"mymemory", "my-memory"} and MyMemoryTranslator and public_allowed:
            providers.append(_DeepTranslatorProvider(
                MyMemoryTranslator, "mymemory", lang_map=_MYMEMORY_LANG, min_interval=1.0,
                source="en-US",
            ))
        elif name == "libretranslate":
            endpoint = os.getenv("SHOPVPN_LIBRETRANSLATE_URL", "").strip()
            if endpoint and ((_is_local_endpoint(endpoint)) or (public_allowed and not local_only)):
                providers.append(_LibreTranslateProvider(endpoint, os.getenv("SHOPVPN_LIBRETRANSLATE_API_KEY")))
    return providers


def _fa_en_providers(db=None, *, local_only: bool = False) -> list[_Provider]:
    """Providers configured to translate FROM Persian TO English.

    Mirrors ``_providers`` but every provider is pointed at the reverse
    direction, since the rest of the engine only ever translates English UI
    text into other languages. This is what lets the English admin-panel UI
    itself be completed automatically instead of relying solely on the
    static M/FRAGMENTS dictionary in i18n.js.
    """
    providers: list[_Provider] = []
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except Exception:
        GoogleTranslator = MyMemoryTranslator = None
    public_allowed = _public_translation_allowed() and not local_only
    for name in _provider_order():
        if name == "argos":
            try:
                providers.append(_ArgosProvider(source="fa"))
            except Exception:
                pass
        elif name == "gemini" and public_allowed:
            keys = _gemini_keys(db)
            if keys:
                providers.append(_GeminiProvider(
                    keys, os.getenv("SHOPVPN_TRANSLATION_MODEL", DEFAULT_GEMINI_MODEL), source_name="Persian",
                ))
        elif name == "openrouter" and public_allowed:
            keys = _openrouter_keys(db)
            if keys:
                providers.append(_OpenRouterProvider(
                    keys, os.getenv("SHOPVPN_TRANSLATION_OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
                    source_name="Persian",
                ))
        elif name == "google" and GoogleTranslator and public_allowed:
            providers.append(_DeepTranslatorProvider(GoogleTranslator, "google", min_interval=0.3, source="fa"))
        elif name in {"mymemory", "my-memory"} and MyMemoryTranslator and public_allowed:
            providers.append(_DeepTranslatorProvider(
                MyMemoryTranslator, "mymemory", min_interval=1.0, source="fa-IR",
            ))
        elif name == "libretranslate":
            endpoint = os.getenv("SHOPVPN_LIBRETRANSLATE_URL", "").strip()
            if endpoint and ((_is_local_endpoint(endpoint)) or (public_allowed and not local_only)):
                providers.append(_LibreTranslateProvider(endpoint, os.getenv("SHOPVPN_LIBRETRANSLATE_API_KEY"), source="fa"))
    return providers


def translate_fa_to_english_partial(texts: Iterable[str], *, cached: Dict[str, str] | None = None, db=None) -> tuple[Dict[str, str], list[str]]:
    """Translate raw Persian admin-panel strings straight into English.

    Keyed by the original Persian text (unlike the fa->en->target pipeline
    used for other languages, there is no intermediate English string to key
    on here). Returns (translations, failure messages); never raises, so
    partial progress is kept even if a provider is down.
    """
    values = list(dict.fromkeys(str(x) for x in texts if str(x).strip()))
    result: Dict[str, str] = {}
    cached = cached or {}
    for value in values:
        candidate = cached.get(value) or _SHARED_CACHE.get(("en", value))
        if candidate and str(candidate).strip() and validate(value, str(candidate), "en")[0]:
            result[value] = str(candidate)
    remaining = [x for x in values if x not in result]
    if not remaining:
        return result, []
    providers = _fa_en_providers(db)
    if not providers:
        raise RuntimeError("No local translation provider is configured. Install Argos model packages or configure a self-hosted LibreTranslate. Public APIs are disabled by default; set SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS=1 only if you explicitly want them.")
    failures: list[str] = []
    for provider in providers:
        if not remaining:
            break
        protected = {value: protect(value) for value in remaining}
        still: list[str] = []
        provider_failed = False
        for i in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[i:i + BATCH_SIZE]
            if provider_failed:
                still.extend(batch)
                continue
            try:
                translated = provider.translate_batch([protected[v][0] for v in batch], "en", {})
                if not translated or len(translated) != len(batch):
                    raise TranslationProviderError(f"{provider.name}: incomplete batch")
            except Exception as exc:
                failures.append(str(exc))
                _mark_provider(provider.name, ok=False, error=exc)
                log.warning("Translation provider %s failed for fa->en: %s", provider.name, exc)
                provider_failed = True
                still.extend(batch)
                continue
            for src, dst in zip(batch, translated):
                restored = restore(str(dst or ""), protected[src][1])
                ok, reason = validate(src, restored, "en")
                if ok:
                    result[src] = restored
                    _SHARED_CACHE[("en", src)] = restored
                    _mark_provider(provider.name, ok=True)
                else:
                    failures.append(f"{provider.name}: rejected {src!r}: {reason}")
                    still.append(src)
        remaining = still
    return result, failures


def translate_many_to_english(texts: Iterable[str], *, cached: Dict[str, str] | None = None, db=None) -> Dict[str, str]:
    """Translate every Persian string into English or raise; keeps partial progress via cached."""
    texts = [str(x) for x in texts]
    result, failures = translate_fa_to_english_partial(texts, cached=cached, db=db)
    values = list(dict.fromkeys(x for x in texts if x.strip()))
    missing = [x for x in values if x not in result]
    if missing:
        raise RuntimeError("All translation providers failed; missing %d item(s): %s" % (len(missing), "; ".join(failures[-3:])))
    return result


def provider_status(db=None) -> list[dict]:
    """Describe translation providers and whether they are locally usable.

    This intentionally does not call public APIs.
    """
    providers = _providers("tr", db)
    names = {p.name for p in providers}
    out = []
    for name in _provider_order():
        if name == "argos":
            installed = "argos" in names
            item = {"name": name, "configured": installed, "local": True, "network": False, "status": "ready" if installed else "not_installed"}
            item.update({k: v for k, v in _PROVIDER_RUNTIME.get(name, {}).items() if k in {"attempts", "successes", "failures", "last_error", "last_status"}})
            out.append(item)
        elif name == "libretranslate":
            endpoint = os.getenv("SHOPVPN_LIBRETRANSLATE_URL", "").strip()
            configured = bool(endpoint and (not _public_translation_allowed() or _is_local_endpoint(endpoint)))
            item = {"name": name, "configured": configured, "local": _is_local_endpoint(endpoint) if endpoint else False, "network": True, "status": "configured" if configured else "not_configured"}
            item.update({k: v for k, v in _PROVIDER_RUNTIME.get(name, {}).items() if k in {"attempts", "successes", "failures", "last_error", "last_status"}})
            out.append(item)
        elif name in {"gemini", "openrouter"}:
            key = bool(_gemini_keys(db) if name == "gemini" else _openrouter_keys(db))
            item = {"name": name, "configured": key and _public_translation_allowed(), "local": False, "network": True, "status": "disabled_by_default" if not _public_translation_allowed() else ("configured" if key else "no_key")}
            item.update({k: v for k, v in _PROVIDER_RUNTIME.get(name, {}).items() if k in {"attempts", "successes", "failures", "last_error", "last_status"}})
            out.append(item)
        else:
            enabled = _public_translation_allowed()
            item = {"name": name, "configured": enabled, "local": False, "network": True, "status": "enabled" if enabled else "disabled_by_default"}
            item.update({k: v for k, v in _PROVIDER_RUNTIME.get(name, {}).items() if k in {"attempts", "successes", "failures", "last_error", "last_status"}})
            out.append(item)
    return out


def _normalize_target(target: str) -> str:
    return (target or "").lower().split("-", 1)[0]


def translate_many_partial(texts: Iterable[str], target: str, *, cached: Dict[str, str] | None = None, db=None, local_only: bool = False, progress: bool = False) -> tuple[Dict[str, str], list[str]]:
    """Translate as many strings as possible; return (translations, failure messages).

    When ``progress`` is true (only ``sync_language`` sets this), each step is
    also appended to that language's live log (see ``get_progress``) so the
    admin panel can show what is happening instead of a plain "please wait".
    """
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
    if progress and (len(values) - len(remaining)):
        _progress_log(target, f"{len(values) - len(remaining)} مورد از قبل در حافظه موجود بود", done_delta=len(values) - len(remaining))
    if not remaining:
        return result, []
    providers = _providers(target, db, local_only=local_only)
    if not providers:
        if progress:
            _progress_log(target, "هیچ ارائه‌دهنده‌ی ترجمه‌ای در دسترس نیست", level="error")
        raise RuntimeError("No local translation provider is configured. Install Argos model packages or configure a self-hosted LibreTranslate. Public APIs are disabled by default; set SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS=1 only if you explicitly want them.")
    failures: list[str] = []
    for provider in providers:
        if not remaining:
            break
        if progress:
            _progress_log(target, f"تلاش با ارائه‌دهنده «{provider.name}» برای {len(remaining)} مورد باقی‌مانده")
        protected = {value: protect(value) for value in remaining}
        contexts = {}
        for value in remaining:
            found = context_for_text(value)
            if found:
                contexts[protected[value][0]] = found[0]["context"]
        still: list[str] = []
        provider_failed = False
        batch_count = (len(remaining) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[i:i + BATCH_SIZE]
            batch_no = i // BATCH_SIZE + 1
            if provider_failed:
                still.extend(batch)
                continue
            if progress:
                _progress_log(target, f"دسته {batch_no}/{batch_count} — ارسال {len(batch)} مورد به «{provider.name}»")
            try:
                translated = provider.translate_batch([protected[v][0] for v in batch], target, contexts)
                if not translated or len(translated) != len(batch):
                    raise TranslationProviderError(f"{provider.name}: incomplete batch")
            except Exception as exc:
                failures.append(str(exc))
                _mark_provider(provider.name, ok=False, error=exc)
                log.warning("Translation provider %s failed for %s: %s", provider.name, target, exc)
                if progress:
                    _progress_log(target, f"ارائه‌دهنده «{provider.name}» متوقف شد: {exc}", level="warn")
                provider_failed = True
                still.extend(batch)
                continue
            batch_ok = 0
            batch_rejected = 0
            for src, dst in zip(batch, translated):
                restored = restore(str(dst or ""), protected[src][1])
                ok, reason = validate(src, restored, target)
                if ok:
                    result[src] = restored
                    _SHARED_CACHE[(target, src)] = restored
                    _mark_provider(provider.name, ok=True)
                    batch_ok += 1
                else:
                    failures.append(f"{provider.name}: rejected {src!r}: {reason}")
                    still.append(src)
                    batch_rejected += 1
            if progress:
                msg = f"دسته {batch_no}/{batch_count} — {batch_ok} مورد موفق"
                if batch_rejected:
                    msg += f"، {batch_rejected} مورد رد شد"
                _progress_log(target, msg, done_delta=batch_ok)
        remaining = still
    if progress and remaining:
        _progress_log(target, f"{len(remaining)} مورد پس از تمام ارائه‌دهندگان همچنان ترجمه نشد", level="warn")
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
    _progress_start(language, info["missing_count"])
    try:
        try:
            generated, failures = translate_many_partial(info["missing"], language, cached=db.translation_catalog(language), db=db, local_only=not allow_network, progress=True)
        except Exception as exc:
            db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                           info["translated_count"], info["missing_count"], info["obsolete_count"], "error", str(exc)[:500])
            db.add_translation_history(language, info["catalog_version"], info["source_count"],
                                       info["translated_count"], 0, info["obsolete_count"], "error")
            _progress_log(language, f"خطا: {exc}", level="error")
            _progress_finish(language, "error")
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
        _progress_log(language, f"{len(generated)} مورد ترجمه شد، {info['missing_count']} مورد باقی‌مانده")
        _progress_finish(language, info["status"])
        return info
    finally:
        lock.release()


def sync_quick(db, language: str) -> dict:
    """Fast-path sync used when an admin activates a language: translates only
    the hand-curated, high-frequency phrase catalog (``i18n._TRANSLATIONS['en']``
    — the main menu and the most common buttons/messages) so the very first
    thing a user sees is already translated. Everything else is left for
    ``translate_texts_now`` to fill in on demand, per string, the moment a real
    user reaches it."""
    import i18n
    language = _normalize_target(language)
    if language in {"fa", "en"}:
        return {"language": language, "status": "builtin", "generated_count": 0}
    quick_texts = [v for v in i18n._TRANSLATIONS.get("en", {}).values() if v and v.strip()]
    cached = db.translation_catalog(language)
    generated, failures = translate_many_partial(quick_texts, language, cached=cached, db=db)
    if generated:
        db.upsert_translations(language, generated, source="machine")
    info = inspect_language(db, language)
    info["generated_count"] = len(generated)
    # "lazy": deliberately activated with an incomplete catalog; the rest fills
    # in over time as sync_language / translate_texts_now cover more ground.
    status = "lazy" if info["missing_count"] else info["status"]
    db.upsert_translation_manifest(language, info["catalog_version"], info["source_count"],
                                   info["translated_count"], info["missing_count"], info["obsolete_count"],
                                   status, "; ".join(failures[-3:])[:500] or None)
    info["status"] = status
    return info


def translate_texts_now(db, language: str, texts: Iterable[str]) -> Dict[str, str]:
    """On-demand translation of a small, specific set of source (English)
    texts — called right before the bot sends a message whose catalog lookup
    just missed. Returns ``{source_text: translated_text}`` for whatever could
    be resolved and persists successes into the shared catalog so every future
    lookup (by any user) hits the cache instead of calling out again."""
    language = _normalize_target(language)
    texts = [str(x) for x in texts if str(x).strip()]
    if not texts or language in {"fa", "en"}:
        return {}
    cached = db.translation_catalog(language)
    generated, _failures = translate_many_partial(texts, language, cached=cached, db=db)
    if generated:
        db.upsert_translations(language, generated, source="machine")
    return generated


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
