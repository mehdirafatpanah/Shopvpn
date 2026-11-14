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
