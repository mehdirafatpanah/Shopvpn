# -*- coding: utf-8 -*-
from .constants import *  # noqa: F403
from .constants import _wallet_tag

class OrdersMixin:
    def _charge_wallet_atomic(self, conn, user_tg_id: int, amount: int) -> bool:
        if amount <= 0:
            return True
        with _wallet_tag(conn, user_tg_id, "membership_fee", "هزینه‌ی عضویت نمایندگی"):
            cur = conn.execute(
                "UPDATE users SET referral_credit=referral_credit-? WHERE telegram_id=? AND referral_credit>=?",
                (int(amount), user_tg_id, int(amount)),
            )
        return cur.rowcount == 1


    def transfer_wallet(self, sender_id: int, receiver_id: int, amount: int) -> bool:
        amount=int(amount)
        if amount<=0 or sender_id==receiver_id:
            return False
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            sender=conn.execute("SELECT referral_credit FROM users WHERE telegram_id=?", (sender_id,)).fetchone()
            receiver=conn.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (receiver_id,)).fetchone()
            if not sender or not receiver or int(sender["referral_credit"] or 0)<amount:
                return False
            with _wallet_tag(conn, sender_id, "transfer_out", f"انتقال به کاربر {receiver_id}"):
                conn.execute("UPDATE users SET referral_credit=referral_credit-? WHERE telegram_id=?", (amount,sender_id))
            with _wallet_tag(conn, receiver_id, "transfer_in", f"دریافت از کاربر {sender_id}"):
                conn.execute("UPDATE users SET referral_credit=referral_credit+? WHERE telegram_id=?", (amount,receiver_id))
            conn.execute("INSERT INTO wallet_transfers(sender_id,receiver_id,amount) VALUES(?,?,?)", (sender_id,receiver_id,amount))
            return True


    def get_menu_order(self) -> list:
        """ترتیب کلیدهای دکمه‌های منوی اصلی را برمی‌گرداند. کلیدهای جدیدی که در
        تنظیمات ذخیره‌شده نیستند (مثلاً بعد از آپدیت پروژه) به انتهای لیست اضافه می‌شوند
        تا هیچ دکمه‌ای گم نشود."""
        import json
        raw = self.get_setting("menu_order", "")
        order = []
        if raw:
            try:
                order = [k for k in json.loads(raw) if k in DEFAULT_MENU_ORDER]
            except (ValueError, TypeError):
                order = []
        if not order:
            order = list(DEFAULT_MENU_ORDER)
        for k in DEFAULT_MENU_ORDER:
            if k not in order:
                order.append(k)
        return order


    def set_menu_order(self, order: list):
        import json
        clean = [k for k in order if k in DEFAULT_MENU_ORDER]
        for k in DEFAULT_MENU_ORDER:
            if k not in clean:
                clean.append(k)
        self.set_setting("menu_order", json.dumps(clean, ensure_ascii=False))


    def get_custom_order(self, group: str, valid_keys: list) -> list:
        import json
        raw = self.get_setting(f"btncustom_order__{group}", "")
        order = []
        if raw:
            try:
                order = [k for k in json.loads(raw) if k in valid_keys]
            except (ValueError, TypeError):
                order = []
        for k in valid_keys:
            if k not in order:
                order.append(k)
        return order


    def set_custom_order(self, group: str, order: list, valid_keys: list):
        import json
        clean = [k for k in order if k in valid_keys]
        for k in valid_keys:
            if k not in clean:
                clean.append(k)
        self.set_setting(f"btncustom_order__{group}", json.dumps(clean, ensure_ascii=False))

    # -----------------------------------------------------------------------
    # بنرهای کاروسل بالای صفحه‌ی خانه‌ی مینی‌اپ
    # -----------------------------------------------------------------------


    def get_user_full_stats(self, tg_id: int) -> dict:
        """جزئیات کامل آمار یک کاربر برای گزارش ادمین: کیف‌پول، سفارش‌ها،
        سرویس‌های فعال، رفرال و وضعیت نمایندگی."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
            if not user:
                return None
            orders = conn.execute(
                "SELECT o.status, COALESCE(o.final_price, p.price) AS price "
                "FROM orders o JOIN products p ON o.product_id=p.id WHERE o.user_id=?",
                (tg_id,),
            ).fetchall()
            approved = [o for o in orders if o["status"] == "approved"]
            pending_c = sum(1 for o in orders if o["status"] == "pending")
            rejected_c = sum(1 for o in orders if o["status"] == "rejected")
            total_spent = sum(o["price"] or 0 for o in approved)
            total_topup = conn.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM wallet_topups WHERE user_id=? AND status='approved'",
                (tg_id,),
            ).fetchone()["s"]
            active_services = conn.execute(
                "SELECT (SELECT COUNT(*) FROM configs c WHERE c.assigned_user_id=? AND c.is_used=1 "
                "AND (c.expires_at IS NULL OR c.expires_at > ?)) + "
                "(SELECT COUNT(*) FROM custom_configs cc WHERE cc.user_id=? AND cc.status='active' "
                "AND cc.source != 'test') AS c",
                (tg_id, now, tg_id),
            ).fetchone()["c"]
        referral = self.get_referral_stats(tg_id)
        return {
            "user": user,
            "status": self.get_user_status(tg_id),
            "approved_orders": len(approved),
            "pending_orders": pending_c,
            "rejected_orders": rejected_c,
            "total_spent": total_spent,
            "total_topup": total_topup,
            "active_services": active_services,
            "active_configs": active_services,
            "referral_count": referral["count"],
            "is_reseller": self.is_reseller(tg_id),
            "agent_tier": self.get_agent_tier(tg_id),
        }


    def create_order(
        self,
        user_tg_id: int,
        product_id: int,
        base_price: int,
        wallet_used: int = 0,
        discount_code_id: int = None,
        discount_amount: int = 0,
        quantity: int = 1,
        config_name: str = None,
        tier_discount_amount: int = 0,
        user_limit: int = None,
    ) -> int:
        final_price = max(base_price - wallet_used - discount_amount, 0)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (user_id, product_id, status, base_price, wallet_used, "
                "discount_code_id, discount_amount, final_price, quantity, config_name, tier_discount_amount, "
                "user_limit) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_tg_id, product_id, base_price, wallet_used, discount_code_id, discount_amount, final_price,
                 quantity, config_name, tier_discount_amount, user_limit),
            )
            order_id = cur.lastrowid
            if discount_code_id:
                conn.execute(
                    "UPDATE discount_redemptions SET order_id=? WHERE id=("
                    "SELECT MAX(id) FROM discount_redemptions WHERE code_id=? AND user_id=? AND order_id IS NULL)",
                    (order_id, discount_code_id, user_tg_id),
                )
            return order_id


    def create_renewal_order(
        self,
        user_tg_id: int,
        target_kind: str,
        target_id: int,
        mode: str,
        add_volume_gb: int,
        add_days: int,
        base_price: int,
        wallet_used: int = 0,
        user_limit: int = None,
        discount_code_id: int = None,
        discount_amount: int = 0,
    ) -> int:
        """سفارش «تمدید سرویس» از حساب کاربری - مثل is_custom_config از همان جدول
        orders با product_id=0 سنتینل استفاده می‌کند تا همه‌ی روش‌های پرداخت
        (کارت/کیف‌پول/کریپتو/آبان‌گیت‌وی/درگاه سفارشی) بدون تغییر کار کنند.
        discount_code_id/discount_amount (قابلیت ۵۱) فقط برای «تمدید کامل» پر
        می‌شوند؛ رفتارشان مثل create_order است (کسر از final_price + ثبت
        استفاده‌ی کد تخفیف روی همین سفارش)."""
        final_price = max(base_price - wallet_used - discount_amount, 0)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (user_id, product_id, status, base_price, wallet_used, final_price, "
                "quantity, is_renewal, renewal_target_kind, renewal_target_id, renewal_mode, "
                "renewal_add_volume_gb, renewal_add_days, renewal_user_limit, discount_code_id, discount_amount) "
                "VALUES (?, 0, 'pending', ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_tg_id, base_price, wallet_used, final_price, target_kind, target_id, mode, add_volume_gb, add_days,
                 user_limit, discount_code_id, discount_amount),
            )
            order_id = cur.lastrowid
            if discount_code_id:
                conn.execute(
                    "UPDATE discount_redemptions SET order_id=? WHERE id=("
                    "SELECT MAX(id) FROM discount_redemptions WHERE code_id=? AND user_id=? AND order_id IS NULL)",
                    (order_id, discount_code_id, user_tg_id),
                )
            return order_id


    def approve_renewal_order(self, order_id: int) -> bool:
        """تایید اتمیک تمدید و پرداخت یک‌باره‌ی کش‌بک؛ فقط از مبلغ پرداخت‌شده‌ی
        غیرکیف‌پول محاسبه می‌شود تا کش‌بک باعث چرخه‌ی کیف‌پول نشود."""
        now = datetime.utcnow().isoformat()
        percent = max(0, min(int(self.get_setting("renewal_cashback_percent", "0") or 0), 100))
        renewal_points = self.get_score_points("renewal")
        coin_days = self.get_coin_settings()["expiry_days"]
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row or not row["is_renewal"]:
                return False
            cur = conn.execute(
                "UPDATE orders SET status='approved', updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (now, order_id),
            )
            if cur.rowcount == 0:
                return False
            eligible = max(int(row["final_price"] or 0), 0)
            amount = (eligible * percent) // 100
            if amount > 0:
                cur2 = conn.execute(
                    "UPDATE orders SET cashback_paid=1, cashback_amount=?, cashback_type='renewal' "
                    "WHERE id=? AND cashback_paid=0", (amount, order_id)
                )
                if cur2.rowcount:
                    with _wallet_tag(conn, row["user_id"], "cashback", f"کش‌بک تمدید (سفارش #{order_id})"):
                        conn.execute(
                            "UPDATE users SET referral_credit=MAX(referral_credit + ?, MIN(referral_credit,0)) WHERE telegram_id=?",
                            (amount, row["user_id"]),
                        )
            self._grant_coins(conn, row["user_id"], renewal_points, coin_days)
            return True


    def get_order_cashback(self, order_id: int):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT cashback_paid, cashback_amount, cashback_type FROM orders WHERE id=?",
                (order_id,),
            ).fetchone()
        return dict(row) if row else {"cashback_paid": 0, "cashback_amount": 0, "cashback_type": None}


    def set_order_receipt(self, order_id: int, file_id: str, receipt_type: str = "photo"):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE orders SET receipt_file_id=?, receipt_type=? WHERE id=?",
                (file_id, receipt_type, order_id),
            )


    def set_order_admin_message(self, order_id: int, admin_chat_id: int, admin_message_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE orders SET admin_chat_id=?, admin_message_id=? WHERE id=?",
                (admin_chat_id, admin_message_id, order_id),
            )


    def get_order(self, order_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


    def get_order_survey_by_order(self, order_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM order_surveys WHERE order_id=?", (order_id,)).fetchone()


    def create_order_survey(self, order_id: int, sent_by: int = None) -> dict:
        """نظرسنجی سفارش را می‌سازد (یا اگر بی‌پاسخ مانده دوباره فعال می‌کند). خروجی: {ok, survey_id, reason}."""
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order:
                return {"ok": False, "reason": "not_found"}
            if order["status"] != "approved":
                return {"ok": False, "reason": "not_approved"}
            existing = conn.execute("SELECT * FROM order_surveys WHERE order_id=?", (order_id,)).fetchone()
            if existing:
                if existing["rating"] is not None:
                    return {"ok": False, "reason": "answered"}
                conn.execute(
                    "UPDATE order_surveys SET sent_by=?, sent_at=CURRENT_TIMESTAMP WHERE id=?", (sent_by, existing["id"])
                )
                return {"ok": True, "survey_id": existing["id"], "user_id": existing["user_id"]}
            cur = conn.execute(
                "INSERT INTO order_surveys (order_id, user_id, panel_server_id, sent_by) VALUES (?, ?, ?, ?)",
                (order_id, order["user_id"], self._order_panel_server_id(conn, order), sent_by),
            )
            return {"ok": True, "survey_id": cur.lastrowid, "user_id": order["user_id"]}


    def record_survey_rating(self, survey_id: int, user_id: int, rating: int) -> str:
        """امتیاز ۱ تا ۵ را فقط یک بار و فقط از خودِ خریدار ثبت می‌کند: ok | already | not_found | invalid."""
        if not 1 <= int(rating) <= 5:
            return "invalid"
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE order_surveys SET rating=?, answered_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND user_id=? AND rating IS NULL",
                (int(rating), survey_id, user_id),
            )
            if cur.rowcount:
                return "ok"
            row = conn.execute("SELECT rating FROM order_surveys WHERE id=? AND user_id=?", (survey_id, user_id)).fetchone()
            return "already" if row else "not_found"


    def get_survey_summary(self) -> list:
        """میانگین امتیاز به تفکیک پنل؛ ضعیف‌ترین پنل‌ها اول می‌آیند."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT s.panel_server_id AS panel_id, COALESCE(p.name, 'بانک کانفیگ / نامشخص') AS panel_name, "
                "COUNT(*) AS sent, COUNT(s.rating) AS answered, AVG(s.rating) AS avg_rating "
                "FROM order_surveys s LEFT JOIN panel_servers p ON p.id = s.panel_server_id "
                "GROUP BY s.panel_server_id ORDER BY avg_rating IS NULL, avg_rating ASC, sent DESC"
            ).fetchall()
        return [
            {"panel_id": r["panel_id"], "panel_name": r["panel_name"], "sent": r["sent"], "answered": r["answered"],
             "avg_rating": round(r["avg_rating"], 2) if r["avg_rating"] is not None else None}
            for r in rows
        ]


    def claim_order(self, order_id: int) -> bool:
        """قبل از اجرای عملیات جانبی (تمدید روی پنل، ساخت کانفیگ) صدا زده می‌شود تا از
        اجرای همزمان دو تایید برای یک سفارش (مثلاً کال‌بک تکراری درگاه) جلوگیری شود.
        اگر سفارش pending باشد آن را processing می‌کند و True برمی‌گرداند، وگرنه False."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='processing', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), order_id),
            )
            return cur.rowcount > 0


    def release_order_claim(self, order_id: int):
        """در صورت شکست عملیات جانبی بعد از claim_order، سفارش را به pending برمی‌گرداند
        تا قابل تلاش مجدد (توسط ادمین یا وب‌هوک بعدی) باشد."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE orders SET status='pending', updated_at=? WHERE id=? AND status='processing'",
                (datetime.utcnow().isoformat(), order_id),
            )


    def approve_order(self, order_id: int, config_ids) -> bool:
        """config_ids می‌تواند یک id تکی یا لیستی از id ها باشد (برای سفارش با تعداد بیشتر از ۱).
        config_id ستون سفارش برای سازگاری با کدهای قدیمی، همیشه اولین کانفیگ را نگه می‌دارد؛
        برای گرفتن همه‌ی کانفیگ‌های یک سفارش از get_order_configs استفاده کن.
        فقط اگر سفارش pending یا processing (بعد از claim_order) باشد اعمال می‌شود."""
        if isinstance(config_ids, int):
            config_ids = [config_ids]
        purchase_points = self.get_score_points("purchase")
        coin_days = self.get_coin_settings()["expiry_days"]
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', config_id=?, updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (config_ids[0], datetime.utcnow().isoformat(), order_id),
            )
            if cur.rowcount == 0:
                return False
            conn.executemany(
                "UPDATE configs SET order_id=? WHERE id=?",
                [(order_id, cid) for cid in config_ids],
            )
            self._award_order_score(conn, order_id, purchase_points, coin_days)
            return True


    def approve_order_auto(self, order_id: int) -> bool:
        """تایید سفارش محصولات is_auto_provision که کانفیگشان لحظه‌ی خرید و بدون
        استفاده از بانک کانفیگ ساخته می‌شود (بدون config_id).
        فقط اگر سفارش pending یا processing (بعد از claim_order) باشد اعمال می‌شود."""
        purchase_points = self.get_score_points("purchase")
        coin_days = self.get_coin_settings()["expiry_days"]
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (datetime.utcnow().isoformat(), order_id),
            )
            if cur.rowcount:
                self._award_order_score(conn, order_id, purchase_points, coin_days)
            return cur.rowcount > 0


    def fake_receipt_order(self, order_id: int):
        """رسید جعلی: سفارش pending را رد می‌کند، کانفیگ‌های متصل به همان سفارش را
        حذف می‌کند و کاربر را بلاک می‌کند. فقط همان سفارش هدف قرار می‌گیرد؛ سایر
        سرویس‌ها/کانفیگ‌های کاربر دست‌نخورده می‌مانند. در صورت رد سفارش، سهم کیف‌پول
        و مصرف کد تخفیف نیز مانند رد عادی سفارش برگشت داده می‌شود."""
        if not self.reject_order(order_id):
            return None
        with self._get_conn() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order:
                return None
            cur = conn.execute("DELETE FROM configs WHERE order_id=?", (order_id,))
            deleted_configs = cur.rowcount
            conn.execute("UPDATE users SET is_blocked=1 WHERE telegram_id=?", (order["user_id"],))
            return {
                "order_id": order_id,
                "user_id": order["user_id"],
                "deleted_configs": deleted_configs,
            }


    def reject_order(self, order_id: int) -> bool:
        """فقط سفارش pending را رد می‌کند (نه processing/approved)، تا با یک تایید
        هم‌زمان (claim_order) تداخل نکند. در صورت رد شدن، مبلغ کیف پول را برمی‌گرداند."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='rejected', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), order_id),
            )
            if cur.rowcount == 0:
                return False
        order = self.get_order(order_id)
        if order:
            if order["wallet_used"]:
                self.add_wallet_credit(order["user_id"], order["wallet_used"], "order_refund", f"بازگشت وجه سفارش #{order_id}")
            if order["discount_code_id"]:
                self.decrement_discount_usage(order["discount_code_id"], order_id=order_id)
        return True


    def expire_stale_discount_orders(self, timeout_minutes: int) -> list:
        """قابلیت ۸۶: تا قبل از این، کد تخفیف همان لحظه‌ی ثبت سفارش (قبل از هر
        پرداختی) رزرو/مصرف می‌شد؛ اگر کاربر روش کارت‌به‌کارت را انتخاب می‌کرد و
        بعد از دیدن شماره کارت هیچ‌وقت رسیدی نمی‌فرستاد، سفارش برای همیشه
        pending می‌ماند (هیچ‌کس - نه ادمین، نه سیستم - آن را رد نمی‌کرد) و کد
        تخفیف تا ابد گیر می‌کرد. این تابع، سفارش‌های pendingِ رهاشده‌ای که کد
        تخفیف دارند و بعد از گذشت timeout_minutes از ثبتشان هنوز نه رسیدی
        فرستاده شده نه فاکتور هیچ درگاه آنی/خودکاری برایشان باز است را
        'expired' می‌کند: مبلغ کیف‌پولِ کسرشده (اگر بود) برمی‌گردد و مصرف کد
        تخفیف آزاد می‌شود. سفارش‌هایی که final_price<=0 بوده‌اند (پرداخت کامل
        از کیف‌پول/کد) از قبل هنگام ثبت خودکار 'approved' شده‌اند، پس اصلاً
        pending نمی‌مانند و اینجا هم دیده نمی‌شوند. شناسه‌ی سفارش‌های
        expired‌شده را برمی‌گرداند (برای اطلاع‌رسانی به کاربر توسط صدازننده)."""
        cutoff = (datetime.utcnow() - timedelta(minutes=max(timeout_minutes, 1))).isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT o.id FROM orders o "
                "WHERE o.status='pending' AND o.discount_code_id IS NOT NULL "
                "AND o.receipt_file_id IS NULL AND o.created_at<=? "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='order' AND ci.ref_id=o.id) "
                "AND NOT EXISTS (SELECT 1 FROM abangateway_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM blupal_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM noapay_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM extra_gateway_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM custom_gateway_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM card_to_card_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status='pending')",
                (cutoff,),
            ).fetchall()
            order_ids = [r["id"] for r in rows]
            if order_ids:
                now = datetime.utcnow().isoformat()
                conn.executemany(
                    "UPDATE orders SET status='expired', updated_at=? WHERE id=? AND status='pending'",
                    [(now, oid) for oid in order_ids],
                )
        for order_id in order_ids:
            order = self.get_order(order_id)
            if not order:
                continue
            if order["wallet_used"]:
                self.add_wallet_credit(
                    order["user_id"], order["wallet_used"], "order_refund",
                    f"بازگشت وجه سفارش منقضی‌شده #{order_id}",
                )
            if order["discount_code_id"]:
                self.decrement_discount_usage(order["discount_code_id"], order_id=order_id)
        return order_ids


    def search_orders(self, status: str = "pending", query: str = "", product_id: int | None = None, date_from: str = "", date_to: str = "", limit: int = 500):
        """فیلتر سفارشات پنل مدیریت بر اساس وضعیت، کاربر/شناسه سفارش، محصول و بازه تاریخ."""
        where = ["o.status=?"]
        params = [status]
        if query:
            q = str(query).strip()
            if q.isdigit():
                where.append("(o.id=? OR o.user_id=? OR u.username LIKE ? OR u.first_name LIKE ? OR u.last_name LIKE ?)")
                params.extend([int(q), int(q), f"%{q}%", f"%{q}%", f"%{q}%"])
            else:
                where.append("(u.username LIKE ? OR u.first_name LIKE ? OR u.last_name LIKE ? OR CAST(o.user_id AS TEXT) LIKE ?)")
                params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
        if product_id is not None:
            where.append("o.product_id=?")
            params.append(product_id)
        if date_from:
            where.append("o.created_at>=?")
            params.append(date_from.strip() + " 00:00:00")
        if date_to:
            where.append("o.created_at<=?")
            params.append(date_to.strip() + " 23:59:59")
        sql = ("SELECT o.* FROM orders o LEFT JOIN users u ON u.tg_id=o.user_id "
               "WHERE " + " AND ".join(where) + " ORDER BY o.id DESC LIMIT ?")
        params.append(max(1, min(int(limit), 1000)))
        with self._get_conn() as conn:
            return conn.execute(sql, tuple(params)).fetchall()


    def get_orders_by_status(self, status: str, limit: int = 200):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
            ).fetchall()


    def get_pending_orders(self):
        """سفارش‌های نیازمند بررسی دستی؛ سفارش‌هایی که برایشان فاکتور کریپتو ساخته شده‌اند
        اینجا نمی‌آیند، و همین‌طور سفارش‌هایی که یک درگاه «تایید آنی» (آبان‌گیت‌وی/بلوپال/
        نوپی/درگاه سفارشی/کارت‌به‌کارت خودکار) برایشان فاکتور ساخته ولی هنوز new/pending
        است - چون این‌ها منتظر تاییدِ خودکار (وب‌هوک/پیامک) هستند، نه بررسی ادمین؛ همین که
        فاکتور به حالت گیرافتاده/ناموفق (هر چیزی جز new/pending) برسد دوباره اینجا دیده
        می‌شوند تا ادمین متوجه‌ی معطل‌ماندنشان بشود."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT o.* FROM orders o "
                "WHERE o.status='pending' "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='order' AND ci.ref_id=o.id) "
                "AND NOT EXISTS (SELECT 1 FROM abangateway_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM blupal_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM noapay_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM extra_gateway_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM custom_gateway_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM card_to_card_invoices gi WHERE gi.kind='order' AND gi.ref_id=o.id AND gi.status='pending') "
                "ORDER BY o.id"
            ).fetchall()


    def get_latest_pending_order_awaiting_receipt(self, user_tg_id: int):
        """آخرین سفارش (عادی یا کانفیگ شخصی) این کاربر که هنوز pending است و رسیدی
        برایش ثبت نشده - برای fallback بازیابی رسیدهایی که به‌خاطر گم‌شدن FSM state
        (مثلاً ری‌استارت بات) به هندلر state-دار اصلی نرسیده‌اند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE user_id=? AND status='pending' "
                "AND receipt_file_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='order' AND ci.ref_id=orders.id) "
                "ORDER BY id DESC LIMIT 1",
                (user_tg_id,),
            ).fetchone()


    def get_user_orders(self, user_tg_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE user_id=? AND (user_deleted IS NULL OR user_deleted=0) "
                "ORDER BY id DESC",
                (user_tg_id,),
            ).fetchall()


    def get_stats(self):
        with self._get_conn() as conn:
            users_c = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            pending_c = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
            approved_c = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='approved'").fetchone()["c"]
            rejected_c = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='rejected'").fetchone()["c"]
            revenue = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(o.final_price, p.price)),0) s FROM orders o "
                "JOIN products p ON o.product_id=p.id WHERE o.status='approved'"
            ).fetchone()["s"]
            return {
                "users": users_c,
                "pending": pending_c,
                "approved": approved_c,
                "rejected": rejected_c,
                "revenue": revenue,
            }


    def get_user_stats_breakdown(self) -> dict:
        """آمار دقیق کاربران ربات: کل، غیرفعال، خریدار، مسدود، تست‌کننده، نماینده.
        خریدار: کاربری که حداقل یک سفارش تاییدشده دارد.
        غیرفعال: مکمل خریدار (هیچ‌وقت سفارش تاییدشده‌ای نداشته).
        تست‌کننده: کاربری که حداقل یک کانفیگ تست (custom_configs.source='test') گرفته.
        نماینده: is_reseller=1 یا reseller_tier ست‌شده.
        این دسته‌ها مستقل‌اند و می‌توانند هم‌پوشانی داشته باشند (مثلاً نماینده‌ای که خریدار هم هست)."""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            buyers = conn.execute(
                "SELECT COUNT(DISTINCT user_id) c FROM orders WHERE status='approved'"
            ).fetchone()["c"]
            blocked = conn.execute("SELECT COUNT(*) c FROM users WHERE is_blocked=1").fetchone()["c"]
            testers = conn.execute(
                "SELECT COUNT(DISTINCT user_id) c FROM custom_configs WHERE source='test'"
            ).fetchone()["c"]
            resellers = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE is_reseller=1 OR reseller_tier IS NOT NULL"
            ).fetchone()["c"]
        return {
            "total": total,
            "inactive": max(total - buyers, 0),
            "buyers": buyers,
            "blocked": blocked,
            "testers": testers,
            "resellers": resellers,
        }


    def get_sales_stats(self, start_date: str = None, end_date: str = None):
        """آمار فروش کامل برای یک بازه‌ی زمانی دلخواه.
        start_date/end_date به فرمت 'YYYY-MM-DD' (شامل خود آن روزها).
        اگر داده نشوند، پیش‌فرض ۱۴ روز اخیر است.
        شامل: کارت‌های خلاصه، مقایسه با بازه‌ی هم‌طول قبلی، نرخ تبدیل، میانگین سبد خرید،
        روند روزانه، تفکیک درآمد بر اساس دسته‌بندی، سهم رفرال در مقابل خرید مستقیم،
        و پرفروش‌ترین محصولات (همه محدود به همان بازه)."""
        with self._get_conn() as conn:
            if not end_date:
                end_date = conn.execute("SELECT date('now') d").fetchone()["d"]
            if not start_date:
                start_date = conn.execute("SELECT date(?, '-13 days') d", (end_date,)).fetchone()["d"]

            length_days = conn.execute(
                "SELECT CAST(julianday(?) - julianday(?) AS INTEGER) + 1 d", (end_date, start_date)
            ).fetchone()["d"]
            if length_days < 1:
                length_days = 1

            prev_end = conn.execute("SELECT date(?, '-1 day') d", (start_date,)).fetchone()["d"]
            prev_start = conn.execute(
                "SELECT date(?, ?) d", (prev_end, f"-{length_days - 1} days")
            ).fetchone()["d"]

            def _period_totals(s, e):
                row = conn.execute(
                    "SELECT "
                    "SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) approved_c, "
                    "SUM(CASE WHEN o.status='pending' THEN 1 ELSE 0 END) pending_c, "
                    "SUM(CASE WHEN o.status='rejected' THEN 1 ELSE 0 END) rejected_c, "
                    "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue "
                    "FROM orders o JOIN products p ON o.product_id=p.id "
                    "WHERE date(o.created_at) BETWEEN ? AND ?",
                    (s, e),
                ).fetchone()
                approved = row["approved_c"] or 0
                pending = row["pending_c"] or 0
                rejected = row["rejected_c"] or 0
                revenue = row["revenue"] or 0
                decided = approved + rejected
                conversion = round(approved / decided * 100, 1) if decided else 0.0
                aov = round(revenue / approved) if approved else 0
                return {
                    "approved": approved, "pending": pending, "rejected": rejected,
                    "revenue": revenue, "conversion_rate": conversion, "aov": aov,
                }

            current = _period_totals(start_date, end_date)
            previous = _period_totals(prev_start, prev_end)

            def _pct_change(cur, prev):
                if prev == 0:
                    return None if cur == 0 else 100.0
                return round((cur - prev) / prev * 100, 1)

            current["revenue_change_pct"] = _pct_change(current["revenue"], previous["revenue"])
            current["orders_change_pct"] = _pct_change(current["approved"], previous["approved"])
            current["prev_revenue"] = previous["revenue"]
            current["prev_approved"] = previous["approved"]

            new_users = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE date(joined_at) BETWEEN ? AND ?", (start_date, end_date)
            ).fetchone()["c"]
            current["new_users"] = new_users

            daily_rows = conn.execute(
                "SELECT date(o.created_at) d, "
                "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue, "
                "SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) orders "
                "FROM orders o JOIN products p ON o.product_id=p.id "
                "WHERE date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY date(o.created_at)",
                (start_date, end_date),
            ).fetchall()
            daily_map = {r["d"]: {"revenue": r["revenue"], "orders": r["orders"]} for r in daily_rows}
            daily_series = []
            for i in range(length_days):
                d = conn.execute("SELECT date(?, ?) d", (start_date, f"+{i} days")).fetchone()["d"]
                entry = daily_map.get(d, {"revenue": 0, "orders": 0})
                daily_series.append({"date": d, "revenue": entry["revenue"], "orders": entry["orders"]})

            category_rows = conn.execute(
                "SELECT c.name name, COUNT(*) orders, COALESCE(SUM(COALESCE(o.final_price, p.price)),0) revenue "
                "FROM orders o JOIN products p ON o.product_id=p.id JOIN categories c ON p.category_id=c.id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY c.id ORDER BY revenue DESC",
                (start_date, end_date),
            ).fetchall()
            category_breakdown = [
                {"name": r["name"], "orders": r["orders"], "revenue": r["revenue"]} for r in category_rows
            ]

            referral_row = conn.execute(
                "SELECT "
                "COALESCE(SUM(CASE WHEN u.referred_by IS NOT NULL THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) referral_revenue, "
                "COALESCE(SUM(CASE WHEN u.referred_by IS NULL THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) direct_revenue "
                "FROM orders o JOIN products p ON o.product_id=p.id JOIN users u ON o.user_id=u.telegram_id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()
            current["referral_revenue"] = referral_row["referral_revenue"] or 0
            current["direct_revenue"] = referral_row["direct_revenue"] or 0

            top_products = conn.execute(
                "SELECT p.name name, COUNT(*) c, COALESCE(SUM(COALESCE(o.final_price, p.price)),0) s "
                "FROM orders o JOIN products p ON o.product_id=p.id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY p.id ORDER BY c DESC LIMIT 5",
                (start_date, end_date),
            ).fetchall()

            total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            # کارت «کانفیگ‌های فعال» در داشبورد: قبلاً فقط جدول configs (انبار
            # کانفیگ ثابت) را می‌شمرد و custom_configs (کانفیگ‌های ساخته‌شده
            # مستقیم روی پنل‌های Marzban/3X-UI/Hiddify/... که امروز اکثر
            # فروشگاه‌ها فقط از همین روش استفاده می‌کنند) را نادیده می‌گرفت؛
            # به همین دلیل همیشه صفر یا عددی خیلی کمتر از واقعیت نشان می‌داد.
            active_configs_c = conn.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM configs WHERE is_used=1) + "
                "(SELECT COUNT(*) FROM custom_configs WHERE status='active' AND source != 'test') AS c"
            ).fetchone()["c"]
            open_tickets_c = conn.execute(
                "SELECT COUNT(*) c FROM tickets WHERE status IN ('open','answered')"
            ).fetchone()["c"]
            wallet_total = conn.execute("SELECT COALESCE(SUM(MAX(referral_credit,0)),0) s FROM users").fetchone()["s"]

            current.update({
                "start_date": start_date,
                "end_date": end_date,
                "total_users": total_users,
                "active_configs": active_configs_c,
                "open_tickets": open_tickets_c,
                "wallet_total": wallet_total,
                "daily_series": daily_series,
                "category_breakdown": category_breakdown,
                "top_products": [{"name": r["name"], "orders": r["c"], "revenue": r["s"]} for r in top_products],
            })
            return current


    def get_full_stats(self, start_date: str = None, end_date: str = None) -> dict:
        """آمار کامل: get_sales_stats به‌علاوه‌ی موجودی انبار، تیکت‌ها و مشتریان تکراری.
        منبع واحد برای بات، مینی‌اپ و پنل وب تا هر سه دقیقاً یک عدد نشان دهند."""
        stats = self.get_sales_stats(start_date, end_date)
        s, e = stats["start_date"], stats["end_date"]
        threshold = int(self.get_setting("low_stock_threshold", "3") or 3)
        with self._get_conn() as conn:
            inventory_rows = conn.execute(
                "SELECT p.id, p.name name, "
                "SUM(CASE WHEN c.is_used=0 THEN 1 ELSE 0 END) unused, "
                "SUM(CASE WHEN c.is_used=1 THEN 1 ELSE 0 END) used "
                "FROM products p LEFT JOIN configs c ON c.product_id=p.id "
                "WHERE p.is_active=1 GROUP BY p.id ORDER BY p.name"
            ).fetchall()
            inventory = [
                {
                    "product_id": r["id"], "name": r["name"],
                    "unused": r["unused"] or 0, "used": r["used"] or 0,
                    "low_stock": (r["unused"] or 0) <= threshold,
                }
                for r in inventory_rows
            ]
            low_stock_products = [i for i in inventory if i["low_stock"]]

            ticket_row = conn.execute(
                "SELECT COUNT(*) c, SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) open_c, "
                "SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) closed_c "
                "FROM tickets WHERE date(created_at) BETWEEN ? AND ?", (s, e),
            ).fetchone()
            first_response_rows = conn.execute(
                "SELECT t.created_at t_created, MIN(m.created_at) first_admin_reply "
                "FROM tickets t JOIN ticket_messages m ON m.ticket_id=t.id AND m.sender='admin' "
                "WHERE date(t.created_at) BETWEEN ? AND ? GROUP BY t.id", (s, e),
            ).fetchall()
            response_minutes = [
                (conn.execute("SELECT (julianday(?) - julianday(?)) * 1440 d",
                               (r["first_admin_reply"], r["t_created"])).fetchone()["d"])
                for r in first_response_rows
            ]
            avg_response_minutes = round(sum(response_minutes) / len(response_minutes), 1) if response_minutes else None

            repeat_customers = conn.execute(
                "SELECT COUNT(*) c FROM (SELECT user_id FROM orders WHERE status='approved' "
                "GROUP BY user_id HAVING COUNT(*) > 1)"
            ).fetchone()["c"]
            total_customers = conn.execute(
                "SELECT COUNT(DISTINCT user_id) c FROM orders WHERE status='approved'"
            ).fetchone()["c"]
            repeat_rate = round(repeat_customers / total_customers * 100, 1) if total_customers else 0.0

            discount_row = conn.execute(
                "SELECT COALESCE(SUM(discount_amount),0) total, COUNT(*) c FROM orders "
                "WHERE status='approved' AND discount_code_id IS NOT NULL AND date(created_at) BETWEEN ? AND ?",
                (s, e),
            ).fetchone()

        stats.update({
            "inventory": inventory,
            "low_stock_products": low_stock_products,
            "tickets_created": ticket_row["c"] or 0,
            "tickets_open": ticket_row["open_c"] or 0,
            "tickets_closed": ticket_row["closed_c"] or 0,
            "avg_ticket_response_minutes": avg_response_minutes,
            "repeat_customers": repeat_customers,
            "total_customers": total_customers,
            "repeat_customer_rate": repeat_rate,
            "total_discount_given": discount_row["total"] or 0,
            "discount_orders_count": discount_row["c"] or 0,
        })
        return stats


    def get_advanced_stats(self, start_date: str = None, end_date: str = None,
                            granularity: str = "day", churn_days: int = 60) -> dict:
        """آمار پیشرفته‌ی فروشگاه: مکمل get_full_stats با چهار بخشی که آن‌جا نبود -
        روند فروش با تفکیک بازه (روزانه/هفتگی/ماهانه)، عملکرد و نرخ موفقیت هر
        درگاه پرداخت، عملکرد منابع ورودی/کمپین و نمایندگان داخلی، و قیف تبدیل
        کاربر به‌همراه مشتریان بازگشتی/ریزش‌کرده و نقشه‌ی ساعتی فعالیت.
        همین یک تابع منبع واحد هر سه رابط (بات، مینی‌اپ، پنل وب) است - دقیقاً
        مثل get_full_stats - تا هرگز عدد متفاوتی در جاهای مختلف نشان داده نشود."""
        with self._get_conn() as conn:
            if not end_date:
                end_date = conn.execute("SELECT date('now') d").fetchone()["d"]
            if not start_date:
                start_date = conn.execute("SELECT date(?, '-13 days') d", (end_date,)).fetchone()["d"]

            # ---------------------------------------------------------------
            # ۱) روند فروش با تفکیک بازه (برای دوره‌های طولانی، نمودار روزانه
            # خیلی شلوغ و غیرقابل‌خواندن می‌شود؛ هفتگی/ماهانه هم موجود است)
            # ---------------------------------------------------------------
            bucket_expr = {
                "week": "strftime('%Y-W%W', o.created_at)",
                "month": "strftime('%Y-%m', o.created_at)",
            }.get(granularity, "date(o.created_at)")
            trend_rows = conn.execute(
                f"SELECT {bucket_expr} bucket, "
                "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue, "
                "SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) orders "
                "FROM orders o JOIN products p ON o.product_id=p.id "
                "WHERE date(o.created_at) BETWEEN ? AND ? "
                f"GROUP BY {bucket_expr} ORDER BY bucket",
                (start_date, end_date),
            ).fetchall()
            revenue_trend = {
                "granularity": granularity if granularity in ("week", "month") else "day",
                "points": [{"bucket": r["bucket"], "revenue": r["revenue"], "orders": r["orders"]} for r in trend_rows],
            }

            # ---------------------------------------------------------------
            # ۲) تفکیک درگاه پرداخت: هر درگاه جدول فاکتور خودش را دارد (بدون
            # ستون مشترک روی orders)، پس با UNION ALL یکی می‌شوند. «موفق» یعنی
            # status در ('completed','paid') - این دو مقدار بین درگاه‌های
            # مختلف پروژه پوشش کامل «پرداخت تکمیل‌شده» را می‌دهند.
            # ---------------------------------------------------------------
            gateway_union = (
                "SELECT 'کارت به کارت' gw, status, amount_toman amt, created_at ca "
                "FROM card_to_card_invoices WHERE kind='order' "
                "UNION ALL "
                "SELECT 'آبان‌گیت‌وی', status, amount_toman, created_at FROM abangateway_invoices WHERE kind='order' "
                "UNION ALL "
                "SELECT 'بلوپال', status, amount_toman, created_at FROM blupal_invoices WHERE kind='order' "
                "UNION ALL "
                "SELECT 'استارز تلگرام', status, amount_toman, created_at FROM noapay_invoices WHERE kind='order' "
                "UNION ALL "
                "SELECT 'ارز دیجیتال', status, amount_toman, created_at FROM crypto_invoices WHERE kind='order' "
                "UNION ALL "
                + self._extra_gateway_stats_select() +
                " UNION ALL "
                "SELECT cg.name, cgi.status, cgi.amount_toman, cgi.created_at "
                "FROM custom_gateway_invoices cgi JOIN custom_gateways cg ON cg.id=cgi.gateway_id "
                "WHERE cgi.kind='order'"
            )
            gw_rows = conn.execute(
                f"SELECT gw, COUNT(*) attempts, "
                "SUM(CASE WHEN status IN ('completed','paid') THEN 1 ELSE 0 END) success, "
                "COALESCE(SUM(CASE WHEN status IN ('completed','paid') THEN amt ELSE 0 END),0) revenue "
                f"FROM ({gateway_union}) WHERE date(ca) BETWEEN ? AND ? "
                "GROUP BY gw",
                (start_date, end_date),
            ).fetchall()
            gateway_breakdown = []
            for r in gw_rows:
                attempts = r["attempts"] or 0
                success = r["success"] or 0
                gateway_breakdown.append({
                    "gateway": r["gw"], "attempts": attempts, "success": success,
                    "failed": attempts - success,
                    "success_rate": round(success / attempts * 100, 1) if attempts else 0.0,
                    "revenue": r["revenue"] or 0,
                })
            # سفارش‌هایی که کامل با کیف پول (بدون هیچ درگاهی) پرداخت شدند، در
            # هیچ‌کدام از جدول‌های بالا ردی ندارند؛ جدا شمرده می‌شوند تا جمع
            # درآمدِ این بخش با کارت «💰 درآمد» بالای گزارش match شود.
            wallet_row = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(COALESCE(o.final_price, p.price)),0) rev "
                "FROM orders o JOIN products p ON o.product_id=p.id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "AND o.wallet_used > 0 AND o.wallet_used >= COALESCE(o.final_price, p.price)",
                (start_date, end_date),
            ).fetchone()
            if wallet_row["c"]:
                gateway_breakdown.append({
                    "gateway": "کیف پول", "attempts": wallet_row["c"], "success": wallet_row["c"],
                    "failed": 0, "success_rate": 100.0, "revenue": wallet_row["rev"] or 0,
                })
            gateway_breakdown.sort(key=lambda x: x["revenue"], reverse=True)

            # ---------------------------------------------------------------
            # ۳) منبع ورودی کاربر (کمپین/لینک اختصاصی ثبت‌شده در acquisition_source)
            # فقط برای کاربرانی که در همین بازه عضو شده‌اند - یعنی «این کمپین
            # امسال/این‌هفته چند کاربر تازه با چه نرخ تبدیلی آورد».
            # ---------------------------------------------------------------
            camp_rows = conn.execute(
                "SELECT COALESCE(NULLIF(u.acquisition_source,''),'نامشخص/مستقیم') src, "
                "COUNT(DISTINCT u.telegram_id) new_users, "
                "COUNT(DISTINCT CASE WHEN o.status='approved' THEN o.user_id END) buyers, "
                "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue "
                "FROM users u "
                "LEFT JOIN orders o ON o.user_id=u.telegram_id "
                "LEFT JOIN products p ON o.product_id=p.id "
                "WHERE date(u.joined_at) BETWEEN ? AND ? "
                "GROUP BY src ORDER BY revenue DESC, new_users DESC",
                (start_date, end_date),
            ).fetchall()
            campaign_performance = [
                {
                    "source": r["src"], "new_users": r["new_users"], "buyers": r["buyers"],
                    "revenue": r["revenue"],
                    "conversion_rate": round(r["buyers"] / r["new_users"] * 100, 1) if r["new_users"] else 0.0,
                }
                for r in camp_rows
            ]

            # ---------------------------------------------------------------
            # ۴) عملکرد نمایندگان داخلی (لینک اختصاصی داخل همین بات - reseller
            # سطح دیگری که دیتابیس جدا دارد، اینجا نیست، چون در این دیتابیس
            # قابل‌کوئری نیست؛ آن یکی از پنل «نمایندگی‌ها» خودش گزارش می‌شود)
            # ---------------------------------------------------------------
            reseller_rows = conn.execute(
                "SELECT r.telegram_id tg_id, r.username, r.first_name, "
                "r.inline_reseller_commission_percent pct, "
                "COUNT(DISTINCT c.telegram_id) customers, "
                "COUNT(DISTINCT CASE WHEN o.status='approved' THEN o.id END) orders, "
                "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue "
                "FROM users r "
                "JOIN users c ON c.owner_reseller_id = r.telegram_id "
                "LEFT JOIN orders o ON o.user_id = c.telegram_id AND date(o.created_at) BETWEEN ? AND ? "
                "LEFT JOIN products p ON o.product_id = p.id "
                "WHERE r.inline_reseller_enabled = 1 "
                "GROUP BY r.telegram_id "
                "HAVING orders > 0 "
                "ORDER BY revenue DESC LIMIT 15",
                (start_date, end_date),
            ).fetchall()
            commission_rows = conn.execute(
                "SELECT owner_reseller_id, COALESCE(SUM(commission_amount),0) c "
                "FROM reseller_inline_commission_log WHERE date(created_at) BETWEEN ? AND ? "
                "GROUP BY owner_reseller_id",
                (start_date, end_date),
            ).fetchall()
            commission_map = {r["owner_reseller_id"]: r["c"] for r in commission_rows}
            reseller_performance = [
                {
                    "telegram_id": r["tg_id"],
                    "name": r["username"] or r["first_name"] or str(r["tg_id"]),
                    "commission_percent": r["pct"],
                    "customers": r["customers"], "orders": r["orders"], "revenue": r["revenue"],
                    "commission_paid": commission_map.get(r["tg_id"], 0),
                }
                for r in reseller_rows
            ]

            # ---------------------------------------------------------------
            # ۵) قیف تبدیل: از بین کاربرانی که در همین بازه به بات ملحق شدند،
            # چند درصد اصلاً سفارشی ثبت کردند و چند درصد به خرید تایید‌شده رسیدند.
            # ---------------------------------------------------------------
            cohort_row = conn.execute(
                "SELECT COUNT(*) total, "
                "COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN u.telegram_id END) attempted, "
                "COUNT(DISTINCT CASE WHEN o.status='approved' THEN u.telegram_id END) purchased "
                "FROM users u LEFT JOIN orders o ON o.user_id = u.telegram_id "
                "WHERE date(u.joined_at) BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()
            total_new = cohort_row["total"] or 0
            attempted = cohort_row["attempted"] or 0
            purchased = cohort_row["purchased"] or 0
            funnel = {
                "new_users": total_new,
                "attempted_purchase": attempted,
                "completed_purchase": purchased,
                "start_to_attempt_rate": round(attempted / total_new * 100, 1) if total_new else 0.0,
                "attempt_to_purchase_rate": round(purchased / attempted * 100, 1) if attempted else 0.0,
                "overall_conversion_rate": round(purchased / total_new * 100, 1) if total_new else 0.0,
            }

            # مشتریان بازگشتی در برابر مشتریانِ اولین‌خریدشان در همین بازه، به‌علاوه
            # مشتریانی که قبلاً خرید کرده‌اند ولی این چند روز اخیر (churn_days) برنگشته‌اند.
            returning_row = conn.execute(
                "SELECT COUNT(DISTINCT o.user_id) c FROM orders o "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "AND o.user_id IN ("
                "  SELECT o2.user_id FROM orders o2 WHERE o2.status='approved' AND date(o2.created_at) < ?"
                ")",
                (start_date, end_date, start_date),
            ).fetchone()
            period_buyers_row = conn.execute(
                "SELECT COUNT(DISTINCT o.user_id) c FROM orders o "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()
            churn_row = conn.execute(
                "SELECT COUNT(DISTINCT user_id) c FROM orders WHERE status='approved' "
                "AND user_id NOT IN ("
                "  SELECT user_id FROM orders WHERE status='approved' AND date(created_at) >= date('now', ?)"
                ")",
                (f"-{churn_days} days",),
            ).fetchone()
            returning = returning_row["c"] or 0
            period_buyers = period_buyers_row["c"] or 0
            retention = {
                "returning_customers": returning,
                "first_time_customers": max(period_buyers - returning, 0),
                "churned_customers": churn_row["c"] or 0,
                "churn_window_days": churn_days,
            }

            # ---------------------------------------------------------------
            # ۶) نقشه‌ی ساعتی/روزهفته‌ی سفارش‌های تایید‌شده - برای دانستن شلوغ‌ترین
            # ساعات (مثلاً برای برنامه‌ریزی پشتیبانی). created_at به وقت UTC ذخیره
            # می‌شود، پس با +۳:۳۰ به وقت تهران تبدیل می‌شود.
            # ---------------------------------------------------------------
            heat_rows = conn.execute(
                "SELECT CAST(strftime('%w', o.created_at, '+3 hours', '+30 minutes') AS INTEGER) dow, "
                "CAST(strftime('%H', o.created_at, '+3 hours', '+30 minutes') AS INTEGER) hour, "
                "COUNT(*) c "
                "FROM orders o WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY dow, hour",
                (start_date, end_date),
            ).fetchall()
            heat_map = [[0] * 24 for _ in range(7)]
            for r in heat_rows:
                heat_map[r["dow"]][r["hour"]] = r["c"]

            return {
                "start_date": start_date, "end_date": end_date,
                "revenue_trend": revenue_trend,
                "gateway_breakdown": gateway_breakdown,
                "campaign_performance": campaign_performance,
                "reseller_performance": reseller_performance,
                "funnel": funnel,
                "retention": retention,
                "hourly_heatmap": heat_map,  # هفت ردیف (شنبه=۰..جمعه=۶ به وقت sqlite) × ۲۴ ساعت، وقت تهران
            }


    def get_orders_for_export(self, start_date: str = None, end_date: str = None):
        """لیست خام سفارش‌ها برای خروجی CSV، در بازه‌ی زمانی داده‌شده."""
        with self._get_conn() as conn:
            if not end_date:
                end_date = conn.execute("SELECT date('now') d").fetchone()["d"]
            if not start_date:
                start_date = conn.execute("SELECT date(?, '-13 days') d", (end_date,)).fetchone()["d"]
            rows = conn.execute(
                "SELECT o.id, o.created_at, o.status, o.user_id, u.username, u.first_name, "
                "p.name as product_name, COALESCE(o.final_price, p.price) as amount, "
                "o.wallet_used, o.discount_amount, COALESCE(o.quantity, 1) as quantity "
                "FROM orders o "
                "JOIN products p ON o.product_id=p.id "
                "LEFT JOIN users u ON o.user_id=u.telegram_id "
                "WHERE date(o.created_at) BETWEEN ? AND ? "
                "ORDER BY o.id DESC",
                (start_date, end_date),
            ).fetchall()
            return rows

    # -----------------------------------------------------------------------
    # زیرمجموعه‌گیری (رفرال) و کیف پول اعتباری
    # -----------------------------------------------------------------------


    def get_referral_stats(self, user_tg_id: int) -> dict:
        with self._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE referred_by=?", (user_tg_id,)
            ).fetchone()["c"]
            row = conn.execute(
                "SELECT referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            credit = row["referral_credit"] if row else 0
            return {"count": count, "credit": credit}


    def get_wallet_credit(self, user_tg_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return row["referral_credit"] if row else 0


    def add_wallet_credit(self, user_tg_id: int, delta: int, kind: str = None, note: str = None):
        with self._get_conn() as conn:
            with _wallet_tag(conn, user_tg_id, kind, note):
                conn.execute(
                    "UPDATE users SET referral_credit = MAX(referral_credit + ?, MIN(referral_credit, 0)) WHERE telegram_id=?",
                    (delta, user_tg_id),
                )


    def deduct_wallet_credit(self, user_tg_id: int, amount: int, exact: bool = False) -> int:
        """کسر اتمیک از کیف پول با احتساب سقف اعتبار پس‌پرداخت؛ مقدار واقعاً کسرشده را برمی‌گرداند (در حالت exact اگر موجودی و اعتبار کم باشد ۰)."""
        amount = int(amount)
        if amount <= 0:
            return 0
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            balance, limit = self._wallet_balance_and_limit(conn, user_tg_id)
            if balance + limit >= amount:
                take = amount
            else:
                take = 0 if exact else max(min(amount, balance), 0)
            if take > 0:
                with _wallet_tag(conn, user_tg_id, "purchase"):
                    conn.execute(
                        "UPDATE users SET referral_credit = referral_credit - ? WHERE telegram_id=?",
                        (take, user_tg_id),
                    )
            return take


    @staticmethod
    def _wallet_balance_and_limit(conn, user_tg_id: int):
        """موجودی و سقف اعتبار مؤثر: سقف اختصاصی کاربر، وگرنه سقف پیش‌فرض سطح نمایندگی او."""
        row = conn.execute(
            "SELECT COALESCE(u.referral_credit, 0) AS c, "
            "CASE WHEN COALESCE(u.credit_limit, 0) > 0 THEN u.credit_limit "
            "ELSE COALESCE(t.credit_limit_toman, 0) END AS l "
            "FROM users u LEFT JOIN reseller_tiers t ON t.code = u.reseller_tier WHERE u.telegram_id=?",
            (user_tg_id,),
        ).fetchone()
        if not row:
            return 0, 0
        return int(row["c"]), max(int(row["l"]), 0)


    def get_wallet_status(self, user_tg_id: int) -> dict:
        """موجودی، سقف اعتبار پس‌پرداخت، بدهی فعلی و اعتبار قابل استفاده‌ی کاربر."""
        self.expire_wallet_credits(user_tg_id)
        with self._get_conn() as conn:
            balance, limit = self._wallet_balance_and_limit(conn, user_tg_id)
        return {
            "balance": balance,
            "limit": limit,
            "debt": max(-balance, 0),
            "spendable": balance + limit,
        }

    WALLET_TX_KIND_LABELS = {
        "purchase": "خرید/تمدید سرویس", "order_refund": "بازگشت وجه سفارش", "service_refund": "بازگشت وجه حذف سرویس",
        "topup": "شارژ کیف پول", "transfer_out": "انتقال به کاربر دیگر", "transfer_in": "دریافت انتقال",
        "gift_code": "گیفت‌کد", "cashback": "کش‌بک", "referral_reward": "پاداش زیرمجموعه",
        "referral_invite": "پاداش دعوت", "reseller_commission": "کارمزد نمایندگی", "membership_fee": "هزینه‌ی عضویت نمایندگی",
        "lottery": "قرعه‌کشی", "location_fee": "تغییر لوکیشن", "location_refund": "بازگشت هزینه‌ی تغییر لوکیشن",
        "coin_convert": "تبدیل سکه", "coin_expire": "انقضای موجودی حاصل از سکه", "admin_adjust": "تنظیم دستی ادمین", "admin_bulk_deduct": "کاهش گروهی توسط ادمین",
    }


    @staticmethod
    def _bulk_wallet_where(status_filter: str, user_type_filter: str, now: str):
        """شروط WHERE مشترک برای پیش‌نمایش/اجرای کاهش گروهی موجودی کیف پول.
        status_filter: 'all' | 'active' | 'expired' | 'blocked'
        user_type_filter: 'all' | 'reseller' | 'normal'
        خروجی: (conditions, params) — params شامل now برای active/expired است."""
        conditions = []
        params = []
        if status_filter == "blocked":
            conditions.append("u.is_blocked=1")
        elif status_filter == "active":
            conditions.append(
                "EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1 "
                "AND (c.expires_at IS NULL OR c.expires_at > ?))"
            )
            params.append(now)
        elif status_filter == "expired":
            conditions.append(
                "EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) "
                "AND NOT EXISTS (SELECT 1 FROM configs c2 WHERE c2.assigned_user_id=u.telegram_id AND c2.is_used=1 "
                "AND (c2.expires_at IS NULL OR c2.expires_at > ?))"
            )
            params.append(now)
        if user_type_filter == "reseller":
            conditions.append("(u.is_reseller=1 OR u.reseller_tier IS NOT NULL)")
        elif user_type_filter == "normal":
            conditions.append("NOT (u.is_reseller=1 OR u.reseller_tier IS NOT NULL)")
        return conditions, params


    def preview_bulk_wallet_deduct(self, status_filter: str = "all", user_type_filter: str = "all", amount: int = 0):
        """پیش‌نمایش کاهش گروهی موجودی کیف پول: لیست کاربران match‌شده با فیلتر + موجودی قبل/بعد
        (بدون سقف؛ موجودی می‌تواند منفی/بدهکار شود)."""
        amount = int(amount)
        now = datetime.utcnow().isoformat()
        conditions, params = self._bulk_wallet_where(status_filter, user_type_filter, now)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT u.telegram_id, u.username, u.first_name, COALESCE(u.referral_credit,0) AS balance "
                f"FROM users u {where} ORDER BY u.id",
                params,
            ).fetchall()
        return [
            {
                "telegram_id": r["telegram_id"], "username": r["username"], "first_name": r["first_name"],
                "balance_before": r["balance"], "balance_after": r["balance"] - amount,
            }
            for r in rows
        ]


    def apply_bulk_wallet_deduct(self, user_ids: list, amount: int, note: str = None) -> int:
        """کاهش مبلغ ثابت از موجودی کیف پول لیست کاربران؛ بدون سقف (می‌تواند بدهکار کند).
        تعداد کاربرانی که واقعاً به‌روزرسانی شدند را برمی‌گرداند."""
        amount = int(amount)
        if amount <= 0 or not user_ids:
            return 0
        updated = 0
        with self._get_conn() as conn:
            for uid in user_ids:
                with _wallet_tag(conn, uid, "admin_bulk_deduct", note):
                    cur = conn.execute(
                        "UPDATE users SET referral_credit = referral_credit - ? WHERE telegram_id=?",
                        (amount, uid),
                    )
                    updated += cur.rowcount
        return updated


    def admin_adjust_wallet(self, tg_id: int, amount: int, note: str = None):
        """موجودی کیف‌پول یک کاربر مشخص را به‌صورت دستی توسط ادمین تغییر می‌دهد
        (amount می‌تواند مثبت یا منفی باشد؛ بدون سقف، می‌تواند کاربر را بدهکار
        کند). موجودی جدید را برمی‌گرداند، یا None اگر کاربر یافت نشد."""
        amount = int(amount)
        if amount == 0:
            return None
        with self._get_conn() as conn:
            with _wallet_tag(conn, tg_id, "admin_adjust", note):
                cur = conn.execute(
                    "UPDATE users SET referral_credit = referral_credit + ? WHERE telegram_id=?",
                    (amount, tg_id),
                )
                if cur.rowcount == 0:
                    return None
            row = conn.execute(
                "SELECT referral_credit FROM users WHERE telegram_id=?", (tg_id,)
            ).fetchone()
            return row["referral_credit"] if row else None


    def get_wallet_transactions(self, user_tg_id: int, limit: int = 10):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM wallet_transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_tg_id, max(int(limit), 1)),
            ).fetchall()


    def get_wallet_transaction_entries(self, user_tg_id: int, limit: int = 50) -> list:
        """لاگ کیف پول به‌صورت لیست دیکشنری (با برچسب فارسی نوع تراکنش) برای پنل وب و مینی‌اپ."""
        return [
            {
                "id": r["id"], "delta": r["delta"], "balance_before": r["balance_before"],
                "balance_after": r["balance_after"], "kind": r["kind"],
                "label": self.WALLET_TX_KIND_LABELS.get(r["kind"], "سایر"),
                "note": r["note"] or "", "created_at": r["created_at"],
            }
            for r in self.get_wallet_transactions(user_tg_id, limit)
        ]


    def wallet_transactions_text(self, rows) -> str:
        """متن ساده‌ی لاگ تراکنش‌های کیف پول با موجودی قبل و بعد از هر تراکنش."""
        from jalali import to_jalali_str
        if not rows:
            return "هنوز تراکنشی ثبت نشده است."
        blocks = []
        for r in rows:
            label = self.WALLET_TX_KIND_LABELS.get(r["kind"], "سایر")
            icon = "🟢" if r["delta"] > 0 else "🔴"
            lines = [
                f"{icon} {label}: {r['delta']:+,} تومان",
                f"   موجودی: {r['balance_before']:,} ← {r['balance_after']:,}",
            ]
            if r["note"]:
                lines.append(f"   {r['note']}")
            lines.append(f"   🗓 {to_jalali_str(r['created_at'], with_time=True)}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


    def plan_wallet_spend(self, user_tg_id: int, price: int, allowed: bool = True) -> dict:
        """سهم کیف پول از خرید (با اعتبار پس‌پرداخت) و مسدودی کاربر بدهکاری که مبلغ از سقفش بیشتر است."""
        price = max(int(price), 0)
        if not allowed or price <= 0:
            return {"wallet_used": 0, "blocked": False, "message": ""}
        st = self.get_wallet_status(user_tg_id)
        balance, limit, spendable = st["balance"], st["limit"], st["spendable"]
        if (limit > 0 or balance < 0) and price <= spendable:
            return {"wallet_used": price, "blocked": False, "message": ""}
        if balance < 0:
            return {
                "wallet_used": 0,
                "blocked": True,
                "message": (
                    "⛔️ سقف اعتبار پس‌پرداخت شما برای این خرید کافی نیست.\n"
                    f"💳 بدهی فعلی: {st['debt']:,} تومان | سقف اعتبار: {limit:,} تومان\n"
                    "ابتدا کیف پول خود را شارژ کنید و سپس دوباره تلاش کنید."
                ),
            }
        return {"wallet_used": min(balance, price), "blocked": False, "message": ""}


    @staticmethod
    def _wallet_gift_code_hash(code: str) -> str:
        import hashlib
        return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


    def create_wallet_gift_code(self, code: str, amount: int, max_uses: int = 1, expires_at: str = None, created_by: int = None):
        code = code.strip().upper()
        if not code or amount <= 0 or max_uses < 1:
            raise ValueError("مقادیر کد هدیه نامعتبر است")
        code_hash = self._wallet_gift_code_hash(code)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO wallet_gift_codes(code_hash, amount, max_uses, expires_at, created_by) VALUES(?,?,?,?,?)",
                (code_hash, int(amount), int(max_uses), expires_at, created_by),
            )
            return cur.lastrowid


    def list_wallet_gift_codes(self, active_only: bool = False):
        with self._get_conn() as conn:
            sql = "SELECT * FROM wallet_gift_codes"
            if active_only:
                sql += " WHERE is_active=1"
            sql += " ORDER BY id DESC"
            return conn.execute(sql).fetchall()


    def toggle_wallet_gift_code(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE wallet_gift_codes SET is_active=CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?", (code_id,))


    def delete_wallet_gift_code(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM wallet_gift_codes WHERE id=?", (code_id,))


    def redeem_wallet_gift_code(self, user_tg_id: int, code: str) -> dict:
        from datetime import datetime, timezone
        code_hash = self._wallet_gift_code_hash(code)
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM wallet_gift_codes WHERE code_hash=?", (code_hash,)).fetchone()
            if not row or not row["is_active"]:
                raise ValueError("کد هدیه نامعتبر یا غیرفعال است")
            if row["expires_at"]:
                try:
                    exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp <= datetime.now(timezone.utc):
                        conn.execute("UPDATE wallet_gift_codes SET is_active=0 WHERE id=?", (row["id"],))
                        raise ValueError("اعتبار این کد هدیه تمام شده است")
                except ValueError:
                    raise
                except Exception:
                    pass
            if row["used_count"] >= row["max_uses"]:
                conn.execute("UPDATE wallet_gift_codes SET is_active=0 WHERE id=?", (row["id"],))
                raise ValueError("ظرفیت استفاده از این کد هدیه تمام شده است")
            already = conn.execute(
                "SELECT 1 FROM wallet_gift_redemptions WHERE gift_code_id=? AND user_id=?",
                (row["id"], user_tg_id),
            ).fetchone()
            if already:
                raise ValueError("این کد هدیه را قبلاً استفاده کرده‌ای")
            cur = conn.execute(
                "UPDATE wallet_gift_codes SET used_count=used_count+1, is_active=CASE WHEN used_count+1>=max_uses THEN 0 ELSE is_active END WHERE id=? AND is_active=1 AND used_count<max_uses",
                (row["id"],),
            )
            if cur.rowcount != 1:
                raise ValueError("کد هدیه هم‌زمان توسط کاربر دیگری مصرف شد؛ دوباره امتحان کن")
            conn.execute(
                "INSERT INTO wallet_gift_redemptions(gift_code_id,user_id,amount) VALUES(?,?,?)",
                (row["id"], user_tg_id, row["amount"]),
            )
            with _wallet_tag(conn, user_tg_id, "gift_code", "استفاده از گیفت‌کد"):
                conn.execute(
                    "UPDATE users SET referral_credit=MAX(referral_credit+?, MIN(referral_credit,0)) WHERE telegram_id=?",
                    (row["amount"], user_tg_id),
                )
            new_balance = conn.execute("SELECT referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()["referral_credit"]
            return {"amount": row["amount"], "new_balance": new_balance, "remaining_uses": max(0, row["max_uses"] - row["used_count"] - 1)}


    def create_discount_code(
        self, code: str, percent: int = None, fixed_amount: int = None, max_uses: int = 0,
        expires_at: str = None, source: str = "admin", min_purchase: int = None,
        max_purchase: int = None, product_id: int = None, category_id: int = None,
        per_user_limit: int = None, first_purchase_only: bool = False, audience: str = "all",
        max_discount_amount: int = None, product_ids: list = None,
    ) -> int:
        per_user_limit = int(per_user_limit) if per_user_limit and int(per_user_limit) > 0 else None
        audience = audience if audience in ("all", "normal", "reseller") else "all"
        product_ids_value = json.dumps([int(p) for p in product_ids], ensure_ascii=False) if product_ids else None
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO discount_codes (code, percent, fixed_amount, max_uses, expires_at, source, "
                "min_purchase, max_purchase, product_id, category_id, per_user_limit, first_purchase_only, audience, "
                "max_discount_amount, product_ids) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code.strip().upper(), percent, fixed_amount, max_uses, expires_at, source,
                    min_purchase or None, max_purchase or None, product_id or None, category_id or None,
                    per_user_limit, 1 if first_purchase_only else 0, audience,
                    max_discount_amount or None, product_ids_value,
                ),
            )
            return cur.lastrowid


    def update_discount_code(
        self, code_id: int, min_purchase: int = None, max_purchase: int = None,
        product_id: int = None, category_id: int = None, expires_at: str = None,
        max_discount_amount: int = None, product_ids: list = None,
    ) -> None:
        """ویرایش محدودیت‌های یک کد تخفیف موجود (حداقل/حداکثر خرید، سقف مبلغ
        تخفیف، محصول/دسته‌ی اختصاصی یا چند محصول خاص، تاریخ انقضا). مقادیر
        None یعنی «بدون محدودیت» برای همان فیلد."""
        product_ids_value = json.dumps([int(p) for p in product_ids], ensure_ascii=False) if product_ids else None
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE discount_codes SET min_purchase=?, max_purchase=?, product_id=?, "
                "category_id=?, expires_at=?, max_discount_amount=?, product_ids=? WHERE id=?",
                (
                    min_purchase or None, max_purchase or None, product_id or None, category_id or None,
                    expires_at, max_discount_amount or None, product_ids_value, code_id,
                ),
            )


    def get_discount_code(self, code: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM discount_codes WHERE code=?", (code.strip().upper(),)
            ).fetchone()


    def get_discount_code_by_id(self, code_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM discount_codes WHERE id=?", (code_id,)).fetchone()


    def list_discount_codes(self, exclude_source: str = None):
        """لیست کدهای تخفیف. exclude_source برای پنهان‌کردن کدهای گروهیِ تک‌کاربره
        (source='bulk_admin') از صفحات مدیریتی که هر کد را با دکمه‌ی جدا نشان
        می‌دهند - چون تعدادشان می‌تواند صدها/هزاران باشد و کیبورد تلگرام را
        بشکند؛ خودِ کدها در دیتابیس و در گزارش‌ها/API دست‌نخورده می‌مانند."""
        with self._get_conn() as conn:
            if exclude_source:
                return conn.execute(
                    "SELECT * FROM discount_codes WHERE source IS NOT ? ORDER BY id DESC", (exclude_source,)
                ).fetchall()
            return conn.execute("SELECT * FROM discount_codes ORDER BY id DESC").fetchall()


    def toggle_discount_code(self, code_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_active FROM discount_codes WHERE id=?", (code_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE discount_codes SET is_active=? WHERE id=?",
                    (0 if row["is_active"] else 1, code_id),
                )


    def delete_discount_code(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM discount_codes WHERE id=?", (code_id,))


    def increment_discount_usage(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE discount_codes SET used_count = used_count + 1 WHERE id=?", (code_id,))


    def decrement_discount_usage(self, code_id: int, order_id: int = None):
        with self._get_conn() as conn:
            if order_id is not None:
                conn.execute(
                    "DELETE FROM discount_redemptions WHERE code_id=? AND order_id=?", (code_id, order_id)
                )
            conn.execute(
                "UPDATE discount_codes SET used_count = MAX(used_count - 1, 0) WHERE id=?", (code_id,)
            )


    def claim_discount_use(self, code_id: int, user_id: int) -> bool:
        """مصرف یک بار کد را اتمیک رزرو می‌کند (سقف کلی و سقف هر کاربر)؛ در صورت پر بودن سقف False."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE discount_codes SET used_count = used_count + 1 WHERE id=? AND is_active=1 "
                "AND (COALESCE(max_uses, 0) = 0 OR used_count < max_uses) "
                "AND (COALESCE(per_user_limit, 0) = 0 OR "
                "(SELECT COUNT(*) FROM discount_redemptions WHERE code_id=? AND user_id=?) < per_user_limit)",
                (code_id, code_id, user_id),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "INSERT INTO discount_redemptions (code_id, user_id) VALUES (?, ?)", (code_id, user_id)
            )
            return True


    def _discount_user_invalid_reason(self, row, user_id: int):
        keys = row.keys()
        audience = (row["audience"] if "audience" in keys else None) or "all"
        first_only = bool(row["first_purchase_only"]) if "first_purchase_only" in keys else False
        per_user_limit = (row["per_user_limit"] if "per_user_limit" in keys else None) or 0
        with self._get_conn() as conn:
            if audience != "all":
                u = conn.execute(
                    "SELECT is_reseller, reseller_tier FROM users WHERE telegram_id=?", (user_id,)
                ).fetchone()
                is_reseller = bool(u and (u["is_reseller"] or u["reseller_tier"]))
                if audience == "normal" and is_reseller:
                    return "این کد تخفیف فقط برای کاربران عادی معتبر است."
                if audience == "reseller" and not is_reseller:
                    return "این کد تخفیف فقط برای نمایندگان معتبر است."
            if first_only:
                has_order = conn.execute(
                    "SELECT 1 FROM orders WHERE user_id=? AND status IN ('pending','processing','approved') LIMIT 1",
                    (user_id,),
                ).fetchone()
                if has_order:
                    return "این کد تخفیف فقط برای اولین خرید معتبر است."
            if per_user_limit:
                used = conn.execute(
                    "SELECT COUNT(*) c FROM discount_redemptions WHERE code_id=? AND user_id=?",
                    (row["id"], user_id),
                ).fetchone()["c"]
                if used >= per_user_limit:
                    if per_user_limit == 1:
                        return "شما قبلاً از این کد تخفیف استفاده کرده‌اید."
                    return "سقف استفاده‌ی شما از این کد تخفیف تمام شده است."
        return None


    def get_discount_invalid_reason(
        self, row, price: int = None, product_id: int = None, category_id: int = None,
        user_id: int = None,
    ) -> str:
        """اگر کد تخفیف معتبر نباشد، دلیل قابل‌نمایش به کاربر را برمی‌گرداند؛
        اگر معتبر باشد None برمی‌گردد. price/product_id در صورت وجود، شرط‌های
        حداقل/حداکثر خرید و محصول/دسته‌ی اختصاصی را هم چک می‌کنند."""
        if not row:
            return "کد تخفیف یافت نشد."
        if not row["is_active"]:
            return "این کد تخفیف غیرفعال است."
        if row["max_uses"] and row["used_count"] >= row["max_uses"]:
            return "سقف استفاده از این کد تخفیف تمام شده است."
        expires_at = row["expires_at"] if "expires_at" in row.keys() else None
        if expires_at and datetime.utcnow().isoformat() > expires_at:
            return "این کد تخفیف منقضی شده است."

        row_product_id = row["product_id"] if "product_id" in row.keys() else None
        row_category_id = row["category_id"] if "category_id" in row.keys() else None
        row_product_ids_raw = row["product_ids"] if "product_ids" in row.keys() else None
        if row_product_ids_raw:
            try:
                allowed_product_ids = {int(p) for p in json.loads(row_product_ids_raw)}
            except (ValueError, TypeError):
                allowed_product_ids = set()
            if product_id is None or int(product_id) not in allowed_product_ids:
                return "این کد تخفیف فقط برای چند محصول خاص معتبر است."
        elif row_product_id:
            if product_id is None or int(product_id) != int(row_product_id):
                return "این کد تخفیف فقط برای یک محصول خاص معتبر است."
        elif row_category_id:
            effective_cat_id = category_id
            if effective_cat_id is None and product_id is not None:
                product = self.get_product(product_id)
                effective_cat_id = product["category_id"] if product else None
            if effective_cat_id is None or int(effective_cat_id) != int(row_category_id):
                return "این کد تخفیف فقط برای یک دسته‌بندی خاص معتبر است."

        min_purchase = row["min_purchase"] if "min_purchase" in row.keys() else None
        max_purchase = row["max_purchase"] if "max_purchase" in row.keys() else None
        if price is not None:
            if min_purchase and price < min_purchase:
                return f"حداقل مبلغ خرید برای این کد {min_purchase:,} تومان است."
            if max_purchase and price > max_purchase:
                return f"این کد فقط برای خریدهای تا سقف {max_purchase:,} تومان معتبر است."
        if user_id is not None:
            return self._discount_user_invalid_reason(row, int(user_id))
        return None


    def is_discount_code_valid(
        self, row, price: int = None, product_id: int = None, category_id: int = None, user_id: int = None,
    ) -> bool:
        return self.get_discount_invalid_reason(row, price, product_id, category_id, user_id) is None


    def compute_discount_amount(self, row, price: int) -> int:
        if row["percent"]:
            amount = (price * row["percent"]) // 100
            max_discount_amount = row["max_discount_amount"] if "max_discount_amount" in row.keys() else None
            if max_discount_amount:
                amount = min(amount, max_discount_amount)
            return min(amount, price)
        if row["fixed_amount"]:
            return min(row["fixed_amount"], price)
        return 0


    def get_discount_product_ids(self, row) -> list:
        """لیست شناسه‌ی محصولاتِ حالت «چند محصول خاص» یک کد تخفیف (ستون
        product_ids، JSON)؛ اگر تنظیم نشده باشد لیست خالی برمی‌گرداند."""
        raw = row["product_ids"] if "product_ids" in row.keys() else None
        if not raw:
            return []
        try:
            return [int(p) for p in json.loads(raw)]
        except (ValueError, TypeError):
            return []


    def get_discount_product_names(self, row) -> list:
        names = []
        for pid in self.get_discount_product_ids(row):
            product = self.get_product(pid)
            if product:
                names.append(product["name"])
        return names

    # -----------------------------------------------------------------------
    # شارژ کیف پول
    # -----------------------------------------------------------------------


    def create_topup(self, user_tg_id: int, amount: int) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO wallet_topups (user_id, amount, status) VALUES (?, ?, 'pending')",
                (user_tg_id, amount),
            )
            return cur.lastrowid


    def set_topup_receipt(self, topup_id: int, file_id: str, receipt_type: str = "photo"):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE wallet_topups SET receipt_file_id=?, receipt_type=? WHERE id=?",
                (file_id, receipt_type, topup_id),
            )


    def set_topup_admin_message(self, topup_id: int, admin_chat_id: int, admin_message_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE wallet_topups SET admin_chat_id=?, admin_message_id=? WHERE id=?",
                (admin_chat_id, admin_message_id, topup_id),
            )


    def get_topup(self, topup_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM wallet_topups WHERE id=?", (topup_id,)).fetchone()


    def get_latest_pending_topup_awaiting_receipt(self, user_tg_id: int):
        """آخرین درخواست شارژ کیف‌پول این کاربر که هنوز pending است و رسیدی
        برایش ثبت نشده - برای fallback بازیابی رسیدهایی که FSM state‌شان گم شده."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM wallet_topups WHERE user_id=? AND status='pending' "
                "AND receipt_file_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='wallet_topup' AND ci.ref_id=wallet_topups.id) "
                "ORDER BY id DESC LIMIT 1",
                (user_tg_id,),
            ).fetchone()


    def approve_topup(self, topup_id: int) -> bool:
        """تایید شارژ کیف پول و اعمال کش‌بک یک‌باره در صورت فعال بودن."""
        topup = self.get_topup(topup_id)
        if not topup:
            return False
        percent = max(0, min(int(self.get_setting("topup_cashback_percent", "0") or 0), 100))
        cashback = (int(topup["amount"] or 0) * percent) // 100
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE wallet_topups SET status='approved', updated_at=?, cashback_paid=1, cashback_amount=? "
                "WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), cashback, topup_id),
            )
            if cur.rowcount == 0:
                return False
            with _wallet_tag(conn, topup["user_id"], "topup", f"شارژ کیف پول #{topup_id}"):
                conn.execute(
                    "UPDATE users SET referral_credit=MAX(referral_credit + ?, MIN(referral_credit,0)) WHERE telegram_id=?",
                    (int(topup["amount"]) + cashback, topup["user_id"]),
                )
        return True


    def get_topup_cashback(self, topup_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT cashback_amount FROM wallet_topups WHERE id=?", (topup_id,)).fetchone()
        return int(row["cashback_amount"] or 0) if row else 0


    def reject_topup(self, topup_id: int) -> bool:
        """فقط topup pending را رد می‌کند (نه processing/approved)."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE wallet_topups SET status='rejected', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), topup_id),
            )
            return cur.rowcount > 0


    def get_topups_by_status(self, status: str, limit: int = 200):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM wallet_topups WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
            ).fetchall()


    def get_pending_topups(self):
        """شارژهای نیازمند بررسی دستی؛ شارژهای دارای فاکتور کریپتو، یا فاکتور فعال
        new/pending نزد یک درگاه «تایید آنی» دیگر (آبان‌گیت‌وی/بلوپال/نوپی/درگاه
        سفارشی/کارت‌به‌کارت خودکار)، اینجا نمی‌آیند - رجوع به توضیح get_pending_orders."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT t.* FROM wallet_topups t "
                "WHERE t.status='pending' "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='wallet_topup' AND ci.ref_id=t.id) "
                "AND NOT EXISTS (SELECT 1 FROM abangateway_invoices gi WHERE gi.kind='wallet_topup' AND gi.ref_id=t.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM blupal_invoices gi WHERE gi.kind='wallet_topup' AND gi.ref_id=t.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM noapay_invoices gi WHERE gi.kind='wallet_topup' AND gi.ref_id=t.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM extra_gateway_invoices gi WHERE gi.kind='wallet_topup' AND gi.ref_id=t.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM custom_gateway_invoices gi WHERE gi.kind='wallet_topup' AND gi.ref_id=t.id AND gi.status IN ('new','pending')) "
                "AND NOT EXISTS (SELECT 1 FROM card_to_card_invoices gi WHERE gi.kind='wallet_topup' AND gi.ref_id=t.id AND gi.status='pending') "
                "ORDER BY t.id"
            ).fetchall()

    # -----------------------------------------------------------------------
    # ثبت‌نام بات‌های نمایندگی (فقط در دیتابیس بات اصلی معنا دارد)
    # -----------------------------------------------------------------------


    @staticmethod
    def _db_now() -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


    @staticmethod
    def _db_after_days(days: int):
        if int(days) <= 0:
            return None
        return (datetime.utcnow() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")


    def _grant_coins(self, conn, user_tg_id: int, points: int, expiry_days: int):
        """points و expiry_days باید قبل از باز کردن conn محاسبه شوند."""
        if points <= 0:
            return
        conn.execute("UPDATE users SET score=COALESCE(score,0)+? WHERE telegram_id=?", (int(points), user_tg_id))
        conn.execute(
            "INSERT INTO coin_batches (user_id, amount, remaining, created_at, expires_at) VALUES (?,?,?,?,?)",
            (user_tg_id, int(points), int(points), self._db_now(), self._db_after_days(expiry_days)),
        )


    def add_score(self, user_tg_id: int, points: int = 1) -> int:
        """افزایش اتمیک سکه؛ مقدار منفی مجاز نیست."""
        if self.get_setting("score_enabled", "1") != "1" or points <= 0:
            return self.get_user_score(user_tg_id)
        expiry_days = self.get_coin_settings()["expiry_days"]
        with self._get_conn() as conn:
            self._grant_coins(conn, user_tg_id, int(points), expiry_days)
            row = conn.execute("SELECT COALESCE(score,0) score FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
        return int(row["score"]) if row else 0


    def get_score_points(self, kind: str) -> int:
        """امتیاز هر رویداد (purchase/renewal/referral)؛ با خاموش بودن امتیاز یا مقدار صفر، صفر برمی‌گرداند."""
        if self.get_setting("score_enabled", "1") != "1":
            return 0
        default = {"purchase": 2, "renewal": 1, "referral": 1}.get(kind, 0)
        try:
            return max(0, min(int(self.get_setting(f"score_{kind}_points", str(default)) or 0), 1000))
        except (TypeError, ValueError):
            return default


    def _award_order_score(self, conn, order_id: int, points: int, expiry_days: int = 0):
        """points و expiry_days باید قبل از باز کردن conn محاسبه شوند؛ get_setting داخل قفل _get_conn ممکن است deadlock بدهد."""
        if points > 0:
            row = conn.execute("SELECT user_id FROM orders WHERE id=?", (order_id,)).fetchone()
            if row:
                self._grant_coins(conn, row["user_id"], points, expiry_days)


    @staticmethod
    def _lottery_participant_clause(include_agents: bool, min_coins: int) -> str:
        agent = "" if include_agents else "AND COALESCE(reseller_tier,'') = '' AND COALESCE(inline_reseller_enabled,0)=0"
        return f"is_blocked=0 AND COALESCE(coin_mode,'wallet')='lottery' AND COALESCE(score,0)>={max(1, int(min_coins))} {agent}"


    def get_score_leaderboard(self, limit: int = 10, include_agents: bool = True):
        self.expire_coins()
        clause = self._lottery_participant_clause(include_agents, self.get_coin_settings()["lottery_min"])
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT telegram_id, username, first_name, COALESCE(score,0) score FROM users "
                f"WHERE {clause} ORDER BY score DESC, telegram_id LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()


    def count_score_participants(self, include_agents: bool = True) -> int:
        self.expire_coins()
        clause = self._lottery_participant_clause(include_agents, self.get_coin_settings()["lottery_min"])
        with self._get_conn() as conn:
            row = conn.execute(f"SELECT COUNT(*) c FROM users WHERE {clause}").fetchone()
        return int(row["c"]) if row else 0


    def get_coin_settings(self) -> dict:
        def _int(key, default):
            try:
                return max(0, int(self.get_setting(key, str(default)) or 0))
            except (TypeError, ValueError):
                return default
        return {
            "enabled": self.get_setting("score_enabled", "1") == "1",
            "value": _int("coin_value_toman", 0),
            "convert_min": max(1, _int("coin_convert_min", 1)),
            "convert_max": _int("coin_convert_max", 0),
            "lottery_min": max(1, _int("lottery_min_coins", 1)),
            "expiry_days": min(_int("coin_expiry_days", 7), 3650),
            "wallet_expiry_days": min(_int("coin_wallet_expiry_days", 7), 3650),
        }


    def get_user_coin_mode(self, user_tg_id: int) -> str:
        with self._get_conn() as conn:
            row = conn.execute("SELECT coin_mode FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
        return "lottery" if row and row["coin_mode"] == "lottery" else "wallet"


    def set_user_coin_mode(self, user_tg_id: int, mode: str) -> str:
        mode = "lottery" if mode == "lottery" else "wallet"
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET coin_mode=? WHERE telegram_id=?", (mode, user_tg_id))
        return mode


    def convert_coins_to_wallet(self, user_tg_id: int, coins: int) -> dict:
        """تبدیل اتمیک سکه به موجودی کیف پول؛ در خطا ValueError با پیام فارسی می‌دهد."""
        s = self.get_coin_settings()
        coins = int(coins)
        if not s["enabled"]:
            raise ValueError("سیستم سکه غیرفعال است.")
        if s["value"] <= 0:
            raise ValueError("تبدیل سکه به موجودی هنوز فعال نشده است.")
        if coins < s["convert_min"]:
            raise ValueError(f"حداقل تعداد سکه برای تبدیل {s['convert_min']:,} است.")
        if s["convert_max"] and coins > s["convert_max"]:
            raise ValueError(f"حداکثر تعداد سکه برای هر تبدیل {s['convert_max']:,} است.")
        amount = coins * s["value"]
        self.expire_coins(user_tg_id)
        self.expire_wallet_credits(user_tg_id)
        expires_at = self._db_after_days(s["wallet_expiry_days"])
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(score,0) score, COALESCE(coin_mode,'wallet') coin_mode FROM users WHERE telegram_id=?",
                (user_tg_id,),
            ).fetchone()
            if not row:
                raise ValueError("کاربر پیدا نشد.")
            if row["coin_mode"] != "wallet":
                raise ValueError("برای تبدیل، ابتدا حالت سکه‌ها را روی «تبدیل به کیف پول» بگذارید.")
            if row["score"] < coins:
                raise ValueError("تعداد سکه‌های شما کافی نیست.")
            cur = conn.execute(
                "UPDATE users SET score=score-? WHERE telegram_id=? AND COALESCE(score,0)>=?",
                (coins, user_tg_id, coins),
            )
            if cur.rowcount == 0:
                raise ValueError("تعداد سکه‌های شما کافی نیست.")
            self._consume_coin_batches(conn, user_tg_id, coins)
            with _wallet_tag(conn, user_tg_id, "coin_convert", f"تبدیل {coins:,} سکه"):
                conn.execute(
                    "UPDATE users SET referral_credit=MAX(COALESCE(referral_credit,0)+?, MIN(COALESCE(referral_credit,0),0)) WHERE telegram_id=?",
                    (amount, user_tg_id),
                )
            tx_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM wallet_transactions WHERE user_id=?", (user_tg_id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO coin_wallet_credits (user_id, amount, remaining, tx_id, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                (user_tg_id, amount, amount, int(tx_id), self._db_now(), expires_at),
            )
        return {"coins": coins, "amount": amount, "coins_left": int(row["score"]) - coins, "expires_at": expires_at}


    @staticmethod
    def _consume_coin_batches(conn, user_tg_id: int, coins: int):
        need = int(coins)
        rows = conn.execute(
            "SELECT id, remaining FROM coin_batches WHERE user_id=? AND remaining>0 "
            "ORDER BY (expires_at IS NULL), expires_at, id",
            (user_tg_id,),
        ).fetchall()
        for r in rows:
            if need <= 0:
                break
            take = min(need, int(r["remaining"]))
            conn.execute("UPDATE coin_batches SET remaining=remaining-? WHERE id=?", (take, r["id"]))
            need -= take


    def expire_coins(self, user_tg_id: int = None) -> list:
        """سکه‌های منقضی‌شده را کم می‌کند و [(user_id, تعداد)] برمی‌گرداند؛ سکه‌ی بدون دسته (قدیمی) از همین لحظه مهلت می‌گیرد."""
        now = self._db_now()
        expiry_days = self.get_coin_settings()["expiry_days"]
        user_filter = "" if user_tg_id is None else "AND u.telegram_id=?"
        params = () if user_tg_id is None else (user_tg_id,)
        expired = []
        with self._get_conn() as conn:
            orphans = conn.execute(
                "SELECT u.telegram_id uid, COALESCE(u.score,0) - COALESCE((SELECT SUM(b.remaining) FROM coin_batches b WHERE b.user_id=u.telegram_id),0) diff "
                "FROM users u WHERE COALESCE(u.score,0)>0 "
                "AND COALESCE(u.score,0) > COALESCE((SELECT SUM(b.remaining) FROM coin_batches b WHERE b.user_id=u.telegram_id),0) "
                f"{user_filter}",
                params,
            ).fetchall()
            for o in orphans:
                conn.execute(
                    "INSERT INTO coin_batches (user_id, amount, remaining, created_at, expires_at) VALUES (?,?,?,?,?)",
                    (o["uid"], o["diff"], o["diff"], now, self._db_after_days(expiry_days)),
                )
            due_filter = "" if user_tg_id is None else "AND user_id=?"
            due = conn.execute(
                "SELECT id, user_id, remaining FROM coin_batches WHERE remaining>0 AND expires_at IS NOT NULL AND expires_at<=? "
                f"{due_filter}",
                (now,) + params,
            ).fetchall()
            totals = {}
            for d in due:
                totals[d["user_id"]] = totals.get(d["user_id"], 0) + int(d["remaining"])
                conn.execute("UPDATE coin_batches SET remaining=0 WHERE id=?", (d["id"],))
            for uid, total in totals.items():
                conn.execute("UPDATE users SET score=MAX(COALESCE(score,0)-?,0) WHERE telegram_id=?", (total, uid))
                expired.append((uid, total))
        return expired


    @staticmethod
    def _sync_wallet_credits(conn, user_tg_id: int):
        """برداشت‌های کیف پول را از دفتر تراکنش‌ها روی موجودی حاصل از سکه اعمال می‌کند؛ اول موجودی زودتر منقضی‌شونده خرج می‌شود."""
        row = conn.execute("SELECT COALESCE(coin_credit_synced_tx,0) FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
        synced = int(row[0]) if row else 0
        txs = conn.execute(
            "SELECT id, delta, created_at FROM wallet_transactions WHERE user_id=? AND id>? AND delta<0 "
            "AND COALESCE(kind,'')<>'coin_expire' ORDER BY id",
            (user_tg_id, synced),
        ).fetchall()
        for tx in txs:
            need = -int(tx["delta"])
            credits = conn.execute(
                "SELECT id, remaining FROM coin_wallet_credits WHERE user_id=? AND remaining>0 AND tx_id<? "
                "AND (expires_at IS NULL OR expires_at>=?) ORDER BY (expires_at IS NULL), expires_at, id",
                (user_tg_id, tx["id"], tx["created_at"]),
            ).fetchall()
            for c in credits:
                if need <= 0:
                    break
                take = min(need, int(c["remaining"]))
                conn.execute("UPDATE coin_wallet_credits SET remaining=remaining-? WHERE id=?", (take, c["id"]))
                need -= take
        last = conn.execute("SELECT COALESCE(MAX(id),0) FROM wallet_transactions WHERE user_id=?", (user_tg_id,)).fetchone()[0]
        conn.execute("UPDATE users SET coin_credit_synced_tx=? WHERE telegram_id=?", (int(last), user_tg_id))


    def expire_wallet_credits(self, user_tg_id: int = None) -> list:
        """موجودی منقضی‌شده‌ی حاصل از تبدیل سکه را از کیف پول کم می‌کند و [(user_id, مبلغ)] برمی‌گرداند."""
        now = self._db_now()
        expired = []
        with self._get_conn() as conn:
            if user_tg_id is None:
                uids = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM coin_wallet_credits WHERE remaining>0").fetchall()]
            else:
                uids = [user_tg_id]
            for uid in uids:
                if not conn.execute("SELECT 1 FROM coin_wallet_credits WHERE user_id=? AND remaining>0 LIMIT 1", (uid,)).fetchone():
                    continue
                self._sync_wallet_credits(conn, uid)
                due = conn.execute(
                    "SELECT id, remaining FROM coin_wallet_credits WHERE user_id=? AND remaining>0 "
                    "AND expires_at IS NOT NULL AND expires_at<=?",
                    (uid, now),
                ).fetchall()
                if not due:
                    continue
                total = sum(int(d["remaining"]) for d in due)
                for d in due:
                    conn.execute("UPDATE coin_wallet_credits SET remaining=0 WHERE id=?", (d["id"],))
                balance = int(conn.execute("SELECT COALESCE(referral_credit,0) FROM users WHERE telegram_id=?", (uid,)).fetchone()[0])
                deduct = min(total, max(balance, 0))
                if deduct > 0:
                    with _wallet_tag(conn, uid, "coin_expire", "انقضای موجودی حاصل از تبدیل سکه"):
                        conn.execute("UPDATE users SET referral_credit=referral_credit-? WHERE telegram_id=?", (deduct, uid))
                    last = conn.execute("SELECT COALESCE(MAX(id),0) FROM wallet_transactions WHERE user_id=?", (uid,)).fetchone()[0]
                    conn.execute("UPDATE users SET coin_credit_synced_tx=? WHERE telegram_id=?", (int(last), uid))
                    expired.append((uid, deduct))
        return expired


    def get_coin_expiry_lines(self, user_tg_id: int, limit: int = 3) -> list:
        """[(تاریخ میلادی, تعداد)] نزدیک‌ترین انقضای سکه‌های کاربر."""
        self.expire_coins(user_tg_id)
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT date(expires_at) d, SUM(remaining) n FROM coin_batches WHERE user_id=? AND remaining>0 "
                "AND expires_at IS NOT NULL GROUP BY d ORDER BY d LIMIT ?",
                (user_tg_id, int(limit)),
            ).fetchall()
        return [(r["d"], int(r["n"])) for r in rows]


    def get_wallet_credit_expiry_lines(self, user_tg_id: int, limit: int = 3) -> list:
        """[(تاریخ میلادی, مبلغ)] نزدیک‌ترین انقضای موجودی حاصل از سکه."""
        self.expire_wallet_credits(user_tg_id)
        with self._get_conn() as conn:
            balance = conn.execute("SELECT COALESCE(referral_credit,0) FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
            rows = conn.execute(
                "SELECT date(expires_at) d, SUM(remaining) n FROM coin_wallet_credits WHERE user_id=? AND remaining>0 "
                "AND expires_at IS NOT NULL GROUP BY d ORDER BY d LIMIT ?",
                (user_tg_id, int(limit)),
            ).fetchall()
        cap = max(int(balance[0]), 0) if balance else 0
        lines = []
        for r in rows:
            amount = min(int(r["n"]), cap)
            cap -= amount
            if amount > 0:
                lines.append((r["d"], amount))
        return lines


    def get_cashback_totals(self) -> dict:
        with self._get_conn() as conn:
            renewal = conn.execute(
                "SELECT COALESCE(SUM(cashback_amount),0) t, COUNT(*) c FROM orders WHERE cashback_paid=1 AND COALESCE(cashback_amount,0)>0"
            ).fetchone()
            topup = conn.execute(
                "SELECT COALESCE(SUM(cashback_amount),0) t, COUNT(*) c FROM wallet_topups WHERE cashback_paid=1 AND COALESCE(cashback_amount,0)>0"
            ).fetchone()
        return {
            "renewal_total": int(renewal["t"]), "renewal_count": int(renewal["c"]),
            "topup_total": int(topup["t"]), "topup_count": int(topup["c"]),
        }


    def get_user_score(self, user_tg_id: int) -> int:
        self.expire_coins(user_tg_id)
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(score,0) score FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
        return int(row["score"]) if row else 0


    def get_lottery_settings(self) -> dict:
        raw = self.get_setting("lottery_prizes", "50000,30000,20000") or ""
        prizes = []
        for part in raw.split(","):
            try:
                value = int(part.strip())
                if value > 0:
                    prizes.append(value)
            except (TypeError, ValueError):
                pass
        prizes = (prizes + [50000, 30000, 20000])[:3]
        return {
            "enabled": self.get_setting("lottery_enabled", "1") == "1",
            "score_enabled": self.get_setting("score_enabled", "1") == "1",
            "agent_enabled": self.get_setting("lottery_agent_enabled", "0") == "1",
            "prize_type": self.get_setting("lottery_prize_type", "wallet") or "wallet",
            "prizes": prizes,
            "discount_expiry_hours": max(1, int(self.get_setting("lottery_discount_expiry_hours", "24") or 24)),
            "report_chat_id": self.get_setting("lottery_report_chat_id", "") or "",
            "min_coins": self.get_coin_settings()["lottery_min"],
        }


    def list_lottery_logs(self, limit: int = 10):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM lottery_log ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()


    def run_lottery_once(self, lottery_date: str = None) -> dict:
        """سه نفر اول را به‌صورت اتمیک انتخاب و سکه‌ی همه‌ی شرکت‌کنندگان را صفر می‌کند.
        INSERT UNIQUE روی lottery_date مانع اجرای دوباره در چند worker/process است."""
        from datetime import date as _date
        lottery_date = lottery_date or _date.today().isoformat()
        settings = self.get_lottery_settings()
        if not settings["enabled"] or not settings["score_enabled"]:
            return {"status": "disabled", "winners": [], "prizes": settings["prizes"]}
        self.expire_coins()
        import json as _json
        with self._get_conn() as conn:
            exists = conn.execute("SELECT id FROM lottery_log WHERE lottery_date=?", (lottery_date,)).fetchone()
            if exists:
                return {"status": "already_done", "winners": [], "prizes": settings["prizes"]}
            participant_clause = self._lottery_participant_clause(settings["agent_enabled"], settings["min_coins"])
            sql = f"SELECT telegram_id, username, first_name, COALESCE(score,0) score FROM users WHERE {participant_clause} ORDER BY score DESC, RANDOM() LIMIT 3"
            rows = conn.execute(sql).fetchall()
            winners = []
            for idx, row in enumerate(rows, 1):
                winners.append({"rank": idx, "user_id": int(row["telegram_id"]), "username": row["username"], "first_name": row["first_name"], "score": int(row["score"]), "prize": int(settings["prizes"][idx-1])})
            if not winners:
                return {"status": "no_winners", "winners": [], "prizes": settings["prizes"]}
            # ابتدا لاگ یکتا ثبت می‌شود تا دو پردازش همزمان نتوانند جایزه بدهند.
            conn.execute(
                "INSERT INTO lottery_log(lottery_date,winners_json,prize_type,prizes_json) VALUES(?,?,?,?)",
                (lottery_date, _json.dumps(winners, ensure_ascii=False), settings["prize_type"], _json.dumps(settings["prizes"]))
            )
            for winner in winners:
                if settings["prize_type"] == "wallet":
                    with _wallet_tag(conn, winner["user_id"], "lottery", "جایزه‌ی قرعه‌کشی"):
                        conn.execute("UPDATE users SET referral_credit=MAX(COALESCE(referral_credit,0)+?, MIN(COALESCE(referral_credit,0),0)) WHERE telegram_id=?", (winner["prize"], winner["user_id"]))
            conn.execute(
                f"UPDATE coin_batches SET remaining=0 WHERE remaining>0 AND user_id IN (SELECT telegram_id FROM users WHERE {participant_clause})"
            )
            conn.execute(f"UPDATE users SET score=0 WHERE {participant_clause}")
        # کد تخفیف خارج از transaction اصلی ساخته می‌شود؛ لاگ و صفرشدن امتیاز از قبل قطعی است.
        if settings["prize_type"] == "discount":
            for winner in winners:
                expires = (datetime.utcnow() + timedelta(hours=settings["discount_expiry_hours"])).isoformat()
                code = f"NIGHT{winner['user_id']}{secrets.randbelow(900000)+100000}"
                try:
                    self.create_discount_code(code, percent=winner["prize"], max_uses=1, expires_at=expires, source="lottery")
                    winner["code"] = code
                    winner["expires_at"] = expires
                except Exception:
                    winner["code"] = None
        return {"status": "completed", "winners": winners, "prizes": settings["prizes"], "prize_type": settings["prize_type"]}

    # -----------------------------------------------------------------------
    # گردونه شانس
    # -----------------------------------------------------------------------


    def get_wheel_settings(self) -> dict:
        return {
            "enabled": self.get_setting("wheel_enabled", "1") == "1",
            "win_percent": int(self.get_setting("wheel_win_percent", "10") or 0),
            "prizes": [int(p) for p in self.get_setting("wheel_prizes", "10,20,30,50").split(",") if p.strip().isdigit()],
            "expiry_hours": int(self.get_setting("wheel_code_expiry_hours", "24") or 24),
            "cooldown_hours": int(self.get_setting("wheel_cooldown_hours", "24") or 24),
        }


    def set_wheel_prizes(self, prizes: list):
        self.set_setting("wheel_prizes", ",".join(str(p) for p in prizes))


    def can_spin_wheel(self, user_tg_id: int):
        """برمی‌گرداند (True, None) اگر مجاز به چرخش باشد، وگرنه (False, ساعات باقی‌مانده)."""
        cooldown_hours = int(self.get_setting("wheel_cooldown_hours", "24") or 24)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT last_wheel_spin_at FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
        if not row or not row["last_wheel_spin_at"]:
            return True, None
        last_spin = datetime.fromisoformat(row["last_wheel_spin_at"])
        elapsed = datetime.utcnow() - last_spin
        remaining = cooldown_hours - (elapsed.total_seconds() / 3600)
        if remaining <= 0:
            return True, None
        return False, remaining


    def record_wheel_spin(self, user_tg_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_wheel_spin_at=? WHERE telegram_id=?",
                (datetime.utcnow().isoformat(), user_tg_id),
            )


    def generate_wheel_prize_code(self, user_tg_id: int, percent: int) -> tuple:
        """یک کد تخفیف یکبارمصرف با تاریخ انقضا برای برنده‌ی گردونه می‌سازد و برمی‌گرداند (code, expires_at)."""
        settings = self.get_wheel_settings()
        expires_at = (datetime.utcnow() + timedelta(hours=settings["expiry_hours"])).isoformat()
        code = f"LUCKY{user_tg_id}{secrets.randbelow(9000) + 1000}"
        self.create_discount_code(
            code, percent=percent, max_uses=1, expires_at=expires_at, source="wheel"
        )
        return code, expires_at

    def generate_bulk_discount_codes(
        self, user_ids: list, percent: int = None, fixed_amount: int = None, expires_at: str = None,
    ) -> list:
        """برای هر کاربر در user_ids یک کد تخفیف یکبارمصرف و یکتا می‌سازد (کد تخفیف
        گروهی بر اساس فیلتر، پنل مدیریت). هر کد فقط برای همان کاربر و فقط یک‌بار
        قابل استفاده است (max_uses=1, per_user_limit=1). خروجی: [(user_id, code), ...]
        - user_id هایی که به هر دلیل کد برایشان ساخته نشد (برخورد نام تصادفی پس از
        چند تلاش) در خروجی نمی‌آیند."""
        results = []
        for uid in user_ids:
            code = None
            for _ in range(5):
                candidate = f"BULK{uid}{secrets.randbelow(9000) + 1000}"
                if not self.get_discount_code(candidate):
                    code = candidate
                    break
            if not code:
                continue
            self.create_discount_code(
                code, percent=percent, fixed_amount=fixed_amount, max_uses=1,
                expires_at=expires_at, source="bulk_admin", per_user_limit=1,
            )
            results.append((uid, code))
        return results

    # -----------------------------------------------------------------------
    # یادآوری اتمام سرویس + کد تخفیف تشویقی تمدید
    # -----------------------------------------------------------------------


    def generate_renewal_discount_code(self, user_tg_id: int) -> tuple:
        """یک کد تخفیف یکبارمصرف و محدود به زمان برای یادآوری تمدید سرویس کاربر می‌سازد.
        خروجی: (code, expires_at, percent, expiry_hours)"""
        settings = self.get_renewal_settings()
        expires_at = (datetime.utcnow() + timedelta(hours=settings["discount_expiry_hours"])).isoformat()
        code = f"RENEW{user_tg_id}{secrets.randbelow(9000) + 1000}"
        self.create_discount_code(
            code, percent=settings["discount_percent"], max_uses=1, expires_at=expires_at, source="renewal_reminder"
        )
        return code, expires_at, settings["discount_percent"], settings["discount_expiry_hours"]

    # -----------------------------------------------------------------------
    # یادآوری اتمام حجم + کد تخفیف تشویقی تمدید (مستقل از یادآوری تاریخ انقضا)
    # -----------------------------------------------------------------------


    def generate_volume_discount_code(self, user_tg_id: int) -> tuple:
        """یک کد تخفیف یکبارمصرف و محدود به زمان برای یادآوری اتمام حجم کاربر می‌سازد.
        خروجی: (code, expires_at, percent, expiry_hours)"""
        settings = self.get_volume_reminder_settings()
        expires_at = (datetime.utcnow() + timedelta(hours=settings["discount_expiry_hours"])).isoformat()
        code = f"VOLUME{user_tg_id}{secrets.randbelow(9000) + 1000}"
        self.create_discount_code(
            code, percent=settings["discount_percent"], max_uses=1, expires_at=expires_at, source="volume_reminder"
        )
        return code, expires_at, settings["discount_percent"], settings["discount_expiry_hours"]

    # -----------------------------------------------------------------------
    # هشدار اتصال / عدم‌اتصال به کانفیگ
    #
    # چون هیچ‌کدام از پنل‌های VPN پشتیبانی‌شده وضعیت «آنلاین/آفلاین لحظه‌ای»
    # واقعی (handshake) را گزارش نمی‌کنند، «اتصال» از روی تغییر مصرف
    # (used_bytes) تشخیص داده می‌شود: اولین باری که مصرف سرویس از صفر (یا از
    # آستانه‌ی تنظیم‌شده) بیشتر شود، یعنی کاربر متصل شده. «عدم‌اتصال» یعنی بعد
    # از N ساعت از لحظه‌ی فعال‌سازی (assigned_at برای انبار کانفیگ،
    # created_at برای کانفیگ‌های ساخته‌شده مستقیم روی پنل)، مصرف هنوز به
    # آستانه نرسیده. متن پیام‌ها را ادمین تعیین می‌کند و می‌تواند از
    # placeholder های {used_gb} و {threshold_gb} استفاده کند.
    # -----------------------------------------------------------------------


    def get_early_full_renewal_discount_settings(self) -> dict:
        return {
            "enabled": self.get_setting("early_renewal_discount_enabled", "0") == "1",
            "days_before": int(self.get_setting("early_renewal_discount_days", "5") or 5),
            "percent": int(self.get_setting("early_renewal_discount_percent", "10") or 10),
        }


    def set_early_full_renewal_discount_settings(self, enabled: bool, days_before: int, percent: int):
        self.set_setting("early_renewal_discount_enabled", "1" if enabled else "0")
        self.set_setting("early_renewal_discount_days", str(int(days_before)))
        self.set_setting("early_renewal_discount_percent", str(int(percent)))

    # -----------------------------------------------------------------------
    # چت پشتیبانی (مینی‌اپ + بات، یکپارچه)
    # -----------------------------------------------------------------------

