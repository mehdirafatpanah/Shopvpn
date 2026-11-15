# -*- coding: utf-8 -*-
"""تست منوی «/» و لیست دستورها. اجرا: python -m unittest test_bot_commands -v"""
import asyncio
import glob
import os
import re
import tempfile
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="bot_commands_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import bot_commands  # noqa: E402
from database import Database  # noqa: E402


class FakeBot:
    def __init__(self):
        self.calls = []

    async def set_my_commands(self, commands, scope=None, language_code=None):
        self.calls.append((scope, language_code, [c.command for c in commands], commands))


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def make_db():
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


class BotCommandsTest(unittest.TestCase):
    def test_names_and_descriptions_valid(self):
        names = [c[0] for c in bot_commands.USER_COMMANDS] + [c[0] for c in bot_commands.ADMIN_COMMANDS]
        self.assertEqual(len(names), len(set(names)))
        for n in names:
            self.assertRegex(n, r"^[a-z0-9_]{1,32}$")
        for c in bot_commands.USER_COMMANDS:
            self.assertTrue(3 <= len(c[1]) <= 256 and 3 <= len(c[2]) <= 256)
        for c in bot_commands.ADMIN_COMMANDS:
            self.assertTrue(3 <= len(c[1]) <= 256 and 3 <= len(c[2]) <= 256)

    def test_every_listed_command_has_a_handler(self):
        src = ""
        for f in glob.glob("*.py"):
            if f.startswith("test_") or f == "bot_commands.py":
                continue
            src += open(f, encoding="utf-8").read()
        handled = set(re.findall(r'Command\("([a-z0-9_]+)"\)', src)) | {"start"}
        # ویجت‌های پرو با Command(cmd) ثبت می‌شوند
        handled |= set(re.findall(r'_register_pro\("([a-z0-9_]+)"', src))
        listed = {c[0] for c in bot_commands.USER_COMMANDS} | {c[0] for c in bot_commands.ADMIN_COMMANDS}
        self.assertEqual(listed - handled, set())

    def test_all_handled_commands_are_listed(self):
        src = ""
        for f in glob.glob("*.py"):
            if f.startswith("test_") or f == "bot_commands.py":
                continue
            src += open(f, encoding="utf-8").read()
        handled = set(re.findall(r'Command\("([a-z0-9_]+)"\)', src)) | set(re.findall(r'_register_pro\("([a-z0-9_]+)"', src))
        listed = {c[0] for c in bot_commands.USER_COMMANDS} | {c[0] for c in bot_commands.ADMIN_COMMANDS}
        self.assertEqual(handled - listed, set())

    def test_sync_default_and_admin_scopes(self):
        db = make_db()
        with db._get_conn() as c:
            c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (50,'s','s')")
        db.add_admin(50, role="support") if "role" in db.add_admin.__code__.co_varnames else db.add_admin(50)
        bot = FakeBot()
        run(bot_commands.sync_commands(bot, db, True))
        default_fa = next(c for c in bot.calls if type(c[0]).__name__ == "BotCommandScopeDefault" and c[1] is None)
        self.assertIn("buy", default_fa[2])
        self.assertNotIn("admin", default_fa[2])          # کاربر عادی دستور مدیریتی نمی‌بیند
        owner_fa = next(c for c in bot.calls if getattr(c[0], "chat_id", None) == 1 and c[1] is None)
        self.assertIn("ai", owner_fa[2])
        self.assertIn("commands", owner_fa[2])
        sup = [c for c in bot.calls if getattr(c[0], "chat_id", None) == 50 and c[1] is None]
        if sup and not db.is_senior_admin(50):
            self.assertIn("admin", sup[0][2])
            self.assertNotIn("ai", sup[0][2])             # سطح مدیر کامل
        # مجموعه‌ی هر منو زیر سقف تلگرام
        self.assertTrue(all(len(c[2]) <= 100 for c in bot.calls))

    def test_reseller_bot_hides_main_only(self):
        bot = FakeBot()
        db = make_db()
        run(bot_commands.sync_commands(bot, db, False))
        default_fa = next(c for c in bot.calls if type(c[0]).__name__ == "BotCommandScopeDefault" and c[1] is None)
        self.assertNotIn("payg", default_fa[2])

    def test_admin_without_chat_does_not_raise(self):
        class Bad(FakeBot):
            async def set_my_commands(self, *a, **k):
                raise RuntimeError("chat not found")
        db = make_db()
        self.assertFalse(run(bot_commands.sync_admin_commands(Bad(), db, 1, True)))

    def test_list_text_levels(self):
        senior = bot_commands.build_commands_text(True, True)
        plain = bot_commands.build_commands_text(True, False)
        self.assertIn("/ai", senior)
        self.assertNotIn("/ai ", plain)
        self.assertIn("/commands", plain)
        self.assertIn("/buy", plain)
        self.assertIn("/payg", plain)
        self.assertNotIn("/payg ", bot_commands.build_commands_text(False, True))


if __name__ == "__main__":
    unittest.main()
