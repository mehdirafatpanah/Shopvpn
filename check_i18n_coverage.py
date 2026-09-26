import ast
import os
import re
import sys

import i18n

PERSIAN = re.compile(r"[\u0600-\u06ff]")
# tr()/api_message()/localized() take the Persian text as arg 0.
# db.get_text(key, default)/self.get_text(key, default) take it as arg 1 - the
# actual UI string is the *default*, not the lookup key. This was previously
# missed entirely, which is how ~1000 db.get_text() fallback strings in
# handlers_admin.py/handlers_user.py ended up with zero i18n coverage without
# this scanner ever flagging them.
CALLS_ARG0 = {"tr", "api_message", "localized"}
CALLS_ARG1 = {"get_text"}


def _call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def find_uncovered(root="."):
    """Return Persian literals/f-string templates (from tr()-family calls and
    db.get_text() defaults) that have no English translation."""
    known = set(i18n._TRANSLATIONS.get("en", {})) | set(i18n._PHRASE_TRANSLATIONS)
    literals, templates = {}, {}
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            if not name.endswith(".py") or name in {"i18n.py", "i18n_extra.py", "check_i18n_coverage.py"} or name.startswith("test_"):
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name_ = _call_name(node.func)
                if name_ in CALLS_ARG0 and node.args:
                    arg_index = 0
                elif name_ in CALLS_ARG1 and len(node.args) >= 2:
                    arg_index = 1
                else:
                    continue
                arg = node.args[arg_index]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    text = arg.value
                    if PERSIAN.search(text) and text not in known and not i18n.dynamic_match(text):
                        literals[text] = path
                elif isinstance(arg, ast.JoinedStr):
                    text = "".join(p.value if isinstance(p, ast.Constant) else "{x}" for p in arg.values)
                    if PERSIAN.search(text) and not i18n.dynamic_match(text.replace("{x}", "0")):
                        templates[text] = path
    return literals, templates


if __name__ == "__main__":
    literals, templates = find_uncovered(sys.argv[1] if len(sys.argv) > 1 else ".")
    for text, path in {**literals, **templates}.items():
        print(f"{path}: {text!r}")
    print(f"uncovered: {len(literals)} literals, {len(templates)} f-string templates")
    sys.exit(1 if literals or templates else 0)
