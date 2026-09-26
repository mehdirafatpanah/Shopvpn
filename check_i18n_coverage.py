import ast
import os
import re
import sys

import i18n

PERSIAN = re.compile(r"[\u0600-\u06ff]")
CALLS = {"tr", "api_message", "localized"}


def _call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def find_uncovered(root="."):
    """Return Persian tr() literals and f-string templates that have no English translation."""
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
                if not (isinstance(node, ast.Call) and _call_name(node.func) in CALLS and node.args):
                    continue
                arg = node.args[0]
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
