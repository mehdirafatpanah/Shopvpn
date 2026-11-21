# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
رجیستری سراسری «کاستوم‌سازی دکمه‌ها» برای تب مستقل پنل وب.

این فایل تنها جایی است که پنل وب برای ساختن/ذخیره‌ی تب «دکمه‌ها» به آن نیاز
دارد. اگر بعداً دکمه‌ی جدیدی به بات اضافه شود:
  - اگر داخل منوی اصلی است: یک ورودی به MENU_BUTTON_META در database.py اضافه کن.
  - اگر داخل پنل مدیریت است: یک ورودی به ADMIN_PANEL_ITEMS/ADMIN_PANEL_CATEGORIES
    در keyboards.py اضافه کن.
  - اگر یک دکمه‌ی ثابت جدید در مسیر خرید/حساب کاربری/پرداخت است: به متادیتای
    مربوطه (BUYFLOW_META / ACCOUNT_HUB_META / PAYMENT_METHOD_META) در
    database.py اضافه کن.
در هر سه حالت، تب «دکمه‌ها»ی پنل وب بدون هیچ تغییری در این فایل یا فرانت‌اند،
آیتم جدید را خودکار نشان می‌دهد.
"""

import database as dbmod
import keyboards as kb

STYLE_CHOICES = ("", "primary", "success", "danger")


def _style_options():
    return [
        {"value": "", "label": "پیش‌فرض (خاکستری)"},
        {"value": "primary", "label": "آبی"},
        {"value": "success", "label": "سبز"},
        {"value": "danger", "label": "قرمز"},
    ]


def _is_layout_group(group: str) -> bool:
    return group in ("admin_categories", "account_hub", "payment_methods") or group.startswith("admin_items__") or group in kb.USER_SCREENS


def _wide_pack(group: str) -> bool:
    return group == "admin_categories" or group.startswith("admin_items__")


def _rows_for(db, group: str, keys: list, labels: dict):
    breaks = db.get_group_row_breaks(group)
    rows, cur = [], []
    if breaks is None:
        if group in kb.USER_SCREENS:
            present = set(keys)
            used = set()
            for drow in kb.USER_SCREENS[group]["default_rows"]:
                got = [k for k in drow if k in present]
                used.update(got)
                if got:
                    rows.append(got)
            rows.extend([k] for k in keys if k not in used)
            return rows, False
        if _wide_pack(group):
            for k in keys:
                if kb._is_wide_label(labels.get(k, "")):
                    if cur:
                        rows.append(cur)
                        cur = []
                    rows.append([k])
                else:
                    cur.append(k)
                    if len(cur) == 2:
                        rows.append(cur)
                        cur = []
            if cur:
                rows.append(cur)
            return rows, False
        return [[k] for k in keys], False
    break_set = set(breaks)
    for k in keys:
        if cur and k in break_set:
            rows.append(cur)
            cur = []
        cur.append(k)
    if cur:
        rows.append(cur)
    return rows, True


def _finish_group(db, group: dict) -> dict:
    if _is_layout_group(group["key"]):
        keys = [i["key"] for i in group["items"]]
        labels = {i["key"]: (i.get("text") or i.get("label") or "") for i in group["items"]}
        rows, custom = _rows_for(db, group["key"], keys, labels)
        group["rows"] = rows
        group["layout_custom"] = custom
        group["supports_row_break"] = True
    return group


def build_registry(db) -> dict:
    # نکته: منوی اصلی بات (کیبورد پایین/شیشه‌ای) متادیتای مخصوص خودش را در
    # MENU_BUTTON_META و APIهای /api/settings/menu-order|menu-layout دارد
    # (ترتیب + چیدمان ردیف‌ها + فعال/غیرفعال + متن/رنگ). فرانت‌اند تب «دکمه‌های
    # ربات» آن را جداگانه از همان API می‌خواند و به‌صورت یک گروه دیگر، کنار
    # گروه‌های این رجیستری، در همان تب نمایش می‌دهد - تا کل چیدمان دکمه‌های بات‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    # فقط از یک‌جا (تب دکمه‌های ربات) قابل مدیریت باشد. به همین دلیل عمداً اینجا
    # تکرار نشده.
    groups = []

    # -------------------------------------------------------- پنل مدیریت: دسته‌ها
    cat_default_order = [c[0] for c in kb.ADMIN_PANEL_CATEGORIES]
    cat_label_by_key = {c[0]: c[1] for c in kb.ADMIN_PANEL_CATEGORIES}
    cat_order = db.get_custom_order("admin_categories", cat_default_order)
    cat_items = []
    for key in cat_order:
        default_label = cat_label_by_key.get(key)
        if default_label is None:
            continue
        cat_items.append({
            "key": key, "label": default_label, "has_text": True, "has_style": True,
            "text": db.get_setting(f"catlbl_{key}", default_label),
            "style": db.get_setting(f"catlbl_{key}_style", ""),
            "row_break_before": None,
        })
    groups.append(_finish_group(db, {
        "key": "admin_categories", "label": "پنل مدیریت — دسته‌های اصلی",
        "reorderable": True, "supports_row_break": False, "items": cat_items,
    }))

    # -------------------------------------------------- پنل مدیریت: آیتم‌های هر دسته
    default_cat = {k: ck for ck, _l, items in kb.ADMIN_PANEL_CATEGORIES for k in items}
    for cat_key, cat_label, _default_item_keys in kb.ADMIN_PANEL_CATEGORIES:
        effective = kb.admin_category_item_keys(db, cat_key)
        order = db.get_custom_order(f"admin_items__{cat_key}", effective)
        items = []
        for key in order:
            label, _cb = kb._admin_item_label_and_cb(key)
            if key in kb._EXTRA_PANEL_ITEM_LABELS:
                items.append({
                    "key": key, "label": label, "has_text": False, "has_style": False,
                    "text": None, "style": None, "row_break_before": None,
                    "default_category": default_cat.get(key),
                })
                continue
            items.append({
                "key": key, "label": label, "has_text": True, "has_style": True,
                "text": db.get_setting(f"{key}_label", label),
                "style": db.get_setting(f"{key}_style", ""),
                "row_break_before": None,
                "default_category": default_cat.get(key),
            })
        groups.append(_finish_group(db, {
            "key": f"admin_items__{cat_key}", "label": f"پنل مدیریت — {cat_label}",
            "category": cat_key, "category_label": cat_label,
            "reorderable": True, "supports_row_break": False, "items": items,
        }))

    # ---------------------------------------------------------------- مسیر خرید
    bf_items = []
    for key, meta in dbmod.BUYFLOW_META.items():
        bf_items.append({
            "key": key, "label": meta["label"], "has_text": True, "has_style": True,
            "text": db.get_setting(f"{key}_text", meta["default_text"]),
            "style": db.get_setting(f"{key}_style", ""),
            "row_break_before": None,
        })
    for key, meta in dbmod.BUYFLOW_STYLE_ONLY_META.items():
        bf_items.append({
            "key": key, "label": meta["label"], "has_text": False, "has_style": True,
            "text": None,
            "style": db.get_setting(f"{key}_style", ""),
            "row_break_before": None,
        })
    groups.append({
        "key": "buyflow", "label": "مسیر خرید — متن/رنگ دکمه‌ها",
        "reorderable": False, "supports_row_break": False, "items": bf_items,
        "note": "این دکمه‌ها هرکدام جای ثابتی در مسیر خرید دارند. برای دکمه‌های انتخاب دسته‌بندی/محصول فقط رنگ قابل تغییر است (متنشان از نام دسته/محصول در دیتابیس می‌آید).",
    })
    confirm_order = db.get_custom_order("buyflow_confirm", dbmod.DEFAULT_BUYFLOW_CONFIRM_ORDER)
    groups.append({
        "key": "buyflow_confirm", "label": "مسیر خرید — ترتیب «ادامه» و «کد تخفیف»",
        "reorderable": True, "supports_row_break": False,
        "items": [{
            "key": key, "label": dbmod.BUYFLOW_META[key]["label"],
            "has_text": True, "has_style": True,
            "text": db.get_setting(f"{key}_text", dbmod.BUYFLOW_META[key]["default_text"]),
            "style": db.get_setting(f"{key}_style", ""),
            "row_break_before": None,
        } for key in confirm_order],
        "note": "ترتیب، متن و رنگ دکمه‌های «ادامه و ارسال رسید» و «وارد کردن کد تخفیف». دکمه‌ی «بازگشت» همیشه ردیف آخر ثابت می‌ماند.",
    })

    # ------------------------------------------------------------ حساب کاربری من
    acct_order = db.get_custom_order("account_hub", dbmod.DEFAULT_ACCOUNT_HUB_ORDER)
    acct_items = []
    for key in acct_order:
        meta = dbmod.ACCOUNT_HUB_META.get(key)
        if not meta:
            continue
        toggle = kb._ACCOUNT_HUB_CALLBACKS[key][0]
        acct_items.append({
            "key": key, "label": meta["label"], "has_text": True, "has_style": True,
            "text": db.get_setting(f"{key}_text", meta["default_text"]),
            "style": db.get_setting(f"{key}_style", ""),
            "row_break_before": None,
            "togglable": True, "enabled": db.get_setting(toggle, "1") == "1",
        })
    groups.append(_finish_group(db, {
        "key": "account_hub", "label": "حساب کاربری من",
        "reorderable": True, "supports_row_break": False, "items": acct_items,
    }))

    # -------------------------------------------- روش‌های پرداخت + درگاه‌های سفارشی
    gateways = db.list_custom_gateways()
    gw_by_key = {f"customgw:{g['id']}": g for g in gateways}
    valid_keys = list(dbmod.DEFAULT_PAYMENT_METHOD_ORDER) + list(gw_by_key.keys())
    pm_order = db.get_custom_order("payment_methods", valid_keys)
    pm_items = []
    for key in pm_order:
        if key in dbmod.PAYMENT_METHOD_META:
            meta = dbmod.PAYMENT_METHOD_META[key]
            pm_items.append({
                "key": key, "label": meta["label"], "has_text": True, "has_style": True,
                "text": db.get_setting(f"paymeth_{key}_text", meta["default_text"]),
                "style": db.get_setting(f"paymeth_{key}_style", ""),
                "row_break_before": None,
            })
        elif key in gw_by_key:
            gw = gw_by_key[key]
            default_text = f"💠 {gw['name']} (تایید آنی)"
            pm_items.append({
                "key": key, "label": f"درگاه سفارشی: {gw['name']}", "has_text": True, "has_style": True,
                "text": db.get_setting(f"paymeth_customgw_{gw['id']}_text", default_text),
                "style": db.get_setting(f"paymeth_customgw_{gw['id']}_style", ""),
                "row_break_before": None,
            })
    groups.append(_finish_group(db, {
        "key": "payment_methods", "label": "روش‌های پرداخت (شامل درگاه‌های سفارشی)",
        "reorderable": True, "supports_row_break": False, "items": pm_items,
        "note": "درگاه‌های سفارشی خودکار وارد این لیست می‌شوند - همین‌جا هم قابل جابجایی و رنگ‌آمیزی‌اند.",
    }))

    for scr_key, scr in kb.USER_SCREENS.items():
        order = db.get_custom_order(scr_key, [i[0] for i in scr["items"]])
        meta = {i[0]: i for i in scr["items"]}
        items = []
        for key in order:
            _k, default_text, toggle, dynamic = meta[key]
            item = {
                "key": key, "label": default_text, "has_text": not dynamic, "has_style": True,
                "text": db.get_setting(f"ubtn_{key}_text", "") or default_text,
                "style": db.get_setting(f"ubtn_{key}_style", ""),
                "row_break_before": None,
            }
            if toggle:
                item["togglable"] = True
                item["enabled"] = db.get_setting(toggle, "1") == "1"
            items.append(item)
        groups.append(_finish_group(db, {
            "key": scr_key, "label": scr["label"], "reorderable": True, "supports_row_break": False,
            "items": items, "note": scr["note"], "user_screen": True,
        }))

    categories = [{"key": c[0], "label": c[1]} for c in kb.ADMIN_PANEL_CATEGORIES]
    return {"groups": groups, "style_options": _style_options(), "admin_categories": categories}
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def _group_valid_keys(db, group: str):
    if group == "main_menu":
        return list(dbmod.MENU_BUTTON_META.keys())
    if group == "admin_categories":
        return [c[0] for c in kb.ADMIN_PANEL_CATEGORIES]
    if group.startswith("admin_items__"):
        cat_key = group.split("__", 1)[1]
        return kb.admin_category_item_keys(db, cat_key)
    if group == "buyflow":
        return list(dbmod.BUYFLOW_META.keys()) + list(dbmod.BUYFLOW_STYLE_ONLY_META.keys())
    if group == "buyflow_confirm":
        return list(dbmod.DEFAULT_BUYFLOW_CONFIRM_ORDER)
    if group in kb.USER_SCREENS:
        return [i[0] for i in kb.USER_SCREENS[group]["items"]]
    if group == "account_hub":
        return list(dbmod.ACCOUNT_HUB_META.keys())
    if group == "payment_methods":
        gateways = db.list_custom_gateways()
        return list(dbmod.DEFAULT_PAYMENT_METHOD_ORDER) + [f"customgw:{g['id']}" for g in gateways]
    return []


_TEXT_ONLY_GROUPS = set()  # دیگر گروهی که فقط ترتیب داشته باشد و متن/رنگ نداشته باشد، وجود ندارد


def update_item(db, group: str, key: str, text: str = None, style: str = None, enabled: bool = None):
    valid = _group_valid_keys(db, group)
    if key not in valid:
        raise ValueError("کلید نامعتبر برای این گروه")
    if group in _TEXT_ONLY_GROUPS:
        raise ValueError("این گروه فقط قابل جابجایی است، متن/رنگ ندارد")
    if style is not None and style not in STYLE_CHOICES:
        raise ValueError("رنگ نامعتبر")

    if group in kb.USER_SCREENS:
        meta = next(i for i in kb.USER_SCREENS[group]["items"] if i[0] == key)
        if text is not None:
            text = text.strip()
            if not text:
                raise ValueError("متن دکمه نمی‌تواند خالی باشد")
            if meta[3]:
                raise ValueError("متن این دکمه به وضعیت وابسته است و قابل تغییر نیست")
            db.set_setting(f"ubtn_{key}_text", text)
        if style is not None:
            db.set_setting(f"ubtn_{key}_style", style)
        if enabled is not None and meta[2]:
            db.set_setting(meta[2], "1" if enabled else "0")
        return

    if enabled is not None and group == "account_hub":
        db.set_setting(kb._ACCOUNT_HUB_CALLBACKS[key][0], "1" if enabled else "0")

    if text is not None:
        text = text.strip()
        if not text:
            raise ValueError("متن دکمه نمی‌تواند خالی باشد")
        if group == "main_menu":
            db.set_setting(key, text)
        elif group == "admin_categories":
            db.set_setting(f"catlbl_{key}", text)
        elif group.startswith("admin_items__"):
            db.set_setting(f"{key}_label", text)
        elif group in ("buyflow", "account_hub", "buyflow_confirm"):
            db.set_setting(f"{key}_text", text)
        elif group == "payment_methods":
            if key.startswith("customgw:"):
                gw_id = key.split(":", 1)[1]
                db.set_setting(f"paymeth_customgw_{gw_id}_text", text)
            else:
                db.set_setting(f"paymeth_{key}_text", text)
        else:
            raise ValueError("این گروه متن قابل ویرایش ندارد")

    if style is not None:
        if group == "main_menu":
            db.set_setting(f"{key}_style", style)
        elif group == "admin_categories":
            db.set_setting(f"catlbl_{key}_style", style)
        elif group.startswith("admin_items__"):
            db.set_setting(f"{key}_style", style)
        elif group in ("buyflow", "account_hub", "buyflow_confirm"):
            db.set_setting(f"{key}_style", style)
        elif group == "payment_methods":
            if key.startswith("customgw:"):
                gw_id = key.split(":", 1)[1]
                db.set_setting(f"paymeth_customgw_{gw_id}_style", style)
            else:
                db.set_setting(f"paymeth_{key}_style", style)
        else:
            raise ValueError("این گروه رنگ قابل ویرایش ندارد")


def update_order(db, group: str, order: list):
    valid = _group_valid_keys(db, group)
    if not valid:
        raise ValueError("گروه نامعتبر یا قابل جابجایی نیست")
    if group == "main_menu":
        db.set_menu_order(order)
        return
    db.set_custom_order(group, order, valid)


def update_layout(db, group: str, order: list, breaks: list):
    """ذخیره‌ی هم‌زمان ترتیب و چیدمان ردیف‌های یک گروه (ردیف تازه قبل از هر کلیدِ breaks)."""
    valid = _group_valid_keys(db, group)
    if not valid:
        raise ValueError("گروه نامعتبر یا قابل جابجایی نیست")
    if group == "main_menu":
        db.set_menu_order(order)
        db.set_menu_row_breaks(list(breaks))
        return
    db.set_custom_order(group, order, valid)
    if _is_layout_group(group):
        db.set_group_row_breaks(group, list(breaks), valid)


def set_admin_item_categories(db, overrides: dict):
    """overrides: {کلید آیتم: دسته‌ی مقصد}؛ کل نقشه‌ی انتقال‌ها را جایگزین می‌کند.
    آیتمی که دسته‌اش با پیش‌فرض کد یکی باشد ذخیره نمی‌شود."""
    defaults = {k: ck for ck, _l, items in kb.ADMIN_PANEL_CATEGORIES for k in items}
    cats = {c[0] for c in kb.ADMIN_PANEL_CATEGORIES}
    clean = {}
    for key, to_cat in (overrides or {}).items():
        if key not in defaults:
            raise ValueError("آیتم نامعتبر")
        if to_cat not in cats:
            raise ValueError("دسته‌ی مقصد نامعتبر")
        if to_cat != defaults[key]:
            clean[key] = to_cat
    db.set_admin_item_cat_overrides(clean)


def set_row_break(db, key: str, value: bool):
    """فقط برای منوی اصلی: مشخص می‌کند آیا این دکمه ردیف تازه‌ای شروع می‌کند یا
    به ردیفِ دکمه‌ی قبلی‌اش می‌چسبد."""
    if key not in dbmod.MENU_BUTTON_META:
        raise ValueError("کلید نامعتبر")
    order = db.get_menu_order()
    breaks = set(db.get_menu_row_breaks() or [])
    if value:
        breaks.add(key)
    else:
        breaks.discard(key)
    db.set_menu_row_breaks([k for k in order if k in breaks])
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
