# -*- coding: utf-8 -*-
"""تست اعلان یک‌پیامی و فاصله‌ی قابل‌تنظیم پاکسازی سرویس‌های منقضی (cleanup_loop)."""
import asyncio
import sys
import types
import unittest
from datetime import datetime, timedelta


def _import_cleanup_loop():
    """اگر وابستگی‌های بات نصب نیست (محیط سبک تست)، فقط همان‌ها stub می‌شوند."""
    try:
        import cleanup_loop  # noqa
        return cleanup_loop
    except ImportError:
        pass
    stubbed = []
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        stubbed.append(name)
        return m
    class _Any:
        def __init__(self, *a, **k): pass
    mod("aiogram", Bot=_Any)
    mod("aiogram.types", InlineKeyboardButton=_Any, InlineKeyboardMarkup=_Any)
    mod("i18n", tr=lambda s, *a, **k: s)
    mod("notification_i18n", send_telegram=None)
    mod("report_router", report=None)
    mod("service_alerts", send_service_alert=None)
    mod("panel_providers", get_provider=None)
    import cleanup_loop
    # stub ها فقط برای import بودند؛ cleanup_loop مرجعشان را نگه می‌دارد و بقیه‌ی تست‌های همین پردازه
    # (مثلاً i18n واقعی) نباید آلوده شوند.
    for name in stubbed:
        sys.modules.pop(name, None)
    return cleanup_loop


cl = _import_cleanup_loop()


class FakeDB:
    def __init__(self, rows=None, **settings):
        self.s = dict(settings)
        self.rows = rows or []
    def get_setting(self, k, d=""):
        return self.s.get(k, d)
    def set_setting(self, k, v):
        self.s[k] = v
    def get_service_expiry_notification_candidates(self, now_iso):
        return []
    def get_cleanup_candidates(self, now_iso):
        return self.rows
    def list_admins(self):
        return []


def row(i, uid, source="test"):
    exp = (datetime.utcnow() - timedelta(days=3)).isoformat()
    return {"id": i, "user_id": uid, "source": source, "expires_at": exp,
            "cleanup_soft_disabled_at": None, "panel_server_id": 1, "username": f"u{i}", "product_id": None}


class CleanupReportTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        async def fake_report(bot, db, topic, text, *a, **k):
            self.sent.append((topic, text))
            return True
        self._orig = cl.report_router.report
        cl.report_router.report = fake_report

    def tearDown(self):
        cl.report_router.report = self._orig

    def run_once(self, db, **kw):
        return asyncio.run(cl.cleanup_once(None, db, **kw))

    def test_interval_clamped_and_due(self):
        db = FakeDB(expired_cleanup_interval_hours="0")
        self.assertEqual(cl._interval_hours(db), 1)
        db.s["expired_cleanup_interval_hours"] = "99999"
        self.assertEqual(cl._interval_hours(db), 720)
        db.s["expired_cleanup_interval_hours"] = "6"
        now = datetime.utcnow()
        self.assertTrue(cl._cleanup_due(db, now))  # هیچ اجرای قبلی
        db.s["expired_cleanup_last_run"] = (now - timedelta(hours=5)).isoformat()
        self.assertFalse(cl._cleanup_due(db, now))
        db.s["expired_cleanup_last_run"] = (now - timedelta(hours=6)).isoformat()
        self.assertTrue(cl._cleanup_due(db, now))

    def test_dry_run_single_message_to_service_topic_and_dedupe(self):
        db = FakeDB(rows=[row(2, 120962997), row(3, 5861444565)],
                    test_delete_days="1", expired_cleanup_dry_run="1")
        self.run_once(db)
        self.assertEqual(len(self.sent), 1)                      # دقیقاً یک پیام برای هر دو مورد
        topic, text = self.sent[0]
        self.assertEqual(topic, "service")
        self.assertIn("#2", text); self.assertIn("#3", text)
        self.assertIn("120962997", text); self.assertIn("5861444565", text)
        self.run_once(db)                                         # فهرست عوض نشده → پیام تکراری نه
        self.assertEqual(len(self.sent), 1)
        db.rows.append(row(4, 777))                               # فهرست تغییر کرد → دوباره اعلام
        self.run_once(db)
        self.assertEqual(len(self.sent), 2)
        db.rows.clear(); self.run_once(db)                        # خالی شد → امضا پاک
        self.assertEqual(db.s["expired_cleanup_dryrun_sig"], "")

    def test_report_toggle_off_sends_nothing(self):
        db = FakeDB(rows=[row(2, 1)], test_delete_days="1", expired_cleanup_report_enabled="0")
        self.run_once(db)
        self.assertEqual(self.sent, [])

    def test_run_cleanup_false_skips_cleanup(self):
        db = FakeDB(rows=[row(2, 1)], test_delete_days="1")
        res = self.run_once(db, run_cleanup=False)
        self.assertEqual(self.sent, [])
        self.assertEqual(res["candidates"], [])

    def test_long_list_is_capped_in_one_message(self):
        db = FakeDB(rows=[row(i, 1000 + i) for i in range(1, 61)], test_delete_days="1")
        self.run_once(db)
        self.assertEqual(len(self.sent), 1)
        text = self.sent[0][1]
        self.assertIn("و 45 مورد دیگر", text)
        self.assertLess(len(text), 4000)


if __name__ == "__main__":
    unittest.main()
