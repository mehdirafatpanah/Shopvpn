# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from .constants import *

class PaymentsMixin:
    def create_crypto_invoice(self, txn_id: str, kind: str, ref_id: int, user_id: int,
                               amount_toman: int, source_amount_usd: float,
                               invoice_url: str = None, currency: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO crypto_invoices (txn_id, kind, ref_id, user_id, amount_toman, "
                "source_amount_usd, invoice_url, currency, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                (txn_id, kind, ref_id, user_id, amount_toman, source_amount_usd, invoice_url, currency,
                 (datetime.utcnow() + timedelta(minutes=80)).isoformat()),
            )
            return cur.lastrowid


    def get_crypto_invoice_by_txn(self, txn_id: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM crypto_invoices WHERE txn_id=?", (txn_id,)).fetchone()


    def get_crypto_invoice(self, invoice_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM crypto_invoices WHERE id=?", (invoice_id,)).fetchone()


    def update_crypto_invoice_status(self, txn_id: str, status: str, currency: str = None):
        with self._get_conn() as conn:
            if currency is not None:
                conn.execute(
                    "UPDATE crypto_invoices SET status=?, currency=?, updated_at=? WHERE txn_id=?",
                    (status, currency, datetime.utcnow().isoformat(), txn_id),
                )
            else:
                conn.execute(
                    "UPDATE crypto_invoices SET status=?, updated_at=? WHERE txn_id=?",
                    (status, datetime.utcnow().isoformat(), txn_id),
                )


    def get_pending_crypto_invoice_for_ref(self, kind: str, ref_id: int):
        """آخرین فاکتور فعال (new/pending) ثبت‌شده برای یک سفارش یا شارژ کیف پول خاص را برمی‌گرداند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM crypto_invoices WHERE kind=? AND ref_id=? AND status IN ('new','pending') "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()


    def get_crypto_invoices(self, limit: int = 50):
        """فهرست پرداخت‌های کریپتو برای پنل مدیریت؛ شامل پرداخت‌های فعال و تاریخچه."""
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM crypto_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    # -----------------------------------------------------------------------
    # لاگ وبهوک درگاه‌های پرداخت (برای دیباگ مشکلاتی مثل رد شدن امضا)
    # -----------------------------------------------------------------------


    def log_webhook_event(self, gateway: str, txn_id: str = None, verified: bool = False,
                           status: str = None, error: str = None, raw_body: str = None):
        raw_body = (raw_body or "")[:4000]  # جلوگیری از رشد بی‌رویه‌ی دیتابیس
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO payment_webhook_logs (gateway, txn_id, verified, status, error, raw_body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gateway, txn_id, 1 if verified else 0, status, error, raw_body),
            )


    def get_recent_webhook_logs(self, limit: int = 50, gateway: str = None):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if gateway:
                return conn.execute(
                    "SELECT * FROM payment_webhook_logs WHERE gateway=? ORDER BY id DESC LIMIT ?",
                    (gateway, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM payment_webhook_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def get_gateway_revenue_report(self):
        """جمع تومانی تراکنش‌های کامل‌شده به تفکیک درگاه (بر پایه‌ی جداول invoice هر درگاه).
        توجه: کارت‌به‌کارت دستی جدول invoice مجزا ندارد (تایید دستی روی سفارش انجام می‌شود)
        و در این گزارش لحاظ نشده."""
        with self._get_conn() as conn:
            crypto = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount_toman),0) s FROM crypto_invoices WHERE status='completed'"
            ).fetchone()
            aban = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount_toman),0) s FROM abangateway_invoices WHERE status IN ('paid','completed')"
            ).fetchone()
            blupal = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount_toman),0) s FROM blupal_invoices WHERE status IN ('paid','completed')"
            ).fetchone()
            noapay = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount_toman),0) s FROM noapay_invoices WHERE status='completed'"
            ).fetchone()
            extra_rows = conn.execute(
                "SELECT gateway, COUNT(*) c, COALESCE(SUM(amount_toman),0) s "
                "FROM extra_gateway_invoices WHERE status IN ('paid','completed') GROUP BY gateway"
            ).fetchall()
            custom_rows = conn.execute(
                "SELECT cg.name AS name, COUNT(*) c, COALESCE(SUM(cgi.amount_toman),0) s "
                "FROM custom_gateway_invoices cgi JOIN custom_gateways cg ON cg.id = cgi.gateway_id "
                "WHERE cgi.status='completed' GROUP BY cgi.gateway_id"
            ).fetchall()
        result = [
            {"gateway": "crypto", "label": "کریپتو (Plisio)", "count": crypto["c"], "amount_toman": crypto["s"]},
            {"gateway": "abangateway", "label": "آبان گیت‌وی", "count": aban["c"], "amount_toman": aban["s"]},
            {"gateway": "blupal", "label": "بلوپال", "count": blupal["c"], "amount_toman": blupal["s"]},
            {"gateway": "noapay", "label": "NoapayBot (استارز)", "count": noapay["c"], "amount_toman": noapay["s"]},
        ]
        for row in extra_rows:
            gw_meta = extra_gateway_registry.GATEWAYS.get(row["gateway"])
            result.append({
                "gateway": row["gateway"], "label": gw_meta["title"] if gw_meta else row["gateway"],
                "count": row["c"], "amount_toman": row["s"],
            })
        for row in custom_rows:
            result.append({
                "gateway": f"custom:{row['name']}", "label": row["name"] or "درگاه سفارشی",
                "count": row["c"], "amount_toman": row["s"],
            })
        return result


    def expire_stale_crypto_invoices(self):
        """فاکتورهایی که هنوز 'new'/'pending' مانده‌اند ولی زمان اعتبارشان (expires_at)
        گذشته را 'expired' علامت می‌زند. این‌ها هیچ‌وقت خودشان به‌روزرسانی نمی‌شدند
        چون کاربر پرداخت نکرده و وبهوکی برایشان نمی‌آید."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE crypto_invoices SET status='expired', updated_at=? "
                "WHERE status IN ('new','pending') AND expires_at IS NOT NULL AND expires_at < ?",
                (now, now),
            )


    def cancel_and_delete_crypto_invoice(self, invoice_id: int):
        """لغو دستی توسط ادمین: فاکتور بلافاصله از دیتابیس حذف می‌شود (منتظر ۷ روز نمی‌ماند)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM crypto_invoices WHERE id=?", (invoice_id,))


    def purge_old_crypto_invoices(self, days: int = 7):
        """فاکتورهای کریپتوی نهایی‌شده (تکمیل/منقضی/لغو/خطا/مغایرت) که بیش از N روز از
        آخرین به‌روزرسانی‌شان گذشته را برای همیشه حذف می‌کند، تا لیست پنل مدیریت شلوغ نماند."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM crypto_invoices WHERE status IN "
                "('completed','expired','cancelled','error','mismatch') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # فاکتورهای پرداخت کارت‌به‌کارت خودکار (آبان گیت وی)
    # -----------------------------------------------------------------------


    def create_abangateway_invoice(self, invoice_id: str, kind: str, ref_id: int, user_id: int,
                                    amount_toman: int, amount_rial: int, payable_rial: int = None,
                                    payment_url: str = None, expiry_minutes: int = 60) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO abangateway_invoices (invoice_id, kind, ref_id, user_id, amount_toman, "
                "amount_rial, payable_rial, payment_url, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                (invoice_id, kind, ref_id, user_id, amount_toman, amount_rial, payable_rial, payment_url,
                 (datetime.utcnow() + timedelta(minutes=expiry_minutes)).isoformat()),
            )
            return cur.lastrowid


    def get_abangateway_invoice_by_invoice_id(self, invoice_id: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM abangateway_invoices WHERE invoice_id=?", (invoice_id,)
            ).fetchone()


    def get_abangateway_invoice(self, id_: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM abangateway_invoices WHERE id=?", (id_,)).fetchone()


    def update_abangateway_invoice_status(self, invoice_id: str, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE abangateway_invoices SET status=?, updated_at=? WHERE invoice_id=?",
                (status, datetime.utcnow().isoformat(), invoice_id),
            )


    def get_pending_abangateway_invoice_for_ref(self, kind: str, ref_id: int):
        """آخرین فاکتور فعال (new/pending) ثبت‌شده برای یک سفارش یا شارژ کیف پول خاص را برمی‌گرداند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM abangateway_invoices WHERE kind=? AND ref_id=? AND status IN ('new','pending') "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()


    def get_abangateway_invoices(self, limit: int = 50):
        """فهرست پرداخت‌های آبان گیت وی برای پنل مدیریت؛ شامل پرداخت‌های فعال و تاریخچه."""
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM abangateway_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def expire_stale_abangateway_invoices(self):
        """فاکتورهایی که هنوز 'new'/'pending' مانده‌اند ولی زمان اعتبارشان گذشته را 'expired' علامت می‌زند."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE abangateway_invoices SET status='expired', updated_at=? "
                "WHERE status IN ('new','pending') AND expires_at IS NOT NULL AND expires_at < ?",
                (now, now),
            )


    def cancel_and_delete_abangateway_invoice(self, id_: int):
        """لغو دستی توسط ادمین: فاکتور بلافاصله از دیتابیس حذف می‌شود."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM abangateway_invoices WHERE id=?", (id_,))


    def purge_old_abangateway_invoices(self, days: int = 7):
        """فاکتورهای نهایی‌شده‌ی آبان گیت وی که بیش از N روز از آخرین به‌روزرسانی‌شان گذشته را حذف می‌کند."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM abangateway_invoices WHERE status IN "
                "('completed','expired','cancelled','error') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # فاکتورهای پرداخت کارت‌به‌کارت خودکار (بلوپال)
    # -----------------------------------------------------------------------


    def create_blupal_invoice(self, invoice_id: str, kind: str, ref_id: int, user_id: int,
                               amount_toman: int, amount_rial: int, final_amount_rial: int = None,
                               payment_url: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO blupal_invoices (invoice_id, kind, ref_id, user_id, amount_toman, "
                "amount_rial, final_amount_rial, payment_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')",
                (invoice_id, kind, ref_id, user_id, amount_toman, amount_rial, final_amount_rial, payment_url),
            )
            return cur.lastrowid


    def get_blupal_invoice_by_invoice_id(self, invoice_id: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM blupal_invoices WHERE invoice_id=?", (invoice_id,)
            ).fetchone()


    def get_blupal_invoice(self, id_: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM blupal_invoices WHERE id=?", (id_,)).fetchone()


    def update_blupal_invoice_status(self, invoice_id: str, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE blupal_invoices SET status=?, updated_at=? WHERE invoice_id=?",
                (status, datetime.utcnow().isoformat(), invoice_id),
            )


    def claim_blupal_invoice(self, invoice_id: str) -> bool:
        """تلاش اتمیک برای علامت‌گذاری یک فاکتور بلوپال به‌عنوان 'completed'، فقط
        اگر قبلاً completed نشده باشد. چون بلوپال (برخلاف آبان گیت وی) مرحله‌ی
        verify یک‌بارمصرف جدا ندارد، همین claim روی دیتابیس خودمان جلوی تحویل
        دوباره را می‌گیرد (مثلاً وقتی وب‌هوک و بررسی دستی هم‌زمان اجرا شوند)."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE blupal_invoices SET status='completed', updated_at=? "
                "WHERE invoice_id=? AND status != 'completed'",
                (datetime.utcnow().isoformat(), invoice_id),
            )
            return cur.rowcount > 0


    def get_pending_blupal_invoice_for_ref(self, kind: str, ref_id: int):
        """آخرین فاکتور فعال (new/pending) ثبت‌شده برای یک سفارش یا شارژ کیف پول خاص را برمی‌گرداند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM blupal_invoices WHERE kind=? AND ref_id=? AND status IN ('new','pending') "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()


    def get_blupal_invoices(self, limit: int = 50):
        """فهرست پرداخت‌های بلوپال برای پنل مدیریت؛ شامل پرداخت‌های فعال و تاریخچه."""
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM blupal_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def expire_stale_blupal_invoices(self, hours: int = 1):
        """فاکتورهایی که هنوز 'new'/'pending' مانده‌اند ولی بیش از یک ساعت (اعتبار
        فاکتور بلوپال طبق مستندات) از ایجادشان گذشته را 'expired' علامت می‌زند."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE blupal_invoices SET status='expired', updated_at=? "
                "WHERE status IN ('new','pending') AND created_at < ?",
                (datetime.utcnow().isoformat(), cutoff),
            )


    def cancel_and_delete_blupal_invoice(self, id_: int):
        """لغو دستی توسط ادمین: فاکتور بلافاصله از دیتابیس حذف می‌شود."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM blupal_invoices WHERE id=?", (id_,))


    def purge_old_blupal_invoices(self, days: int = 7):
        """فاکتورهای نهایی‌شده‌ی بلوپال که بیش از N روز از آخرین به‌روزرسانی‌شان گذشته را حذف می‌کند."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM blupal_invoices WHERE status IN "
                "('completed','expired','cancelled','error') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # فاکتورهای پرداخت NoapayBot (خرید استارز تلگرام)
    # -----------------------------------------------------------------------‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


    def create_noapay_invoice(self, invoice_token: str, kind: str, ref_id: int, user_id: int,
                               amount_toman: int, stars_count: int, quoted_total_toman: int = None,
                               payment_url: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO noapay_invoices (invoice_token, kind, ref_id, user_id, amount_toman, "
                "stars_count, quoted_total_toman, payment_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')",
                (invoice_token, kind, ref_id, user_id, amount_toman, stars_count, quoted_total_toman, payment_url),
            )
            return cur.lastrowid


    def get_noapay_invoice_by_token(self, invoice_token: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM noapay_invoices WHERE invoice_token=?", (invoice_token,)
            ).fetchone()


    def get_noapay_invoice(self, id_: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM noapay_invoices WHERE id=?", (id_,)).fetchone()


    def update_noapay_invoice_status(self, invoice_token: str, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE noapay_invoices SET status=?, updated_at=? WHERE invoice_token=?",
                (status, datetime.utcnow().isoformat(), invoice_token),
            )


    def get_pending_noapay_invoice_for_ref(self, kind: str, ref_id: int):
        """آخرین فاکتور فعال (new/pending/opened/paid/confirmed) ثبت‌شده برای یک سفارش
        یا شارژ کیف پول خاص را برمی‌گرداند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM noapay_invoices WHERE kind=? AND ref_id=? "
                "AND status IN ('new','pending','opened','paid','confirmed') "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()


    def get_noapay_invoices(self, limit: int = 50):
        """فهرست پرداخت‌های NoapayBot برای پنل مدیریت؛ شامل پرداخت‌های فعال و تاریخچه."""
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM noapay_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def expire_stale_noapay_invoices(self):
        """فاکتورهایی که هنوز در جریان مانده‌اند ولی بیش از ۶۰ دقیقه (اعتبار فاکتور NoapayBot)
        از ایجادشان گذشته را 'expired' علامت می‌زند."""
        cutoff = (datetime.utcnow() - timedelta(minutes=65)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE noapay_invoices SET status='expired', updated_at=? "
                "WHERE status IN ('new','pending','opened') AND created_at < ?",
                (datetime.utcnow().isoformat(), cutoff),
            )


    def cancel_and_delete_noapay_invoice(self, id_: int):
        """لغو دستی توسط ادمین: فاکتور بلافاصله از دیتابیس حذف می‌شود."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM noapay_invoices WHERE id=?", (id_,))


    def purge_old_noapay_invoices(self, days: int = 7):
        """فاکتورهای نهایی‌شده‌ی NoapayBot که بیش از N روز از آخرین به‌روزرسانی‌شان گذشته را حذف می‌کند."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM noapay_invoices WHERE status IN "
                "('completed','expired','rejected') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )


    def _extra_gateway_stats_select(self) -> str:
        cases = " ".join(
            f"WHEN '{key}' THEN '{extra_gateway_registry.GATEWAYS[key]['title']}'"
            for key in extra_gateway_registry.GATEWAY_ORDER
        )
        return (
            f"SELECT CASE gateway {cases} ELSE gateway END, status, amount_toman, created_at "
            "FROM extra_gateway_invoices WHERE kind='order'"
        )


    def create_extra_invoice(self, gateway: str, kind: str, ref_id: int, user_id: int,
                              amount_toman: int, payable_amount: int = None, remote_id: str = None,
                              order_number: str = None, payment_url: str = None, meta: dict = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO extra_gateway_invoices (gateway, kind, ref_id, user_id, amount_toman, "
                "payable_amount, remote_id, order_number, payment_url, meta, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')",
                (gateway, kind, ref_id, user_id, amount_toman, payable_amount, remote_id, order_number,
                 payment_url, json.dumps(meta or {}, ensure_ascii=False)),
            )
            return cur.lastrowid


    def get_extra_invoice(self, id_: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM extra_gateway_invoices WHERE id=?", (id_,)).fetchone()


    def get_extra_invoice_by_remote(self, gateway: str, remote_id: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM extra_gateway_invoices WHERE gateway=? AND remote_id=? ORDER BY id DESC LIMIT 1",
                (gateway, str(remote_id)),
            ).fetchone()


    def get_extra_invoice_by_order_number(self, order_number: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM extra_gateway_invoices WHERE order_number=?", (order_number,)
            ).fetchone()


    def get_pending_extra_invoice_for_ref(self, gateway: str, kind: str, ref_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM extra_gateway_invoices WHERE gateway=? AND kind=? AND ref_id=? "
                "AND status IN ('new','pending') ORDER BY id DESC LIMIT 1",
                (gateway, kind, ref_id),
            ).fetchone()


    def update_extra_invoice_status(self, id_: int, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE extra_gateway_invoices SET status=?, updated_at=? WHERE id=?",
                (status, datetime.utcnow().isoformat(), id_),
            )


    def claim_extra_invoice(self, id_: int) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE extra_gateway_invoices SET status='completed', updated_at=? "
                "WHERE id=? AND status IN ('new','pending')",
                (datetime.utcnow().isoformat(), id_),
            )
            return cur.rowcount == 1


    def release_extra_invoice(self, id_: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE extra_gateway_invoices SET status='pending', updated_at=? "
                "WHERE id=? AND status='completed'",
                (datetime.utcnow().isoformat(), id_),
            )


    def merge_extra_invoice_meta(self, id_: int, updates: dict):
        with self._get_conn() as conn:
            row = conn.execute("SELECT meta FROM extra_gateway_invoices WHERE id=?", (id_,)).fetchone()
            if not row:
                return
            try:
                meta = json.loads(row["meta"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            meta.update(updates)
            conn.execute(
                "UPDATE extra_gateway_invoices SET meta=?, updated_at=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), datetime.utcnow().isoformat(), id_),
            )


    def list_extra_invoices(self, limit: int = 50, gateway: str = None):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if gateway:
                return conn.execute(
                    "SELECT * FROM extra_gateway_invoices WHERE gateway=? ORDER BY id DESC LIMIT ?",
                    (gateway, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM extra_gateway_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def list_open_extra_invoices(self, limit: int = 100):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM extra_gateway_invoices WHERE status IN ('new','pending') "
                "AND gateway != 'tgstars' ORDER BY id LIMIT ?",
                (int(limit),),
            ).fetchall()


    def expire_stale_extra_invoices(self):
        now = datetime.utcnow()
        with self._get_conn() as conn:
            for key, meta in extra_gateway_registry.GATEWAYS.items():
                cutoff = (now - timedelta(minutes=int(meta["ttl_minutes"]))).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE extra_gateway_invoices SET status='expired', updated_at=? "
                    "WHERE gateway=? AND status IN ('new','pending') AND created_at < ?",
                    (now.isoformat(), key, cutoff),
                )


    def cancel_and_delete_extra_invoice(self, id_: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM extra_gateway_invoices WHERE id=?", (id_,))


    def purge_old_extra_invoices(self, days: int = 7):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM extra_gateway_invoices WHERE status IN ('completed','expired','cancelled') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # درگاه‌های پرداخت سفارشی/پویا (بدون کد، تعریف‌شده توسط ادمین)
    # -----------------------------------------------------------------------


    def create_custom_gateway(self, key: str, name: str, config: dict, enabled: bool = False,
                               min_amount: int = 0) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO custom_gateways (gateway_key, name, config_json, enabled, min_amount) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, name, json.dumps(config, ensure_ascii=False), 1 if enabled else 0, min_amount or 0),
            )
            return cur.lastrowid


    def update_custom_gateway(self, gateway_id: int, name: str = None, config: dict = None,
                               enabled: bool = None, min_amount: int = None):
        fields, values = [], []
        if name is not None:
            fields.append("name=?")
            values.append(name)
        if config is not None:
            fields.append("config_json=?")
            values.append(json.dumps(config, ensure_ascii=False))
        if enabled is not None:
            fields.append("enabled=?")
            values.append(1 if enabled else 0)
        if min_amount is not None:
            fields.append("min_amount=?")
            values.append(min_amount)
        if not fields:
            return
        fields.append("updated_at=?")
        values.append(datetime.utcnow().isoformat())
        values.append(gateway_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE custom_gateways SET {', '.join(fields)} WHERE id=?", values)


    def delete_custom_gateway(self, gateway_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM custom_gateways WHERE id=?", (gateway_id,))
            conn.execute("DELETE FROM custom_gateway_invoices WHERE gateway_id=?", (gateway_id,))


    def get_custom_gateway(self, gateway_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_gateways WHERE id=?", (gateway_id,)).fetchone()


    def get_custom_gateway_by_key(self, key: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_gateways WHERE gateway_key=?", (key,)).fetchone()


    def list_custom_gateways(self, only_enabled: bool = False):
        with self._get_conn() as conn:
            if only_enabled:
                return conn.execute(
                    "SELECT * FROM custom_gateways WHERE enabled=1 ORDER BY id"
                ).fetchall()
            return conn.execute("SELECT * FROM custom_gateways ORDER BY id").fetchall()

    # -----------------------------------------------------------------------
    # کاتالوگ روش‌های پرداخت (داخلی + درگاه‌های سفارشی) + حداقل مبلغ هرکدام
    # -----------------------------------------------------------------------
    # این تابع تنها منبع حقیقت برای «لیست همه‌ی روش‌های پرداخت موجود» است؛
    # همه‌جا (بات، پنل ادمین وب، مینی‌اپ) از همین‌جا خوانده می‌شود تا با
    # اضافه‌شدن یک درگاه سفارشی جدید، بدون هیچ تغییر دستی، خودش را در همه‌ی
    # لیست‌های انتخابِ محصول هم نشان دهد.


    def get_payment_methods_catalog(self, only_enabled: bool = False) -> list:
        """لیست کامل روش‌های پرداخت: آیتم‌های داخلی (کیف پول/کارت/آبان‌گیت‌وی/
        کریپتو) + همه‌ی درگاه‌های سفارشی تعریف‌شده. هر آیتم:
        {key, label, enabled, min_amount, is_custom}"""
        items = []
        for m in BUILTIN_PAYMENT_METHODS:
            enabled = True if not m["enable_setting"] else (self.get_setting(m["enable_setting"], "0") == "1")
            if only_enabled and not enabled:
                continue
            items.append({
                "key": m["key"],
                "label": m["label"],
                "enabled": enabled,
                "min_amount": int(self.get_setting(f"min_amount_{m['key']}", "0") or 0),
                "push_enabled": self.get_setting(f"push_pm_{m['key']}", "1") == "1",
                "is_custom": False,
                "is_instant": m["key"] in self._INSTANT_GATEWAY_TABLES,
                "notify_timeout_minutes": self.get_payment_method_notify_timeout(m["key"]),
            })
        for gw in self.list_custom_gateways(only_enabled=only_enabled):
            key = f"custom:{gw['gateway_key']}"
            items.append({
                "key": key,
                "label": f"💠 {gw['name']}",
                "enabled": bool(gw["enabled"]),
                "min_amount": int(gw["min_amount"] or 0) if "min_amount" in gw.keys() else 0,
                "push_enabled": self.get_setting(f"push_pm_custom:{gw['gateway_key']}", "1") == "1",
                "is_custom": True,
                "is_instant": True,
                "notify_timeout_minutes": self.get_payment_method_notify_timeout(key),
                "gateway_id": gw["id"],
            })
        return items


    def get_payment_method_min_amount(self, method_key: str) -> int:
        """حداقل مبلغ مجاز برای یک روش پرداخت (کلید داخلی یا 'custom:<key>')."""
        if method_key and method_key.startswith("custom:"):
            gw = self.get_custom_gateway_by_key(method_key.split(":", 1)[1])
            if gw and "min_amount" in gw.keys():
                return int(gw["min_amount"] or 0)
            return 0
        return int(self.get_setting(f"min_amount_{method_key}", "0") or 0)


    def set_payment_method_push_enabled(self, method_key: str, enabled: bool):
        """روشن/خاموش‌کردن پوش نوتیف ادمین برای یک روش پرداخت (داخلی یا 'custom:<key>')."""
        self.set_setting(f"push_pm_{method_key}", "1" if enabled else "0")


    def is_payment_method_push_enabled(self, method_key: str) -> bool:
        return self.get_setting(f"push_pm_{method_key}", "1") == "1"


    def get_payment_method_notify_timeout(self, method_key: str) -> int:
        """چند دقیقه بعد از ساخته‌شدن فاکتورِ یک درگاه «تایید آنی»، اگر هنوز
        new/pending مانده بود، باید یک پوش «معطل‌مانده» جدا برای ادمین برود.
        فقط برای درگاه‌های خودکار (abangateway/blupal/noapay/card_auto/custom:<key>)
        معنا دارد. صفر یعنی این قابلیت برای این روش خاموش است (پیش‌فرض)."""
        try:
            return max(0, int(self.get_setting(f"push_timeout_{method_key}", "0") or 0))
        except (TypeError, ValueError):
            return 0


    def set_payment_method_notify_timeout(self, method_key: str, minutes: int):
        self.set_setting(f"push_timeout_{method_key}", str(max(0, int(minutes or 0))))

    # جدول/شرط «هنوز در جریان» هر درگاه آنی - برای هم مخفی‌نگه‌داشتن سفارش از
    # لیست بررسی دستی (تا وقتی در جریان است) و هم تشخیص «معطل‌مانده» بعد از timeout.‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    _INSTANT_GATEWAY_TABLES = {
        "abangateway": ("abangateway_invoices", "status IN ('new','pending')"),
        "blupal": ("blupal_invoices", "status IN ('new','pending')"),
        "noapay": ("noapay_invoices", "status IN ('new','pending')"),
        "card_auto": ("card_to_card_invoices", "status='pending'"),
        **{
            _k: ("extra_gateway_invoices", f"gateway='{_k}' AND status IN ('new','pending')")
            for _k in extra_gateway_registry.GATEWAY_ORDER
        },
    }


    def list_stuck_gateway_invoices(self, method_key: str, minutes: int):
        """فاکتورهای یک درگاه آنیِ داخلی (نه سفارشی) که از ساخته‌شدنشان بیش از
        `minutes` دقیقه گذشته و هنوز در جریان مانده‌اند (تایید نشده، ولی گیرافتاده/
        ناموفق هم اعلام نشده) - نامزد پوش «معطل‌مانده»."""
        if minutes <= 0 or method_key not in self._INSTANT_GATEWAY_TABLES:
            return []
        table, in_progress_clause = self._INSTANT_GATEWAY_TABLES[method_key]
        with self._get_conn() as conn:
            return conn.execute(
                f"SELECT * FROM {table} WHERE {in_progress_clause} "
                "AND created_at <= datetime('now', ?) ORDER BY id",
                (f'-{int(minutes)} minutes',),
            ).fetchall()


    def list_stuck_custom_gateway_invoices(self, gateway_id: int, minutes: int):
        """معادل list_stuck_gateway_invoices برای یک درگاه سفارشی مشخص."""
        if minutes <= 0:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND status IN ('new','pending') "
                "AND created_at <= datetime('now', ?) ORDER BY id",
                (gateway_id, f'-{int(minutes)} minutes'),
            ).fetchall()


    def resolve_payment_method(self, kind: str, ref_id: int):
        """گیت‌وی واقعی یک سفارش/شارژ (order/wallet_topup) را از روی رکورد
        فاکتور مرتبط تشخیص می‌دهد: crypto/abangateway/blupal/custom:<key>/card_auto/card.
        None یعنی هنوز هیچ روش پرداختی برایش مشخص نشده (نه فاکتوری ساخته شده،
        نه رسیدی ارسال شده) - یعنی هنوز چیزی برای پوش‌کردن به ادمین نیست."""
        with self._get_conn() as conn:
            if conn.execute(
                "SELECT 1 FROM crypto_invoices WHERE kind=? AND ref_id=? LIMIT 1", (kind, ref_id)
            ).fetchone():
                return "crypto"
            if conn.execute(
                "SELECT 1 FROM abangateway_invoices WHERE kind=? AND ref_id=? LIMIT 1", (kind, ref_id)
            ).fetchone():
                return "abangateway"
            if conn.execute(
                "SELECT 1 FROM blupal_invoices WHERE kind=? AND ref_id=? LIMIT 1", (kind, ref_id)
            ).fetchone():
                return "blupal"
            if conn.execute(
                "SELECT 1 FROM noapay_invoices WHERE kind=? AND ref_id=? LIMIT 1", (kind, ref_id)
            ).fetchone():
                return "noapay"
            extra_row = conn.execute(
                "SELECT gateway FROM extra_gateway_invoices WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()
            if extra_row:
                return extra_row["gateway"]
            row = conn.execute(
                "SELECT cg.gateway_key FROM custom_gateway_invoices cgi "
                "JOIN custom_gateways cg ON cg.id = cgi.gateway_id "
                "WHERE cgi.kind=? AND cgi.ref_id=? LIMIT 1", (kind, ref_id)
            ).fetchone()
            if row:
                return f"custom:{row['gateway_key']}"
            if conn.execute(
                "SELECT 1 FROM card_to_card_invoices WHERE kind=? AND ref_id=? LIMIT 1", (kind, ref_id)
            ).fetchone():
                return "card_auto"
            table = "orders" if kind == "order" else "wallet_topups"
            row = conn.execute(f"SELECT receipt_file_id FROM {table} WHERE id=?", (ref_id,)).fetchone()
            if row and row["receipt_file_id"]:
                return "card"
            return None

    # -----------------------------------------------------------------------
    # محدودسازی روش پرداخت مجاز به ازای هر محصول
    # -----------------------------------------------------------------------


    def get_product_payment_methods(self, product_id: int):
        """None = همه‌ی روش‌ها برای این محصول مجازند (پیش‌فرض/بدون محدودیت).
        در غیر این صورت لیستی از کلیدهای مجاز (مثلاً ["wallet","card"])."""
        row = self.get_product(product_id)
        if not row:
            return None
        raw = row["payment_methods"] if "payment_methods" in row.keys() else None
        if not raw:
            return None
        try:
            methods = json.loads(raw)
        except Exception:
            return None
        if not methods:
            return None
        return methods


    def set_product_payment_methods(self, product_id: int, methods):
        """methods=None یا [] یعنی «همه‌ی روش‌ها مجاز» (حذف محدودیت)."""
        value = json.dumps(methods, ensure_ascii=False) if methods else None
        with self._get_conn() as conn:
            conn.execute("UPDATE products SET payment_methods=? WHERE id=?", (value, product_id))


    def get_custom_config_product_payment_methods(self, product_id: int):
        """معادل get_product_payment_methods اما برای محصولات «ساخت کانفیگ شخصی»
        (custom_config_products) - شامل حالت قیمت‌گذاری پله‌ای/پلکانی هم می‌شود.
        None = همه‌ی روش‌ها مجازند (پیش‌فرض/بدون محدودیت)."""
        row = self.get_custom_config_product(product_id)
        if not row:
            return None
        raw = row["payment_methods"] if "payment_methods" in row.keys() else None
        if not raw:
            return None
        try:
            methods = json.loads(raw)
        except Exception:
            return None
        if not methods:
            return None
        return methods


    def set_custom_config_product_payment_methods(self, product_id: int, methods):
        """methods=None یا [] یعنی «همه‌ی روش‌ها مجاز» (حذف محدودیت)."""
        value = json.dumps(methods, ensure_ascii=False) if methods else None
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_config_products SET payment_methods=? WHERE id=?", (value, product_id))


    def get_custom_config_payment_methods(self):
        """روش‌های پرداخت مجاز سراسری برای «ساخت کانفیگ شخصی» (مسیر مینی‌اپ/پنل وب و
        مسیر بدون محصول در بات). None = همه مجازند."""
        raw = self.get_setting("custom_config_payment_methods", "")
        if not raw:
            return None
        try:
            methods = json.loads(raw)
        except Exception:
            return None
        return methods or None


    def set_custom_config_payment_methods(self, methods):
        """methods=None یا [] یعنی «همه‌ی روش‌ها مجاز» (حذف محدودیت)."""
        value = json.dumps(methods, ensure_ascii=False) if methods else ""
        self.set_setting("custom_config_payment_methods", value)


    def get_effective_custom_config_payment_methods(self, custom_product_id: int = None):
        """محدودیت خودِ پلن (در صورت تنظیم) بر محدودیت سراسری اولویت دارد."""
        if custom_product_id:
            methods = self.get_custom_config_product_payment_methods(custom_product_id)
            if methods is not None:
                return methods
        return self.get_custom_config_payment_methods()


    def custom_config_allows_payment_method(self, custom_product_id, method_key: str) -> bool:
        allowed = self.get_effective_custom_config_payment_methods(custom_product_id)
        return allowed is None or method_key in allowed


    def product_allows_payment_method(self, product_id: int, method_key: str) -> bool:
        allowed = self.get_product_payment_methods(product_id)
        if allowed is None:
            return True
        return method_key in allowed

    # -----------------------------------------------------------------------
    # محدودسازی روش پرداخت مجاز برای «شارژ کیف پول» (مستقل از محصولات)
    # -----------------------------------------------------------------------


    def get_wallet_topup_payment_methods(self):
        """None = همه‌ی روش‌ها برای شارژ کیف پول مجازند (پیش‌فرض/بدون محدودیت).
        در غیر این صورت لیستی از کلیدهای مجاز - همان قراردادِ
        get_product_payment_methods، با این تفاوت که این تنظیم سراسری است
        (در جدول settings ذخیره می‌شود، نه ستون یک محصول)."""
        raw = self.get_setting("wallet_topup_payment_methods", "")
        if not raw:
            return None
        try:
            methods = json.loads(raw)
        except Exception:
            return None
        if not methods:
            return None
        return methods


    def set_wallet_topup_payment_methods(self, methods):
        """methods=None یا [] یعنی «همه‌ی روش‌ها مجاز» (حذف محدودیت)."""
        value = json.dumps(methods, ensure_ascii=False) if methods else ""
        self.set_setting("wallet_topup_payment_methods", value)


    CARD_GATE_METHODS = ("card", "card_auto")

    def get_card_gate_settings(self) -> tuple:
        """(حداقل خرید موفق, حداقل روز از استارت)؛ 0 یعنی آن شرط خاموش است."""
        def _int(key):
            try:
                return max(0, int(self.get_setting(key, "0") or 0))
            except (TypeError, ValueError):
                return 0
        return _int("card_gate_min_purchases"), _int("card_gate_min_days")

    @staticmethod
    def payment_gate_setting_keys(method_key: str) -> tuple:
        """کلید تنظیم (حداقل خرید, حداقل روز) برای یک روش پرداخت. کارت‌به‌کارت (دستی و
        خودکار) همچنان یک شرط مشترک دارد؛ بقیه‌ی درگاه‌ها هرکدام شرط جدا."""
        if method_key in ("card", "card_auto"):
            return "card_gate_min_purchases", "card_gate_min_days"
        return f"pm_gate_min_purchases_{method_key}", f"pm_gate_min_days_{method_key}"

    def get_payment_gate_settings(self, method_key: str) -> tuple:
        """(حداقل خرید موفق, حداقل روز از استارت) برای یک روش پرداخت؛ 0 یعنی خاموش."""
        def _int(key):
            try:
                return max(0, int(self.get_setting(key, "0") or 0))
            except (TypeError, ValueError):
                return 0
        purchases_key, days_key = self.payment_gate_setting_keys(method_key)
        return _int(purchases_key), _int(days_key)

    def payment_gate_passed(self, user_id: int, method_key: str) -> bool:
        """آیا این روش پرداخت برای این کاربر فعال است؟ اگر هر دو شرط خاموش باشند، یا
        کاربر ادمین باشد، یا یکی از دو شرط (خرید موفق / روز از استارت) برقرار باشد: بله."""
        if not method_key or method_key == "wallet":
            return True
        min_purchases, min_days = self.get_payment_gate_settings(method_key)
        if min_purchases <= 0 and min_days <= 0:
            return True
        if user_id is None:
            return False
        if self.is_admin(user_id):
            return True
        with self._get_conn() as conn:
            if min_purchases > 0:
                row = conn.execute(
                    "SELECT COUNT(*) c FROM orders WHERE user_id=? AND status='approved'", (user_id,)
                ).fetchone()
                if int(row["c"] or 0) >= min_purchases:
                    return True
            if min_days > 0:
                row = conn.execute(
                    "SELECT CAST(julianday('now') - julianday(joined_at) AS INTEGER) d FROM users WHERE telegram_id=?",
                    (user_id,),
                ).fetchone()
                if row and row["d"] is not None and int(row["d"]) >= min_days:
                    return True
        return False

    def card_gate_passed(self, user_id: int) -> bool:
        """سازگاری با کد قدیمی: شرط نمایش شماره کارت."""
        return self.payment_gate_passed(user_id, "card")

    def card_method_blocked_for_user(self, user_id: int, method_key: str) -> bool:
        """نام قدیمی حفظ شده؛ حالا برای همه‌ی روش‌های پرداخت (غیر از کیف پول) کار می‌کند."""
        return not self.payment_gate_passed(user_id, method_key)

    def wallet_topup_allows_payment_method(self, method_key: str) -> bool:
        allowed = self.get_wallet_topup_payment_methods()
        if allowed is None:
            return True
        return method_key in allowed


    def create_custom_gateway_invoice(self, gateway_id: int, txn_id: str, kind: str, ref_id: int,
                                       user_id: int, amount_toman: int, invoice_url: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO custom_gateway_invoices (gateway_id, txn_id, kind, ref_id, user_id, "
                "amount_toman, invoice_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'new')",
                (gateway_id, txn_id, kind, ref_id, user_id, amount_toman, invoice_url),
            )
            return cur.lastrowid


    def get_custom_gateway_invoice_by_txn(self, gateway_id: int, txn_id: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND txn_id=?",
                (gateway_id, txn_id),
            ).fetchone()


    def get_custom_gateway_invoice_by_gateway_ref(self, gateway_id: int, gateway_ref: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND gateway_ref=?",
                (gateway_id, gateway_ref),
            ).fetchone()


    def set_custom_gateway_invoice_gateway_ref(self, invoice_id: int, gateway_ref: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_gateway_invoices SET gateway_ref=?, updated_at=? WHERE id=?",
                (gateway_ref, datetime.utcnow().isoformat(), invoice_id),
            )


    def get_custom_gateway_invoice(self, invoice_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE id=?", (invoice_id,)
            ).fetchone()


    def get_pending_custom_gateway_invoice_for_ref(self, gateway_id: int, kind: str, ref_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND kind=? AND ref_id=? "
                "AND status IN ('new','pending') ORDER BY id DESC LIMIT 1",
                (gateway_id, kind, ref_id),
            ).fetchone()


    def update_custom_gateway_invoice_status(self, invoice_id: int, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_gateway_invoices SET status=?, updated_at=? WHERE id=?",
                (status, datetime.utcnow().isoformat(), invoice_id),
            )


    def list_custom_gateway_invoices(self, gateway_id: int = None, limit: int = 50):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if gateway_id:
                return conn.execute(
                    "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? ORDER BY id DESC LIMIT ?",
                    (gateway_id, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def purge_old_custom_gateway_invoices(self, days: int = 7):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM custom_gateway_invoices WHERE status IN "
                "('completed','expired','cancelled','failed') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # کارت‌به‌کارت با تایید خودکار (پیامک بانک)
    # -----------------------------------------------------------------------


    # -----------------------------------------------------------------------
    # چند شماره کارت برای کارت‌به‌کارت دستی، با درصد نمایش هر کارت
    # -----------------------------------------------------------------------

    def list_payment_cards(self, only_active: bool = False):
        with self._get_conn() as conn:
            q = "SELECT * FROM payment_cards"
            if only_active:
                q += " WHERE is_active=1 AND weight>0"
            return conn.execute(q + " ORDER BY id").fetchall()


    def get_payment_card(self, card_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM payment_cards WHERE id=?", (card_id,)).fetchone()


    def create_payment_card(self, card_number: str, holder_name: str = "", bank_name: str = "", weight: int = 1) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO payment_cards (card_number, holder_name, bank_name, weight) VALUES (?, ?, ?, ?)",
                (card_number, holder_name, bank_name, max(0, int(weight))),
            )
            return cur.lastrowid


    def update_payment_card(self, card_id: int, **fields):
        allowed = {"card_number", "holder_name", "bank_name", "weight", "is_active", "photo_file_id", "description_template"}
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        set_clause = ", ".join(f"{k}=?" for k in cols)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE payment_cards SET {set_clause} WHERE id=?", (*cols.values(), card_id))


    def toggle_payment_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE payment_cards SET is_active = 1 - is_active WHERE id=?", (card_id,))


    def delete_payment_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM payment_cards WHERE id=?", (card_id,))
            conn.execute("DELETE FROM payment_card_assignments WHERE card_id=?", (card_id,))


    def payment_card_percentages(self) -> dict:
        """{card_id: درصد نمایش} برای کارت‌های فعال (جمع = ۱۰۰)."""
        rows = self.list_payment_cards(only_active=True)
        total = sum(int(r["weight"] or 0) for r in rows)
        if not total:
            return {}
        return {r["id"]: round(int(r["weight"]) * 100 / total, 1) for r in rows}


    def _legacy_card_dict(self) -> dict:
        return {
            "id": None,
            "card_number": self.get_setting("card_number"),
            "card_holder": self.get_setting("card_holder"),
            "bank_name": "",
        }


    def get_manual_card_for_user(self, user_id=None) -> dict:
        """کارتی که باید به این کاربر نشان داده شود. اگر چند کارت تعریف شده باشد،
        به‌صورت تصادفیِ وزن‌دار (طبق درصد هر کارت) انتخاب می‌شود و برای مدتی
        (card_sticky_minutes، پیش‌فرض ۶۰ دقیقه) برای همان کاربر ثابت می‌ماند تا با
        هر بار باز کردن صفحه کارت عوض نشود و رسیدش با کارت درست بررسی شود. اگر
        هیچ کارت چندگانه‌ای تعریف نشده باشد، همان کارت تکی قدیمی (تنظیمات) برمی‌گردد."""
        import random
        rows = self.list_payment_cards(only_active=True)
        if not rows:
            return self._legacy_card_dict()
        by_id = {r["id"]: r for r in rows}
        if user_id is not None:
            try:
                ttl = max(1, int(self.get_setting("card_sticky_minutes", "60") or 60))
            except ValueError:
                ttl = 60
            with self._get_conn() as conn:
                a = conn.execute("SELECT card_id, assigned_at FROM payment_card_assignments WHERE user_id=?", (user_id,)).fetchone()
            if a and a["card_id"] in by_id:
                try:
                    if datetime.utcnow() - datetime.fromisoformat(a["assigned_at"]) < timedelta(minutes=ttl):
                        r = by_id[a["card_id"]]
                        return {"id": r["id"], "card_number": r["card_number"], "card_holder": r["holder_name"], "bank_name": r["bank_name"], "photo_file_id": r["photo_file_id"] if "photo_file_id" in r.keys() else None, "description_template": r["description_template"] if "description_template" in r.keys() else ""}
                except ValueError:
                    pass
        r = random.choices(rows, weights=[max(1, int(x["weight"] or 0)) for x in rows], k=1)[0]
        if user_id is not None:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO payment_card_assignments (user_id, card_id, assigned_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET card_id=excluded.card_id, assigned_at=excluded.assigned_at",
                    (user_id, r["id"], datetime.utcnow().isoformat()),
                )
        return {"id": r["id"], "card_number": r["card_number"], "card_holder": r["holder_name"], "bank_name": r["bank_name"], "photo_file_id": r["photo_file_id"] if "photo_file_id" in r.keys() else None, "description_template": r["description_template"] if "description_template" in r.keys() else ""}


    def create_card_to_card_card(self, card_number: str, holder_name: str = "",
                                  bank_name: str = "", sort_order: int = 0) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO card_to_card_cards (card_number, holder_name, bank_name, sort_order) "
                "VALUES (?, ?, ?, ?)",
                (card_number, holder_name, bank_name, sort_order),
            )
            return cur.lastrowid


    def get_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM card_to_card_cards WHERE id=?", (card_id,)).fetchone()


    def list_card_to_card_cards(self, only_active: bool = False):
        with self._get_conn() as conn:
            if only_active:
                return conn.execute(
                    "SELECT * FROM card_to_card_cards WHERE is_active=1 ORDER BY sort_order, id"
                ).fetchall()
            return conn.execute("SELECT * FROM card_to_card_cards ORDER BY sort_order, id").fetchall()


    def update_card_to_card_card(self, card_id: int, **fields):
        allowed = {"card_number", "holder_name", "bank_name", "sort_order", "is_active", "photo_file_id", "description_template"}
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        set_clause = ", ".join(f"{k}=?" for k in cols)
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE card_to_card_cards SET {set_clause} WHERE id=?",
                (*cols.values(), card_id),
            )


    def toggle_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_cards SET is_active = 1 - is_active WHERE id=?", (card_id,)
            )


    def delete_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM card_to_card_cards WHERE id=?", (card_id,))


    def pick_next_card_to_card_card(self):
        """کارت فعالِ کمترین‌استفاده‌شده (چرخشی) را برمی‌گرداند تا واریزی‌ها بین
        چند کارت پخش شوند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_cards WHERE is_active=1 "
                "ORDER BY (last_used_at IS NOT NULL), last_used_at, id LIMIT 1"
            ).fetchone()


    def touch_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_cards SET last_used_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), card_id),
            )


    def create_card_to_card_invoice(self, card_id: int, kind: str, ref_id: int, user_id: int,
                                     base_amount_toman: int, amount_toman: int, expires_at: str) -> int:
        """می‌تواند sqlite3.IntegrityError بزند اگر amount_toman با فاکتور در انتظار
        دیگری تداخل داشته باشد؛ فراخوان (card_to_card_payment) باید با مبلغ جدید
        دوباره تلاش کند."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO card_to_card_invoices (card_id, kind, ref_id, user_id, "
                "base_amount_toman, amount_toman, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (card_id, kind, ref_id, user_id, base_amount_toman, amount_toman, expires_at),
            )
            return cur.lastrowid


    def get_card_to_card_invoice(self, invoice_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_invoices WHERE id=?", (invoice_id,)
            ).fetchone()


    def get_pending_card_to_card_invoice_for_ref(self, kind: str, ref_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_invoices WHERE kind=? AND ref_id=? AND status='pending' "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()


    def get_pending_card_to_card_invoice_by_amount(self, amount_toman: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_invoices WHERE amount_toman=? AND status='pending' "
                "ORDER BY created_at ASC LIMIT 1",
                (amount_toman,),
            ).fetchone()


    def complete_card_to_card_invoice(self, invoice_id: int, sender: str = None,
                                       body: str = None, device_id: str = None):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_invoices SET status='completed', matched_sender=?, "
                "matched_body=?, matched_device_id=?, updated_at=? WHERE id=?",
                (sender, (body or "")[:1000], device_id, datetime.utcnow().isoformat(), invoice_id),
            )


    def expire_stale_card_to_card_invoices(self):
        """فاکتورهای در انتظاری که مهلت‌شان گذشته را به 'manual_review' می‌برد تا هم
        مبلغ رزروشده آزاد شود و هم ادمین در لیست سفارش‌های در انتظار آن‌ها را ببیند."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_invoices SET status='manual_review', updated_at=? "
                "WHERE status='pending' AND expires_at < ?",
                (datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )


    def list_card_to_card_invoices(self, status: str = None, limit: int = 50):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM card_to_card_invoices WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM card_to_card_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()


    def purge_old_card_to_card_invoices(self, days: int = 7):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM card_to_card_invoices WHERE status IN ('completed','manual_review') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # امتیاز و قرعه‌کشی شبانه F18


    def get_reseller_payment_methods(self, tier_code: str = None):
        """درگاه‌های مجاز هزینه نمایندگی. مقدار خالی یعنی همه درگاه‌های فعال."""
        key = f"reseller_payment_methods_{tier_code}" if tier_code else "reseller_payment_methods"
        raw = self.get_setting(key, "")
        if not raw:
            return None
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) and value else None
        except Exception:
            return None


    def set_reseller_payment_methods(self, tier_code: str, methods):
        methods = list(dict.fromkeys(str(x) for x in (methods or []) if x))
        self.set_setting(f"reseller_payment_methods_{tier_code}", json.dumps(methods, ensure_ascii=False))


    def get_effective_reseller_payment_methods(self, req):
        """روش‌های پرداخت مجاز یک درخواست: انتخاب ادمین برای همان درخواست، وگرنه تنظیم سطح؛ None یعنی همه فعال‌ها."""
        raw = req["payment_methods"] if "payment_methods" in req.keys() else None
        if raw:
            try:
                value = json.loads(raw)
                if isinstance(value, list) and value:
                    return value
            except Exception:
                pass
        return self.get_reseller_payment_methods(req["tier_code"] if req["tier_code"] else None)


    def approve_reseller_request_payment(self, request_id: int, admin_id: int) -> bool:
        """تایید اتمیک پرداخت؛ برای برنزی/نقره‌ای همان‌جا فعال می‌کند و برای
        طلایی/VIP وارد مرحله اطلاعات بات می‌شود."""
        with self._get_conn() as conn:
            req = conn.execute("SELECT * FROM reseller_requests WHERE id=?", (request_id,)).fetchone()
            if not req or req["status"] != "awaiting_payment_review":
                return False
            tier = conn.execute("SELECT * FROM reseller_tiers WHERE code=?", (req["tier_code"],)).fetchone() if req["tier_code"] else None
            simple = bool(tier and tier["model"] in ("commission", "discount"))
            next_status = "completed" if simple else "awaiting_bot_info"
            cur = conn.execute(
                "UPDATE reseller_requests SET status=?, reviewed_by=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='awaiting_payment_review'",
                (next_status, admin_id, request_id),
            )
            if cur.rowcount == 0:
                return False
        if req["tier_code"]:
            self.switch_agent_tier(req["user_id"], req["tier_code"])
        if simple:
            if tier["model"] == "commission":
                percent = int(req["commission_percent"] or tier["commission_min"] or 10)
                self.enable_inline_reseller(req["user_id"], percent)
                self.set_user_reseller_tier(req["user_id"], req["tier_code"], int(req["discount_percent"]) if req["tier_code"] == "silver" and req["discount_percent"] is not None else None)
            else:
                self.set_user_reseller_tier(req["user_id"], req["tier_code"], int(req["discount_percent"]) if req["tier_code"] == "silver" and req["discount_percent"] is not None else None)
        return True


    def complete_reseller_request_gateway_payment(self, request_id: int) -> bool:
        """تکمیل اتمیک پرداخت خودکار درگاه. برای مدل‌های بدون بات فوراً فعال
        می‌شود؛ برای مدل‌های بات‌دار فقط به مرحله دریافت توکن می‌رود."""
        with self._get_conn() as conn:
            req = conn.execute("SELECT * FROM reseller_requests WHERE id=?", (request_id,)).fetchone()
            if not req or req["status"] != "awaiting_payment":
                return False
            tier = conn.execute("SELECT * FROM reseller_tiers WHERE code=?", (req["tier_code"],)).fetchone() if req["tier_code"] else None
            simple = bool(tier and tier["model"] in ("commission", "discount"))
            next_status = "completed" if simple else "awaiting_bot_info"
            cur = conn.execute(
                "UPDATE reseller_requests SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='awaiting_payment'",
                (next_status, request_id),
            )
            if cur.rowcount == 0:
                return False
        if req["tier_code"]:
            self.switch_agent_tier(req["user_id"], req["tier_code"])
        if simple:
            if tier["model"] == "commission":
                percent = int(req["commission_percent"] or tier["commission_min"] or 10)
                self.enable_inline_reseller(req["user_id"], percent)
                self.set_user_reseller_tier(req["user_id"], req["tier_code"], int(req["discount_percent"]) if req["tier_code"] == "silver" and req["discount_percent"] is not None else None)
            else:
                self.set_user_reseller_tier(req["user_id"], req["tier_code"], int(req["discount_percent"]) if req["tier_code"] == "silver" and req["discount_percent"] is not None else None)
        return True

#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
