# -*- coding: utf-8 -*-
"""Locate store products from the config links stored in their inventory."""
import asyncio
import logging
import time
from typing import Optional

import aiohttp

import geo_scan

logger = logging.getLogger(__name__)

SAMPLE_PER_PRODUCT = 40
TARGETS_PER_LOCATION = 3
_TTL_OK = 6 * 3600
_TTL_FAIL = 1800
_TCP_TTL = 120

_host_cache: dict = {}
_sub_cache: dict = {}
_SUB_TTL = 600
_SUB_URLS_PER_PRODUCT = 2
_tcp_cache: dict = {}
_SUB_TTL_FAIL = 60
_last_good: dict = {}          # {product_id: (time, locations)} آخرین موقعیتِ موفق هر محصول
_LAST_GOOD_MAX_AGE = 7 * 86400


def _fresh(entry: Optional[dict], now: float) -> bool:
    if not entry:
        return False
    return now - entry["at"] < (_TTL_OK if entry["geo"] else _TTL_FAIL)


async def _resolve_hosts(hosts: set) -> None:
    now = time.time()
    todo = [h for h in hosts if not _fresh(_host_cache.get(h), now)]
    if not todo:
        return
    sem = asyncio.Semaphore(geo_scan._DNS_CONCURRENCY)
    ips = await asyncio.gather(*(geo_scan._resolve(h, sem) for h in todo))
    host_ip = dict(zip(todo, ips))
    unique_ips = sorted({ip for ip in ips if ip})
    geo = await geo_scan._geolocate(unique_ips) if unique_ips else {}
    for host, ip in host_ip.items():
        new_geo = geo.get(ip) if ip else None
        prev = _host_cache.get(host) or {}
        if new_geo is None and prev.get("geo"):
            # DNS/GeoIP موقتاً شکست خورده (مثلاً محدودیت نرخ ip-api): موقعیتِ قبلی حفظ می‌شود
            # تا نود از نقشه حذف نشود؛ فقط زمان بررسی تازه می‌شود تا کمی بعد دوباره تلاش شود.
            _host_cache[host] = {"ip": prev.get("ip") or ip or "", "geo": prev["geo"], "at": now - _TTL_OK + _TTL_FAIL}
        else:
            _host_cache[host] = {"ip": ip or "", "geo": new_geo, "at": now}


def _locate(entry: dict) -> Optional[dict]:
    cached = _host_cache.get(entry["host"]) or {}
    geo = cached.get("geo")
    label_cc = geo_scan.detect_label_country(entry.get("remark") or "")
    if label_cc:
        name, lat, lon = geo_scan.COUNTRY_INFO[label_cc]
        cc, city = label_cc, ""
        if geo and geo["country_code"] == label_cc:
            lat, lon, city = geo["lat"], geo["lon"], geo["city"]
    elif geo:
        cc, lat, lon, city = geo["country_code"], geo["lat"], geo["lon"], geo["city"]
    else:
        return None
    port = int(entry["port"]) if str(entry.get("port") or "").isdigit() else 0
    return {"cc": cc.lower(), "city": city, "lat": float(lat), "lon": float(lon), "ip": cached.get("ip") or "", "port": port}


def _name_fallback(name: str) -> Optional[dict]:
    cc = geo_scan.detect_label_country(name or "")
    if not cc:
        return None
    label, lat, lon = geo_scan.COUNTRY_INFO[cc]
    return {"cc": cc.lower(), "city": label, "lat": lat, "lon": lon, "ip": "", "port": 0}


async def _fetch_sub_entries(url: str) -> list:
    now = time.time()
    cached = _sub_cache.get(url)
    if cached and now - cached[0] < (_SUB_TTL if cached[1] else _SUB_TTL_FAIL):
        return cached[1]
    entries = []
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(url, headers={"User-Agent": "v2rayNG/1.8.29"}) as resp:
                text = await resp.text(errors="ignore")
        entries = geo_scan.parse_subscription_text(text)[:SAMPLE_PER_PRODUCT]
    except Exception:
        logger.warning("config_geo: subscription fetch failed", exc_info=True)
    if not entries and cached and cached[1]:
        # دریافت ساب شکست خورد: نتیجه‌ی قبلی را نگه دار (خالی کش نکن) و زود دوباره تلاش کن.
        _sub_cache[url] = (now - _SUB_TTL + _SUB_TTL_FAIL, cached[1])
        return cached[1]
    _sub_cache[url] = (now, entries)
    return entries


