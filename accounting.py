import ast
import json
import math
import operator

CALC_MODES = ("precise", "average")
KINDS = ("panel", "personal", "multi_plan", "multi_node", "payg_gb", "payg_day", "payg_user")
SUM_KINDS = {"multi_plan", "multi_node"}
BASE = "(gb*cost_gb + days*cost_day + users*cost_user) * (1 + margin/100) + fixed_fee"

DEFAULTS = {
    "constants": {"margin": 30, "fixed_fee": 0},
    "round_to": 1000,
    "calc_mode": "precise",
    "formulas": {
        "panel": BASE,
        "personal": BASE,
        "multi_plan": BASE,
        "multi_node": BASE,
        "payg_gb": "cost_gb * (1 + margin/100)",
        "payg_day": "cost_day * (1 + margin/100)",
        "payg_user": "cost_user * (1 + margin/100)",
    },
}

BASE_VARS = ("gb", "days", "users", "panels", "nodes", "cost_gb", "cost_day", "cost_user")
RATE_FIELDS = ("gb_rate", "day_rate", "user_rate")
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCS = {"min": min, "max": max, "ceil": math.ceil, "floor": math.floor, "round": round, "abs": abs}


def _eval(node, env):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"متغیر ناشناخته: {node.id}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand, env)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("توان نامعتبر است.")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
        return _CMP[type(node.ops[0])](_eval(node.left, env), _eval(node.comparators[0], env))
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a, env) for a in node.args])
    raise ValueError("عبارت فرمول مجاز نیست.")


def evaluate(expr: str, env: dict) -> float:
    text = str(expr or "").strip()
    if not text or len(text) > 500:
        raise ValueError("فرمول خالی یا بیش از حد طولانی است.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ValueError("ساختار فرمول نامعتبر است.")
    result = float(_eval(tree, env))
    if not math.isfinite(result):
        raise ValueError("نتیجه فرمول معتبر نیست.")
    return result


def get_config(db) -> dict:
    try:
        stored = json.loads(str(db.get_setting("acct_formulas", "{}") or "{}"))
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["constants"].update({k: v for k, v in (stored.get("constants") or {}).items() if isinstance(v, (int, float))})
    cfg["formulas"].update({k: str(v) for k, v in (stored.get("formulas") or {}).items() if k in KINDS})
    if isinstance(stored.get("round_to"), int):
        cfg["round_to"] = stored["round_to"]
    if stored.get("calc_mode") in CALC_MODES:
        cfg["calc_mode"] = stored["calc_mode"]
    return cfg


def _sample_env(constants: dict) -> dict:
    env = {name: 1 for name in BASE_VARS}
    env.update(constants)
    return env


def save_config(db, body: dict) -> dict:
    constants = {}
    for name, value in (body.get("constants") or {}).items():
        name = str(name).strip()
        if not name.isidentifier() or name in BASE_VARS or name in _FUNCS or len(name) > 30:
            raise ValueError(f"نام ثابت نامعتبر است: {name}")
        try:
            constants[name] = float(value) if "." in str(value) else int(value)
        except (TypeError, ValueError):
            raise ValueError(f"مقدار ثابت «{name}» باید عدد باشد.")
    if len(constants) > 20:
        raise ValueError("حداکثر ۲۰ ثابت مجاز است.")
    formulas = {}
    for kind in KINDS:
        expr = str((body.get("formulas") or {}).get(kind, DEFAULTS["formulas"][kind])).strip()
        evaluate(expr, _sample_env(constants))
        formulas[kind] = expr
    try:
        round_to = int(body.get("round_to", 1000))
    except (TypeError, ValueError):
        raise ValueError("ضریب گرد‌کردن نامعتبر است.")
    if round_to < 1 or round_to > 10**7:
        raise ValueError("ضریب گرد‌کردن خارج از محدوده است.")
    calc_mode = str(body.get("calc_mode") or DEFAULTS["calc_mode"]).strip()
    if calc_mode not in CALC_MODES:
        raise ValueError("روش محاسبه نامعتبر است.")
    cfg = {"constants": constants, "round_to": round_to, "calc_mode": calc_mode, "formulas": formulas}
    db.set_setting("acct_formulas", json.dumps(cfg, ensure_ascii=False, separators=(",", ":")))
    return cfg


def get_node_costs(db) -> dict:
    try:
        value = json.loads(str(db.get_setting("acct_node_costs", "{}") or "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_node_costs(db, entries: list) -> dict:
    result = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        rates = {}
        for field in RATE_FIELDS:
            try:
                amount = int(item.get(field, 0) or 0)
            except (TypeError, ValueError):
                raise ValueError("هزینه باید عدد صحیح باشد.")
            if amount < 0 or amount > 10**12:
                raise ValueError("هزینه خارج از محدوده مجاز است.")
            rates[field] = amount
        result[str(int(item.get("node_id")))] = rates
    db.set_setting("acct_node_costs", json.dumps(result, separators=(",", ":")))
    return result


def panel_costs(db) -> dict:
    try:
        value = json.loads(str(db.get_setting("acct_panel_costs", "{}") or "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_panel_costs(db, panel_id: int, entries: list) -> dict:
    normalized = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        key = str(item.get("target_key", "")).strip()
        if not key or len(key) > 300:
            raise ValueError("شناسه مقصد نامعتبر است.")
        rates = {}
        for field in RATE_FIELDS:
            try:
                amount = int(item.get(field, 0) or 0)
            except (TypeError, ValueError):
                raise ValueError("هزینه باید عدد صحیح باشد.")
            if amount < 0 or amount > 10**12:
                raise ValueError("هزینه خارج از محدوده مجاز است.")
            rates[field] = amount
        normalized[key] = rates
    all_costs = panel_costs(db)
    all_costs[str(int(panel_id))] = normalized
    db.set_setting("acct_panel_costs", json.dumps(all_costs, ensure_ascii=False, separators=(",", ":")))
    return normalized


def _zero():
    return {f: 0 for f in RATE_FIELDS}


def _pick(values: list, mode: str) -> int:
    """دقیق: بالاترین هزینه (هرگز زیر قیمت تمام‌شده نمی‌فروشد)؛ میانگین: میانگین هزینه‌ها."""
    values = [int(v or 0) for v in values] or [0]
    return int(round(sum(values) / len(values))) if mode == "average" else max(values)


def _panel_rates(db, panel_id: int, targets: list, mode: str = "precise") -> dict:
    panel = panel_costs(db).get(str(int(panel_id)), {})
    if targets:
        found = [panel.get(str(t)) or panel.get("*") or _zero() for t in targets]
    elif panel.get("*") and any(panel["*"].get(f) for f in RATE_FIELDS):
        found = [panel["*"]]
    else:
        found = [v for k, v in panel.items() if k != "*" and isinstance(v, dict)] or [_zero()]
    return {f: _pick([r.get(f, 0) for r in found], mode) for f in RATE_FIELDS}


def _aggregate(rate_list: list, use_sum: bool, mode: str = "precise") -> dict:
    if not rate_list:
        return _zero()
    if use_sum:
        return {f: sum(int(r.get(f, 0) or 0) for r in rate_list) for f in RATE_FIELDS}
    return {f: _pick([r.get(f, 0) for r in rate_list], mode) for f in RATE_FIELDS}


def _round(value: float, step: int) -> int:
    return max(0, int(math.ceil(value / step) * step)) if step > 1 else max(0, int(math.ceil(value)))


def suggest(db, kind: str, panels: list, node_ids: list, gb: float, days: float, users: float) -> dict:
    if kind not in KINDS:
        raise ValueError("نوع محصول نامعتبر است.")
    cfg = get_config(db)
    node_costs = get_node_costs(db)
    rate_list = [_panel_rates(db, int(p["id"]), list(p.get("targets") or []), cfg["calc_mode"]) for p in panels]
    rate_list += [node_costs.get(str(int(n)), _zero()) for n in node_ids]
    if not rate_list:
        raise ValueError("برای پیشنهاد قیمت حداقل یک پنل یا نود لازم است.")
    costs = _aggregate(rate_list, kind in SUM_KINDS, cfg["calc_mode"])
    if not any(costs.values()):
        raise ValueError("برای مقصد انتخاب‌شده هنوز قیمت تمام‌شده‌ای در بخش حسابداری ثبت نشده است.")
    env = {"gb": float(gb or 0), "days": float(days or 0), "users": max(1.0, float(users or 1)),
           "panels": len(panels), "nodes": len(node_ids), "cost_gb": costs["gb_rate"],
           "cost_day": costs["day_rate"], "cost_user": costs["user_rate"]}
    env.update(cfg["constants"])
    raw = evaluate(cfg["formulas"][kind], env)
    return {"price": _round(raw, cfg["round_to"]), "raw": round(raw, 2), "costs": costs,
            "formula": cfg["formulas"][kind], "calc_mode": cfg["calc_mode"], "inputs": {k: env[k] for k in BASE_VARS}}


def suggest_payg_rate(db) -> dict:
    cfg = get_config(db)
    values = [int(r.get("gb_rate", 0) or 0) for panel in panel_costs(db).values() for r in panel.values() if isinstance(r, dict)]
    nonzero = [v for v in values if v]
    base_cost = _pick(nonzero, cfg["calc_mode"]) if nonzero else 0
    if not base_cost:
        raise ValueError("هنوز قیمت تمام‌شده‌ی هر گیگ در بخش حسابداری ثبت نشده است.")
    env = {name: 0 for name in BASE_VARS}
    env.update({"cost_gb": base_cost, "gb": 1, "users": 1})
    env.update(cfg["constants"])
    rate = _round(evaluate(cfg["formulas"]["payg_gb"], env), min(cfg["round_to"], 100))
    return {"rate": max(1, rate), "cost_gb": base_cost, "formula": cfg["formulas"]["payg_gb"]}


def suggest_tariff(db, panel_id: int) -> dict:
    cfg = get_config(db)
    panel = panel_costs(db).get(str(int(panel_id)), {})
    step = min(cfg["round_to"], 100)
    default = panel.get("*") or _zero()
    result = {}
    for key, rates in panel.items():
        if not isinstance(rates, dict):
            continue
        rates = rates if any(rates.get(f) for f in RATE_FIELDS) else default
        env = {name: 0 for name in BASE_VARS}
        env.update({"gb": 1, "users": 1, "panels": 1, "cost_gb": int(rates.get("gb_rate", 0) or 0),
                    "cost_day": int(rates.get("day_rate", 0) or 0), "cost_user": int(rates.get("user_rate", 0) or 0)})
        env.update(cfg["constants"])
        result[key] = {field: _round(evaluate(cfg["formulas"][kind], env), step) if env[cost] else 0
                       for field, kind, cost in (("gb_rate", "payg_gb", "cost_gb"), ("day_rate", "payg_day", "cost_day"), ("user_rate", "payg_user", "cost_user"))}
    return result


# ---------------------------------------------------------------------------
# دفتر مالی پنل وب: ثبت درآمد/هزینه، گردش مالی و گزارش‌های دوره‌ای
# ---------------------------------------------------------------------------

def suggest_service_addon(db, custom_config: dict, amount: float, addon_kind: str) -> dict:
    """محاسبه قیمت افزونه برای سرویس خریداری‌شده؛ چندپنلی/چندنودی با میانگین نرخ مقصدها."""
    if addon_kind not in ("gb", "user"):
        raise ValueError("نوع افزونه نامعتبر است.")
    cfg = get_config(db)
    rates = []
    panel_ids = []
    primary_id = custom_config.get("panel_server_id")
    if primary_id:
        panel_ids.append(int(primary_id))
    try:
        links = db.panel_links_for_config(int(custom_config.get("id")), active_only=True)
    except Exception as exc:
        raise ValueError("خواندن پنل‌های متصل به سرویس برای محاسبه حسابداری ناموفق بود.") from exc
    for link in links or []:
        pid = link.get("panel_server_id") if isinstance(link, dict) else None
        if pid:
            panel_ids.append(int(pid))
    panel_ids = list(dict.fromkeys(panel_ids))
    link_targets = {}
    for link in links or []:
        if isinstance(link, dict) and link.get("panel_server_id"):
            link_targets[int(link["panel_server_id"])] = link.get("target_config")
    panel_cost_map = panel_costs(db)
    for pid in panel_ids:
        server = db.get_panel_server(pid)
        if not server:
            continue
        target = custom_config.get("panel_target_config") if pid == int(primary_id or 0) else link_targets.get(pid)
        targets = []
        if target:
            try:
                parsed = json.loads(target) if isinstance(target, str) else target
                if isinstance(parsed, dict):
                    targets = parsed.get("targets") or parsed.get("inbounds") or parsed.get("groups") or []
                    if not targets and "value" in parsed:
                        value = parsed.get("value")
                        if isinstance(value, dict):
                            targets = [f"{proto}::{item}" for proto, items in value.items() for item in (items or [])]
                        elif isinstance(value, list):
                            targets = value
                        elif value not in (None, ""):
                            targets = [value]
                elif isinstance(parsed, list):
                    targets = parsed
            except Exception:
                targets = []
        targets = [str(x.get("value") if isinstance(x, dict) else x) for x in targets if x not in (None, "")]
        panel_entries = panel_cost_map.get(str(pid), {})
        if targets:
            missing = [t for t in targets if t not in panel_entries and "*" not in panel_entries]
            if missing:
                raise ValueError("برای همه گروه‌ها یا اینباندهای انتخاب‌شده تعرفه حسابداری ثبت نشده است.")
            selected_rates = [panel_entries.get(t) if t in panel_entries else panel_entries.get("*") for t in targets]
        elif panel_entries.get("*"):
            selected_rates = [panel_entries["*"]]
        else:
            selected_rates = [v for k, v in panel_entries.items() if k != "*" and isinstance(v, dict)] or [_zero()]
        # تعرفه مقصدهای متعدد یک پنل با هم جمع می‌شود؛ سپس بین پنل‌های مختلف میانگین گرفته می‌شود.
        rates.append({field: sum(int(r.get(field, 0) or 0) for r in selected_rates) for field in RATE_FIELDS})
    # سرویس ترکیبی VPN+SSH: نودهای متصل به استخر سهمیه نیز در میانگین قیمت لحاظ می‌شوند.
    node_ids = []
    try:
        pool = db.quota_pool_for_custom_config(int(custom_config.get("id")))
        if pool:
            usage = db.get_quota_usage(int(pool["id"]))
            if usage is None:
                raise ValueError("اطلاعات استخر سهمیه سرویس برای محاسبه حسابداری در دسترس نیست.")
            node_cost_map = get_node_costs(db)
            for service in usage.get("services", []):
                node_id = service.get("node_id")
                if node_id:
                    node_ids.append(int(node_id))
            # هر نود فقط یک بار در میانگین قیمت لحاظ شود.
            for node_id in dict.fromkeys(node_ids):
                rates.append(node_cost_map.get(str(node_id), _zero()))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("خواندن نودهای استخر سهمیه برای محاسبه حسابداری ناموفق بود.") from exc
    # تک‌پنلی: نرخ همان پنل/مجموع گروه‌های انتخاب‌شده؛ چندپنلی یا ترکیبی با نود: میانگین پنل‌ها و نودها.
    field = "gb_rate" if addon_kind == "gb" else "user_rate"
    if not rates or any(int(r.get(field, 0) or 0) <= 0 for r in rates):
        raise ValueError("تعرفه حسابداری برای همه پنل‌ها، نودها و مقصدهای این سرویس ثبت نشده است.")
    cost = int(rates[0].get(field, 0) or 0) if len(rates) == 1 else _pick([r.get(field, 0) for r in rates], "average")
    if cost <= 0:
        raise ValueError("تعرفه این افزونه برای مقصد سرویس ثبت نشده است.")
    env = {name: 0 for name in BASE_VARS}
    env.update({"gb": 1 if addon_kind == "gb" else 0,
                "users": 1 if addon_kind == "user" else 0,
                "panels": len(panel_ids), "nodes": len(set(node_ids)),
                "cost_gb": cost if addon_kind == "gb" else 0,
                "cost_day": 0, "cost_user": cost if addon_kind == "user" else 0})
    env.update(cfg["constants"])
    formula_key = "payg_gb" if addon_kind == "gb" else "payg_user"
    raw = evaluate(cfg["formulas"][formula_key], env) * float(amount)
    return {"price": _round(raw, cfg["round_to"]), "raw": round(raw, 2),
            "unit_cost": cost, "panels": len(panel_ids), "nodes": len(set(node_ids)), "formula": cfg["formulas"][formula_key],
            "calc_mode": "average" if len(rates) > 1 else "single"}


LEDGER_TYPES = ("income", "expense")
LEDGER_CATEGORIES = {
    "income": ["فروش نقدی", "درآمد متفرقه", "سایر درآمد"],
    "expense": ["هزینه سرور", "زیرساخت و شبکه", "حقوق و دستمزد", "بازاریابی", "کارمزد درگاه", "هزینه عملیاتی", "سایر هزینه"],
}


def ensure_ledger_schema(db) -> None:
    """ایجاد امن جداول دفتر مالی؛ بدون تغییر در جداول عملیاتی سفارش و پرداخت."""
    with db._get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounting_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL CHECK(entry_type IN ('income','expense')),
                title TEXT NOT NULL,
                amount INTEGER NOT NULL CHECK(amount > 0),
                category TEXT NOT NULL,
                payment_method TEXT NOT NULL DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                entry_date TEXT NOT NULL,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounting_ledger_date ON accounting_ledger(entry_date, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounting_ledger_type ON accounting_ledger(entry_type, entry_date)")


def _ledger_date(value) -> str:
    from datetime import date
    value = str(value or "").strip()
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError("تاریخ باید با فرمت YYYY-MM-DD باشد.")


def _ledger_entry_payload(data: dict) -> dict:
    data = data if isinstance(data, dict) else {}
    entry_type = str(data.get("entry_type") or "").strip().lower()
    if entry_type not in LEDGER_TYPES:
        raise ValueError("نوع سند مالی نامعتبر است.")
    title = str(data.get("title") or "").strip()
    if not title or len(title) > 180:
        raise ValueError("عنوان سند الزامی است و حداکثر ۱۸۰ کاراکتر می‌تواند باشد.")
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        raise ValueError("مبلغ باید عدد صحیح باشد.")
    if amount <= 0 or amount > 10**15:
        raise ValueError("مبلغ باید بزرگ‌تر از صفر و در محدوده مجاز باشد.")
    category = str(data.get("category") or "").strip()
    if not category or len(category) > 80:
        raise ValueError("دسته‌بندی سند الزامی است.")
    return {
        "entry_type": entry_type, "title": title, "amount": amount,
        "category": category,
        "payment_method": str(data.get("payment_method") or "").strip()[:60],
        "reference": str(data.get("reference") or "").strip()[:120],
        "description": str(data.get("description") or "").strip()[:1000],
        "entry_date": _ledger_date(data.get("entry_date")),
    }


def create_ledger_entry(db, data: dict, admin_id: int = None) -> dict:
    ensure_ledger_schema(db)
    row = _ledger_entry_payload(data)
    with db._get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO accounting_ledger
            (entry_type,title,amount,category,payment_method,reference,description,entry_date,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (row["entry_type"], row["title"], row["amount"], row["category"],
              row["payment_method"], row["reference"], row["description"],
              row["entry_date"], admin_id))
        row["id"] = cur.lastrowid
    return row


def update_ledger_entry(db, entry_id: int, data: dict) -> dict:
    ensure_ledger_schema(db)
    row = _ledger_entry_payload(data)
    with db._get_conn() as conn:
        cur = conn.execute("""
            UPDATE accounting_ledger SET entry_type=?,title=?,amount=?,category=?,payment_method=?,
            reference=?,description=?,entry_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=?
        """, (row["entry_type"], row["title"], row["amount"], row["category"],
              row["payment_method"], row["reference"], row["description"],
              row["entry_date"], int(entry_id)))
        if not cur.rowcount:
            raise KeyError("سند مالی موردنظر پیدا نشد.")
    row["id"] = int(entry_id)
    return row


def delete_ledger_entry(db, entry_id: int) -> bool:
    ensure_ledger_schema(db)
    with db._get_conn() as conn:
        cur = conn.execute("DELETE FROM accounting_ledger WHERE id=?", (int(entry_id),))
        return bool(cur.rowcount)


def list_ledger_entries(db, from_date=None, to_date=None, entry_type=None,
                        category=None, query=None, offset=0, limit=50) -> dict:
    ensure_ledger_schema(db)
    clauses, params = [], []
    if entry_type not in (None, "") and entry_type not in LEDGER_TYPES:
        raise ValueError("نوع سند مالی نامعتبر است.")
    if from_date:
        clauses.append("entry_date >= ?"); params.append(_ledger_date(from_date))
    if to_date:
        clauses.append("entry_date <= ?"); params.append(_ledger_date(to_date))
    if entry_type in LEDGER_TYPES:
        clauses.append("entry_type = ?"); params.append(entry_type)
    if category:
        clauses.append("category = ?"); params.append(str(category)[:80])
    if query:
        clauses.append("(title LIKE ? OR reference LIKE ? OR description LIKE ?)")
        q = f"%{str(query)[:100]}%"
        params.extend([q, q, q])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    offset = max(0, int(offset or 0))
    limit = max(1, min(200, int(limit or 50)))
    with db._get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM accounting_ledger" + where, params).fetchone()[0]
        rows = conn.execute("SELECT * FROM accounting_ledger" + where +
                            " ORDER BY entry_date DESC, id DESC LIMIT ? OFFSET ?",
                            params + [limit, offset]).fetchall()
    return {"items": [dict(r) for r in rows], "total": int(total), "offset": offset, "limit": limit}


def ledger_summary(db, from_date=None, to_date=None) -> dict:
    ensure_ledger_schema(db)
    clauses, params = [], []
    if from_date:
        clauses.append("entry_date >= ?"); params.append(_ledger_date(from_date))
    if to_date:
        clauses.append("entry_date <= ?"); params.append(_ledger_date(to_date))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT entry_type, COUNT(*) AS count, COALESCE(SUM(amount),0) AS total "
            "FROM accounting_ledger" + where + " GROUP BY entry_type", params
        ).fetchall()
        by_category = conn.execute(
            "SELECT entry_type, category, COUNT(*) AS count, COALESCE(SUM(amount),0) AS total "
            "FROM accounting_ledger" + where +
            " GROUP BY entry_type, category ORDER BY total DESC", params
        ).fetchall()
        monthly = conn.execute(
            "SELECT substr(entry_date,1,7) AS month, "
            "SUM(CASE WHEN entry_type='income' THEN amount ELSE 0 END) AS income, "
            "SUM(CASE WHEN entry_type='expense' THEN amount ELSE 0 END) AS expense "
            "FROM accounting_ledger" + where +
            " GROUP BY substr(entry_date,1,7) ORDER BY month DESC LIMIT 12", params
        ).fetchall()
    totals = {"income": 0, "expense": 0, "income_count": 0, "expense_count": 0}
    for r in rows:
        key = r["entry_type"]
        totals[key] = int(r["total"] or 0)
        totals[key + "_count"] = int(r["count"] or 0)
    totals["net"] = totals["income"] - totals["expense"]
    gateway_revenue = []
    try:
        gateway_revenue = [dict(r) for r in db.get_gateway_revenue_report()]
    except Exception:
        # گزارش درگاه‌ها مکمل دفتر دستی است؛ خرابی/نبود جدول درگاه نباید
        # ثبت اسناد و گزارش دفتر مالی را از دسترس خارج کند.
        gateway_revenue = []
    return {
        **totals,
        "categories": [dict(r) for r in by_category],
        "monthly": [dict(r) for r in monthly],
        "gateway_revenue_lifetime": gateway_revenue,
        "currency": "IRT",
        "available_categories": LEDGER_CATEGORIES,
    }


def export_ledger_csv(db, from_date=None, to_date=None, entry_type=None):
    import csv
    import io
    ensure_ledger_schema(db)
    clauses, params = [], []
    if from_date:
        clauses.append("entry_date >= ?"); params.append(_ledger_date(from_date))
    if to_date:
        clauses.append("entry_date <= ?"); params.append(_ledger_date(to_date))
    if entry_type in LEDGER_TYPES:
        clauses.append("entry_type = ?"); params.append(entry_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with db._get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounting_ledger" + where + " ORDER BY entry_date DESC, id DESC", params).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date", "Type", "Title", "Amount (Toman)", "Category",
                     "Payment method", "Reference", "Description"])
    for r in rows:
        writer.writerow([r["id"], r["entry_date"], r["entry_type"], r["title"], r["amount"],
                         r["category"], r["payment_method"], r["reference"], r["description"]])
    return "\ufeff" + output.getvalue()