async def locate_products(db, products: list) -> dict:
    """Return {product_id: {(lat1, lon1): {cc, city, lat, lon, targets}}} based on stored configs."""
    links_by_product = {}
    for p in products:
        links_by_product[p["id"]] = await asyncio.to_thread(db.get_config_links_for_geo, p["id"], SAMPLE_PER_PRODUCT)
    entries_by_product = {}
    hosts = set()
    for pid, links in links_by_product.items():
        found = []
        for link in links:
            items = geo_scan.parse_subscription_text(link)
            if items:
                found.append(items[0])
        if not found:
            sub_urls = await asyncio.to_thread(db.get_sub_urls_for_geo, pid, _SUB_URLS_PER_PRODUCT)
            for url in sub_urls:
                found.extend(await _fetch_sub_entries(url))
        hosts.update(e["host"] for e in found)
        entries_by_product[pid] = found
    await _resolve_hosts(hosts)

    result = {}
    for p in products:
        locations: dict = {}
        for entry in entries_by_product[p["id"]]:
            loc = _locate(entry)
            if not loc:
                continue
            key = (round(loc["lat"], 1), round(loc["lon"], 1))
            node = locations.setdefault(key, {**{k: loc[k] for k in ("cc", "city", "lat", "lon")}, "targets": []})
            target = (loc["ip"], loc["port"])
            if loc["ip"] and loc["port"] and target not in node["targets"] and len(node["targets"]) < TARGETS_PER_LOCATION:
                node["targets"].append(target)
        if not locations:
            # ۱) آخرین موقعیتِ موفقِ همین محصول (اگر بررسی فعلی موقتاً شکست خورده)
            good = _last_good.get(p["id"])
            if good and time.time() - good[0] < _LAST_GOOD_MAX_AGE:
                locations = {k: {**v, "targets": list(v.get("targets") or [])} for k, v in good[1].items()}
            else:
                # ۲) تشخیص از نام محصول (قبلاً فقط وقتی اصلاً کانفیگی نبود؛ حالا وقتی مکان‌یابی ناموفق بود هم)
                loc = _name_fallback(p["name"])
                if loc:
                    locations[(round(loc["lat"], 1), round(loc["lon"], 1))] = {**{k: loc[k] for k in ("cc", "city", "lat", "lon")}, "targets": []}
        else:
            _last_good[p["id"]] = (time.time(), {k: {**v, "targets": list(v.get("targets") or [])} for k, v in locations.items()})
        result[p["id"]] = locations
    return result


async def _tcp_probe(ip: str, port: int) -> tuple:
    """(status, latency_ms|None). status: online/offline/unknown؛ زمان = مدت برقراری TCP از سمت سرور فروشگاه."""
    now = time.time()
    cached = _tcp_cache.get((ip, port))
    if cached and now - cached[0] < _TCP_TTL:
        return cached[1], cached[2]
    t0 = time.perf_counter()
    status = await geo_scan._tcp_check(ip, port, asyncio.Semaphore(1), timeout=4.0)
    ms = round((time.perf_counter() - t0) * 1000) if status == "online" else None
    _tcp_cache[(ip, port)] = (now, status, ms)
    return status, ms


async def location_probe(targets: list) -> dict:
    """{"status": "up"|"down", "latency_ms": int|None}؛ 'down' فقط وقتی همه‌ی endpointها در دسترس نباشند."""
    if not targets:
        return {"status": "up", "latency_ms": None}
    res = await asyncio.gather(*(_tcp_probe(ip, port) for ip, port in targets))
    down = all(st == "offline" for st, _ in res)
    ms = [m for st, m in res if st == "online" and m is not None]
    return {"status": "down" if down else "up", "latency_ms": min(ms) if ms else None}


async def location_status(targets: list) -> str:
    """سازگاری با فراخوان‌های قبلی."""
    return (await location_probe(targets))["status"]
