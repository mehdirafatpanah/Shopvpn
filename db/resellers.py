from i18n import tr
from notification_i18n import send_telegram
# -*- coding: utf-8 -*-
from .constants import *

class ResellersMixin:
    def _seed_default_reseller_tiers(self, conn):
        for row in self.RESELLER_TIER_DEFAULTS:
            cols = list(row)
            conn.execute(
                f"INSERT OR IGNORE INTO reseller_tiers ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [row[c] for c in cols],
            )
        # مهاجرت یک‌باره: نسخه‌های قبلی نقره‌ای را به‌صورت پیش‌فرض خاموش داشتند؛
        # در سیستم چهارسطحی جدید هر چهار سطح باید قابل درخواست باشند. بعد از یک‌بار
        # اعمال، ادمین می‌تواند نقره‌ای را دوباره دستی غیرفعال کند.
        marker = conn.execute("SELECT value FROM settings WHERE key='reseller_tiers_four_level_v2' LIMIT 1").fetchone()
        if marker is None:
            conn.execute("UPDATE reseller_tiers SET is_enabled=1 WHERE code='silver'")
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('reseller_tiers_four_level_v2','1')")

        # در نسخه‌های قدیمی منوی انتخاب سطح نمایندگی وجود نداشت یا با مقدار 0
        # ذخیره شده بود؛ سیستم جدید چهارسطحی باید دکمه‌ی «درخواست نمایندگی»
        # را به‌صورت پیش‌فرض برای کاربر عادی نمایش دهد. این migration فقط یک‌بار
        # مقدار را فعال می‌کند و بعد از آن ادمین می‌تواند از پنل آن را خاموش کند.
        menu_marker = conn.execute("SELECT value FROM settings WHERE key='reseller_tiers_menu_v2' LIMIT 1").fetchone()
        if menu_marker is None:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('reseller_tiers_menu_enabled','1')")
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('reseller_tiers_menu_v2','1')")
        # انتقال درخواست‌های قدیمی دو جدول جداگانه به موتور واحد درخواست نمایندگی.
        # این کار فقط برای pendingهای قدیمی انجام می‌شود و پس از آن رکورد قدیمی
        # migrated می‌شود تا دوباره وارد سیستم نشود.
        conn.execute("""
            INSERT INTO reseller_requests
                (user_id, volume_gb, request_text, status, supply_model, bot_choice,
                 wants_web_panel, wants_miniapp, tier_code, commission_percent)
            SELECT r.user_id, 0, COALESCE(r.request_text, 'درخواست قدیمی منتقل‌شده'), 'pending_review',
                   CASE WHEN t.model='commission' THEN 'commission' ELSE 'discount' END, 'none', 0, 0,
                   r.tier_code, CASE WHEN t.model='commission' THEN COALESCE(t.commission_min, 10) ELSE NULL END
            FROM reseller_tier_requests r
            JOIN reseller_tiers t ON t.code=r.tier_code
            WHERE r.status='pending'
              AND NOT EXISTS (SELECT 1 FROM reseller_requests x
                              WHERE x.user_id=r.user_id AND x.tier_code=r.tier_code
                                AND x.status IN ('pending_review','awaiting_payment','awaiting_payment_review','awaiting_bot_info'))
        """)
        conn.execute("""
            UPDATE reseller_tier_requests SET status='migrated', updated_at=CURRENT_TIMESTAMP
            WHERE status='pending'
        """)
        conn.execute("""
            INSERT INTO reseller_requests
                (user_id, volume_gb, request_text, status, supply_model, bot_choice,
                 wants_web_panel, wants_miniapp, tier_code, commission_percent)
            SELECT r.user_id, 0, COALESCE(r.request_text, 'درخواست قدیمی منتقل‌شده'), 'pending_review',
                   'commission', 'none', 0, 0, 'bronze', r.proposed_percent
            FROM commission_reseller_requests r
            WHERE r.status='pending'
              AND NOT EXISTS (SELECT 1 FROM reseller_requests x
                              WHERE x.user_id=r.user_id AND x.tier_code='bronze'
                                AND x.status IN ('pending_review','awaiting_payment','awaiting_payment_review','awaiting_bot_info'))
        """)
        conn.execute("UPDATE commission_reseller_requests SET status='migrated', updated_at=CURRENT_TIMESTAMP WHERE status='pending'")


    def list_reseller_tiers(self, enabled_only: bool = False):
        query = "SELECT * FROM reseller_tiers"
        if enabled_only:
            query += " WHERE is_enabled=1"
        with self._get_conn() as conn:
            return conn.execute(query + " ORDER BY sort_order, code").fetchall()


    def get_reseller_tier(self, code: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_tiers WHERE code=?", (code,)).fetchone()


    def update_reseller_tier(self, code: str, **fields) -> bool:
        allowed = (
            set(self.RESELLER_TIER_TEXT_FIELDS) | set(self.RESELLER_TIER_FLAG_FIELDS) | set(self.RESELLER_TIER_INT_FIELDS)
        )
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"فیلد نامعتبر برای سطح نمایندگی: {', '.join(sorted(unknown))}")
        clean = {}
        for key, value in fields.items():
            if value is None and key in self.RESELLER_TIER_NULLABLE_FIELDS:
                clean[key] = None
            elif key in self.RESELLER_TIER_TEXT_FIELDS:
                clean[key] = str(value).strip()
            elif key in self.RESELLER_TIER_FLAG_FIELDS:
                clean[key] = 1 if int(value) else 0
            else:
                clean[key] = int(value)
        for key in self.RESELLER_TIER_PERCENT_FIELDS:
            if clean.get(key) is not None and not 0 <= clean[key] <= 100:
                raise ValueError(f"{key} باید بین ۰ تا ۱۰۰ باشد")
        if not clean:
            return False
        with self._get_conn() as conn:
            current = conn.execute("SELECT * FROM reseller_tiers WHERE code=?", (code,)).fetchone()
            if not current:
                return False
            low = clean["commission_min"] if "commission_min" in clean else current["commission_min"]
            high = clean["commission_max"] if "commission_max" in clean else current["commission_max"]
            if low is not None and high is not None and low > high:
                raise ValueError("حداقل کمیسیون نمی‌تواند از حداکثر بیشتر باشد")
            conn.execute(
                f"UPDATE reseller_tiers SET {', '.join(f'{k}=?' for k in clean)} WHERE code=?",
                [*clean.values(), code],
            )
            return True


    def get_user_reseller_tier(self, user_tg_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT reseller_tier FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
            return row["reseller_tier"] if row and row["reseller_tier"] else None


    def set_user_reseller_tier(self, user_tg_id: int, code, discount_percent: int = None, expires_at: str = None) -> bool:
        if discount_percent is not None:
            discount_percent = int(discount_percent)
            if not 1 <= discount_percent <= 100:
                raise ValueError("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد.")
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET reseller_tier=?, reseller_discount_percent=?, reseller_expires_at=? WHERE telegram_id=?",
                (code or None, discount_percent if code == "silver" else None, expires_at, user_tg_id),
            )
            return cur.rowcount > 0


    def get_reseller_membership(self, user_tg_id: int) -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT u.telegram_id, u.reseller_tier, u.reseller_expires_at, u.is_reseller, "
                "t.title, t.icon, t.membership_fee_toman, t.duration_days "
                "FROM users u LEFT JOIN reseller_tiers t ON t.code=u.reseller_tier WHERE u.telegram_id=?",
                (user_tg_id,),
            ).fetchone()
        return dict(row) if row else {}


    def activate_reseller_membership(self, user_tg_id: int, tier_code: str, admin_id: int = None, charge_fee: bool = True) -> dict:
        with self._get_conn() as conn:
            tier = conn.execute("SELECT * FROM reseller_tiers WHERE code=?", (tier_code,)).fetchone()
            user = conn.execute("SELECT reseller_expires_at, referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
            if not tier or not user:
                return {"ok": False, "reason": "not_found"}
            fee = int(tier["membership_fee_toman"] or 0)
            if charge_fee and fee > 0 and not self._charge_wallet_atomic(conn, user_tg_id, fee):
                return {"ok": False, "reason": "insufficient_balance", "fee": fee, "balance": int(user["referral_credit"] or 0)}
            duration_days = tier["duration_days"]
            new_expiry = None
            if duration_days is not None and int(duration_days) > 0:
                now = datetime.utcnow()
                base = now
                if user["reseller_expires_at"]:
                    try:
                        old_dt = datetime.fromisoformat(user["reseller_expires_at"])
                        if old_dt > now:
                            base = old_dt
                    except Exception:
                        pass
                new_expiry = (base + timedelta(days=int(duration_days))).isoformat()
            is_full = tier["model"] in ("fixed_product", "volume_credit")
            conn.execute(
                "UPDATE users SET reseller_tier=?, reseller_expires_at=?, reseller_reminder_sent='', is_reseller=? WHERE telegram_id=?",
                (tier_code, new_expiry, 1 if is_full else 0, user_tg_id),
            )
            return {"ok": True, "expires_at": new_expiry, "fee": fee, "duration_days": duration_days, "tier_code": tier_code}


    def renew_reseller_membership(self, user_tg_id: int, tier_code: str = None) -> dict:
        with self._get_conn() as conn:
            row = conn.execute("SELECT reseller_tier FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
        code = tier_code or (row["reseller_tier"] if row else None)
        if not code:
            return {"ok": False, "reason": "no_tier"}
        return self.activate_reseller_membership(user_tg_id, code, charge_fee=True)


    def claim_reseller_expiry_reminders(self, now: datetime = None, limit: int = 100) -> list:
        """یادآوری‌های ۷، ۳ و ۱ روز قبل را به‌صورت اتمیک claim می‌کند تا در
        اجرای دوباره یا چند worker پیام تکراری ارسال نشود."""
        now = now or datetime.utcnow()
        candidates = []
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id, reseller_tier, reseller_expires_at, reseller_reminder_sent "
                "FROM users WHERE reseller_tier IS NOT NULL AND reseller_expires_at IS NOT NULL "
                "AND reseller_expires_at>? ORDER BY reseller_expires_at LIMIT ?",
                (now.isoformat(), int(limit) * 4),
            ).fetchall()
            for row in rows:
                try:
                    expiry = datetime.fromisoformat(row["reseller_expires_at"])
                except Exception:
                    continue
                days_left = (expiry - now).total_seconds() / 86400
                target = next((d for d in (7, 3, 1) if days_left <= d and days_left > 0), None)
                if target is None:
                    continue
                sent = {x for x in (row["reseller_reminder_sent"] or "").split(",") if x}
                if str(target) in sent:
                    continue
                new_sent = ",".join(sorted(sent | {str(target)}, key=int))
                cur = conn.execute(
                    "UPDATE users SET reseller_reminder_sent=? WHERE telegram_id=? AND reseller_reminder_sent=?",
                    (new_sent, row["telegram_id"], row["reseller_reminder_sent"] or ""),
                )
                if cur.rowcount:
                    candidates.append({"user_id": row["telegram_id"], "tier_code": row["reseller_tier"], "expires_at": row["reseller_expires_at"], "days": target})
                    if len(candidates) >= limit:
                        break
        return candidates


    def process_reseller_expiries(self, now: datetime = None, limit: int = 100) -> list:
        now = now or datetime.utcnow()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id, reseller_tier FROM users WHERE reseller_tier IS NOT NULL AND reseller_expires_at IS NOT NULL "
                "AND reseller_expires_at<=? ORDER BY reseller_expires_at LIMIT ?",
                (now.isoformat(), int(limit)),
            ).fetchall()
        expired = []
        for row in rows:
            try:
                self.wipe_agent_state(row["telegram_id"])
                with self._get_conn() as conn:
                    conn.execute(
                        "UPDATE users SET is_reseller=0, reseller_expires_at=NULL, reseller_tier=NULL, reseller_discount_percent=NULL, "
                        "inline_reseller_enabled=0, reseller_credit_gb=0, reseller_supply_model='volume_credit', fixed_product_main_id=NULL, reseller_panel_id=NULL WHERE telegram_id=?",
                        (row["telegram_id"],),
                    )
                expired.append({"user_id": row["telegram_id"], "tier_code": row["reseller_tier"]})
            except Exception:
                logger.exception("پاکسازی نمایندگی منقضی کاربر %s ناموفق بود", row["telegram_id"])
        return expired

    async def reseller_expiry_loop(self, bot=None, interval: int = 3600):
        """worker ساعتی. اگر bot داده شود، یادآوری و پیام انقضا را هم ارسال می‌کند؛
        بدون bot فقط پاکسازی DB انجام می‌شود."""
        while True:
            try:
                if bot is not None:
                    reminders = await asyncio.to_thread(self.claim_reseller_expiry_reminders)
                    for item in reminders:
                        try:
                            tier = await asyncio.to_thread(self.get_reseller_tier, item["tier_code"])
                            label = f"{tier['icon']} {tier['title']}" if tier else item["tier_code"]
                            await send_telegram(bot, db, item["user_id"], tr(f"⏳ یادآوری انقضای نمایندگی\n\nسطح: {label}\nفقط {item['days']} روز تا پایان عضویت باقی مانده است.\nتاریخ انقضا: {item['expires_at']}\n\nبرای تمدید، هزینه‌ی دوره‌ی بعدی از کیف پول اعتباری کسر می‌شود."))
                        except Exception:
                            logger.exception("ارسال یادآوری نمایندگی به %s ناموفق بود", item["user_id"])
                expired = await asyncio.to_thread(self.process_reseller_expiries)
                if bot is not None:
                    for item in expired:
                        try:
                            await send_telegram(bot, db, item["user_id"], tr("⚠️ عضویت نمایندگی شما منقضی شد. تنظیمات و دسترسی‌های نمایندگی غیرفعال شدند؛ سرویس‌های ساخته‌شده‌ی شما حذف نشده‌اند. برای ادامه، دوباره درخواست/تمدید نمایندگی ثبت کنید."))
                        except Exception:
                            logger.exception("ارسال پیام انقضای نمایندگی به %s ناموفق بود", item["user_id"])
                    report_chat_id = self.get_setting("report_chat_id", "")
                    if report_chat_id:
                        for item in expired:
                            try:
                                await bot.send_message(report_chat_id, tr(f"⏰ انقضای نمایندگی | کاربر {item['user_id']} | سطح {item['tier_code']}"))
                            except Exception:
                                pass
            except Exception:
                logger.exception("reseller expiry loop failed")
            await asyncio.sleep(interval)


    def list_tier_members(self, code: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT telegram_id, username, first_name, reseller_discount_percent FROM users WHERE reseller_tier=? ORDER BY id DESC", (code,)
            ).fetchall()


    def list_tier_qty_discounts(self, code: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM reseller_tier_qty_discounts WHERE tier_code=? ORDER BY min_qty", (code,)
            ).fetchall()


    def set_tier_qty_discount(self, code: str, min_qty: int, discount_percent: int) -> int:
        min_qty, discount_percent = int(min_qty), int(discount_percent)
        if min_qty < 2:
            raise ValueError("حداقل تعداد برای پلکان باید ۲ یا بیشتر باشد")
        if not 1 <= discount_percent <= 100:
            raise ValueError("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد")
        with self._get_conn() as conn:
            if not conn.execute("SELECT 1 FROM reseller_tiers WHERE code=?", (code,)).fetchone():
                raise ValueError("سطح نامعتبر است")
            conn.execute(
                "INSERT INTO reseller_tier_qty_discounts (tier_code, min_qty, discount_percent) VALUES (?, ?, ?) "
                "ON CONFLICT(tier_code, min_qty) DO UPDATE SET discount_percent=excluded.discount_percent",
                (code, min_qty, discount_percent),
            )
            return conn.execute(
                "SELECT id FROM reseller_tier_qty_discounts WHERE tier_code=? AND min_qty=?", (code, min_qty)
            ).fetchone()["id"]


    def delete_tier_qty_discount(self, discount_id: int) -> bool:
        with self._get_conn() as conn:
            return conn.execute("DELETE FROM reseller_tier_qty_discounts WHERE id=?", (discount_id,)).rowcount > 0


    def get_tier_price_info(self, user_tg_id: int, unit_price: int, quantity: int = 1) -> dict:
        total = unit_price * quantity
        info = {"percent": 0, "amount": 0, "total": total, "total_after": total, "title": "", "icon": ""}
        with self._get_conn() as conn:
            user = conn.execute("SELECT reseller_tier, reseller_discount_percent FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
            if not user or not user["reseller_tier"]:
                return info
            tier = conn.execute("SELECT * FROM reseller_tiers WHERE code=?", (user["reseller_tier"],)).fetchone()
            if not tier or not tier["is_enabled"] or tier["model"] != "discount":
                return info
            bulk = conn.execute(
                "SELECT MAX(discount_percent) AS p FROM reseller_tier_qty_discounts WHERE tier_code=? AND min_qty<=?",
                (tier["code"], quantity),
            ).fetchone()["p"]
        percent = max(user["reseller_discount_percent"] or 0, tier["permanent_discount_percent"] or 0, bulk or 0)
        amount = total * percent // 100
        info.update(percent=percent, amount=amount, total_after=total - amount, title=tier["title"], icon=tier["icon"])
        return info


    def create_tier_request(self, user_tg_id: int, code: str) -> int:
        with self._get_conn() as conn:
            return conn.execute(
                "INSERT INTO reseller_tier_requests (user_id, tier_code, status) VALUES (?, ?, 'pending')",
                (user_tg_id, code),
            ).lastrowid


    def get_tier_request(self, request_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_tier_requests WHERE id=?", (request_id,)).fetchone()


    def get_pending_tier_request(self, user_tg_id: int, code: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM reseller_tier_requests WHERE user_id=? AND tier_code=? AND status='pending' "
                "ORDER BY id DESC LIMIT 1",
                (user_tg_id, code),
            ).fetchone()


    def list_tier_requests(self, status: str = None):
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM reseller_tier_requests WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            return conn.execute("SELECT * FROM reseller_tier_requests ORDER BY id DESC").fetchall()


    def approve_tier_request(self, request_id: int, admin_id: int) -> dict:
        req = self.get_tier_request(request_id)
        if not req or req["status"] != "pending":
            return {"ok": False, "reason": "invalid"}
        with self._get_conn() as conn:
            claimed = conn.execute(
                "UPDATE reseller_tier_requests SET status='processing', reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                (admin_id, request_id),
            ).rowcount
        if not claimed:
            return {"ok": False, "reason": "race"}
        try:
            current = self.get_agent_tier(req["user_id"])
            if current and current != req["tier_code"]:
                self.switch_agent_tier(req["user_id"], req["tier_code"])
            result = self.activate_reseller_membership(req["user_id"], req["tier_code"], admin_id=admin_id, charge_fee=True)
            if not result.get("ok"):
                with self._get_conn() as conn:
                    conn.execute("UPDATE reseller_tier_requests SET status='pending', reviewed_by=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='processing'", (request_id,))
                return result
            with self._get_conn() as conn:
                conn.execute("UPDATE reseller_tier_requests SET status='approved', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='processing'", (request_id,))
            return result
        except Exception:
            with self._get_conn() as conn:
                conn.execute("UPDATE reseller_tier_requests SET status='pending', reviewed_by=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='processing'", (request_id,))
            raise


    def get_agent_tier(self, user_tg_id: int):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT reseller_tier, reseller_expires_at, is_reseller, inline_reseller_enabled, reseller_supply_model "
                "FROM users WHERE telegram_id=?",
                (user_tg_id,),
            ).fetchone()
        if not row:
            return None
        if row["reseller_expires_at"]:
            try:
                if datetime.fromisoformat(row["reseller_expires_at"]) <= datetime.utcnow():
                    return None
            except Exception:
                pass
        if row["reseller_tier"]:
            return row["reseller_tier"]
        if row["is_reseller"]:
            return "gold" if row["reseller_supply_model"] == "fixed_product" else "vip"
        if row["inline_reseller_enabled"]:
            return "bronze"
        return None


    @staticmethod
    def _remove_reseller_db_files(path: str) -> bool:
        removed_all = True
        for suffix in ("", "-wal", "-shm", ".fsm.sqlite3", ".fsm.sqlite3-wal", ".fsm.sqlite3-shm"):
            target = path + suffix
            try:
                if os.path.exists(target):
                    os.remove(target)
            except OSError:
                removed_all = False
        return removed_all


    def switch_agent_tier(self, user_tg_id: int, new_code: str) -> dict:
        current = self.get_agent_tier(user_tg_id)
        if current is None or current == new_code:
            return {"changed": False, "previous": current}
        result = self.wipe_agent_state(user_tg_id)
        result.update(changed=True, previous=current)
        return result


    def reject_tier_request(self, request_id: int, admin_id: int, reason: str = None) -> bool:
        with self._get_conn() as conn:
            return conn.execute(
                "UPDATE reseller_tier_requests SET status='rejected', reviewed_by=?, reject_reason=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                (admin_id, reason, request_id),
            ).rowcount > 0


    def get_reseller_fixed_products(self):
        """محصولات مجاز برای مدل تامین «محصول آماده» در فرم درخواست نمایندگی
        (بند ۶ اسپک)؛ اگر ادمین لیستی انتخاب نکرده باشد (تنظیم خالی)، همه‌ی محصولات فعال برگردانده می‌شوند."""
        raw = (self.get_setting("reseller_fixed_product_ids", "") or "").strip()
        products = [p for p in self.get_all_products() if p["is_active"] and p["is_auto_provision"]]
        if not raw:
            return products
        allowed_ids = {int(x) for x in raw.split(",") if x.strip().isdigit()}
        return [p for p in products if p["id"] in allowed_ids]


    def get_reseller_product_inventory(self, reseller_id: int):
        """موجودی محصولات نماینده همراه با مشخصات محصول."""
        with self._get_conn() as conn:
            return conn.execute(
                """SELECT rpc.*, p.name, p.price, p.duration_days, p.description, p.is_active,
                          p.is_auto_provision, p.auto_provision_volume_gb, p.provision_server_id,
                          c.name AS category_name
                   FROM reseller_product_credit rpc
                   JOIN products p ON p.id=rpc.product_id
                   LEFT JOIN categories c ON c.id=p.category_id
                   WHERE rpc.reseller_id=? ORDER BY rpc.qty_remaining DESC, rpc.id""",
                (reseller_id,),
            ).fetchall()


    def get_reseller_refund_base(self, custom_config_id: int, user_tg_id: int) -> dict:
        """پایه‌ی برگشت اعتبار هنگام حذف کانفیگی که خود نماینده ساخته؛ سهم مصرف و مدل اعتبار جدا اعمال می‌شود."""
        window = max(int(self.get_setting("svc_refund_window_hours", "24") or 0), 0)
        none = {"eligible": False, "reason": "", "window_hours": window}
        if window <= 0:
            return none
        with self._get_conn() as conn:
            cc = self._refund_candidate(conn, custom_config_id, user_tg_id, "reseller")
        if not cc:
            return none
        if self._refund_expired(cc, window):
            return {**none, "reason": "window"}
        return {
            "eligible": True, "reason": "", "window_hours": window,
            "volume_gb": int(cc["volume_gb"]), "reseller_product_id": cc["reseller_product_id"],
        }


    def enable_inline_reseller(self, owner_tg_id: int, percent: int = None):
        """این نماینده گزینه‌ی «لینک اختصاصی داخل بات اصلی» را دارد؛ یعنی لینک
        ref اختصاصی‌اش (resref_<id>) و صفحه‌ی آمار برایش فعال می‌شود.
        percent: درصد کمیسیونِ اختصاصیِ همین نماینده (مستقل از بقیه‌ی نماینده‌ها و
        مستقل از تنظیم سراسری reseller_inline_commission_percent). اگر داده نشود،
        مقدار فعلی (در صورت وجود) دست‌نخورده می‌ماند - برای سازگاری با فراخوانی‌های
        قدیمی که هنوز percent نمی‌فرستند."""
        with self._get_conn() as conn:
            if percent is not None:
                conn.execute(
                    "UPDATE users SET inline_reseller_enabled=1, inline_reseller_commission_percent=? "
                    "WHERE telegram_id=?",
                    (int(percent), owner_tg_id),
                )
            else:
                conn.execute("UPDATE users SET inline_reseller_enabled=1 WHERE telegram_id=?", (owner_tg_id,))
            conn.execute("UPDATE users SET reseller_tier=NULL WHERE telegram_id=?", (owner_tg_id,))


    def set_inline_reseller_commission_percent(self, owner_tg_id: int, percent: int):
        """تغییر درصد کمیسیونِ یک نماینده‌ی کمیسیونیِ از قبل فعال (بدون تغییر
        وضعیت فعال/غیرفعال بودنش)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET inline_reseller_commission_percent=? WHERE telegram_id=?",
                (int(percent), owner_tg_id),
            )


    def disable_inline_reseller(self, owner_tg_id: int):
        """رفع باگ: قبلاً هیچ تابع متقابلی برای enable_inline_reseller وجود نداشت -
        یعنی نماینده‌ی «لینک اختصاصی داخل بات اصلی» بعد از فعال‌شدن، هیچ‌وقت از هیچ
        مسیر ادمینی (حذف نماینده، پاک‌سازی کاربران یتیم) واقعاً غیرفعال نمی‌شد و
        لینک/کارمزدش برای همیشه فعال می‌ماند. این فقط لینک را می‌بندد (لینک تازه
        دیگر owner_reseller_id جدید ثبت نمی‌کند و _apply_inline_reseller_commission
        دیگر کارمزدی واریز نمی‌کند)؛ عمداً owner_reseller_id مشتریانی که قبلاً به
        این نماینده وصل شده‌اند را پاک نمی‌کند - چون آن یک برچسب تاریخی/گزارشی
        است، نه یک اجازه‌ی فعال، و می‌تواند اگر بعداً همین نماینده دوباره فعال شد
        بدون گم‌شدن سابقه‌ی مشتریانش برگردد."""
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET inline_reseller_enabled=0 WHERE telegram_id=?", (owner_tg_id,))

    # -------------------------------------------------------------------
    # درخواست‌های نمایندگی کمیسیونی (مستقل کامل از reseller_requests حجمی):
    # کاربر یک درصد پیشنهادی می‌فرستد، ادمین تایید (با همان یا درصد دیگر) یا رد
    # (با ذکر علت) می‌کند. تایید = enable_inline_reseller با همان درصد.
    # -------------------------------------------------------------------


    def create_commission_reseller_request(self, user_id: int, proposed_percent: int, request_text: str = None):
        """یک درخواست pending جدید می‌سازد. اگر کاربر همین الان یک درخواست pending
        دیگر داشته باشد یا از قبل نماینده‌ی کمیسیونی فعال باشد، None برمی‌گرداند."""
        if self.is_inline_reseller(user_id):
            return None
        if self.get_pending_commission_reseller_request_for_user(user_id):
            return None
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO commission_reseller_requests (user_id, proposed_percent, request_text) "
                "VALUES (?, ?, ?)",
                (user_id, int(proposed_percent), request_text),
            )
            return cur.lastrowid


    def get_pending_commission_reseller_request_for_user(self, user_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM commission_reseller_requests WHERE user_id=? AND status='pending' "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()


    def get_commission_reseller_request(self, request_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM commission_reseller_requests WHERE id=?", (request_id,)
            ).fetchone()


    def list_commission_reseller_requests(self, status: str = "pending"):
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM commission_reseller_requests WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            return conn.execute(
                "SELECT * FROM commission_reseller_requests ORDER BY id DESC"
            ).fetchall()


    def approve_commission_reseller_request(self, request_id: int, percent: int, reviewed_by: int = None):
        """اتمیک: فقط اگر درخواست هنوز pending باشد تایید می‌شود (WHERE status='pending')
        تا دو ادمین هم‌زمان دوبار تاییدش نکنند. در صورت موفقیت، خودِ ردیف درخواست
        (شامل user_id) برمی‌گردد تا caller نماینده را فعال و به او اطلاع بدهد؛
        در غیر این صورت None."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE commission_reseller_requests SET status='approved', approved_percent=?, "
                "reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                (int(percent), reviewed_by, request_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM commission_reseller_requests WHERE id=?", (request_id,)
            ).fetchone()
        if row:
            self.switch_agent_tier(row["user_id"], "bronze")
            self.enable_inline_reseller(row["user_id"], int(percent))
            self.set_user_reseller_tier(row["user_id"], "bronze")
        return row


    def reject_commission_reseller_request(self, request_id: int, reason: str, reviewed_by: int = None):
        """اتمیک، مشابه approve_commission_reseller_request."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE commission_reseller_requests SET status='rejected', reject_reason=?, "
                "reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                (reason, reviewed_by, request_id),
            )
            if cur.rowcount == 0:
                return None
            return conn.execute(
                "SELECT * FROM commission_reseller_requests WHERE id=?", (request_id,)
            ).fetchone()


    def is_inline_reseller(self, user_tg_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT inline_reseller_enabled FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return bool(row and row["inline_reseller_enabled"])


    def set_owner_reseller_id(self, user_tg_id: int, owner_tg_id: int):
        """برچسب دائمی «این مشتری مالِ کدام نماینده‌ی لینک‌محور است» — مثل
        set_referred_by، فقط بار اول ثبت می‌شود و دیگر تغییر نمی‌کند، و کاملاً
        مستقل از سیستم referred_by (یک کاربر می‌تواند هم‌زمان توسط یک دوست
        referred شده باشد و هم مشتریِ یک نماینده‌ی لینک‌محور باشد)."""
        if user_tg_id == owner_tg_id:
            return
        with self._get_conn() as conn:
            owner_exists = conn.execute(
                "SELECT 1 FROM users WHERE telegram_id=? AND inline_reseller_enabled=1", (owner_tg_id,)
            ).fetchone()
            if owner_exists:
                # رفع باگ: قبلاً اینجا اول با یک SELECT جدا چک می‌شد که
                # owner_reseller_id هنوز NULL است و بعد یک UPDATE بدون قید انجام
                # می‌شد؛ بین این دو مرحله هیچ قفلی نبود، پس دو /start تقریباً
                # هم‌زمان با دو لینک نماینده‌ی متفاوت (مثلاً باز شدن دوباره‌ی همان
                # دیپ‌لینک در دو تب/دستگاه) می‌توانستند هر دو از NULL بودن مطمئن
                # شوند و آخرین UPDATE، نتیجه‌ی اولی را بی‌سروصدا رونویسی کند. حالا
                # خودِ UPDATE با WHERE owner_reseller_id IS NULL اتمیک است.
                conn.execute(
                    "UPDATE users SET owner_reseller_id=? WHERE telegram_id=? AND owner_reseller_id IS NULL",
                    (owner_tg_id, user_tg_id),
                )


    def _apply_inline_reseller_commission(self, buyer_tg_id: int, paid_amount: int):
        """روی هر خرید تسویه‌شده (نه فقط اولین خرید) از مشتریانی که owner_reseller_id
        دارند، درصدی کارمزد به کیف پول (referral_credit) خودِ نماینده اضافه می‌شود.
        این تابع را reward_referrer_if_first_purchase صدا می‌زند تا نیازی به تغییر
        هیچ‌کدام از ~۱۷ نقطه‌ی تکمیل سفارش در کل پروژه (بات، پنل ادمین، مینی‌اپ،
        وبهوک درگاه‌ها) نباشد."""
        if not paid_amount or paid_amount <= 0:
            return
        if self.get_setting("reseller_inline_commission_enabled", "1") != "1":
            return
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT owner_reseller_id FROM users WHERE telegram_id=?", (buyer_tg_id,)
            ).fetchone()
            owner_id = row["owner_reseller_id"] if row else None
        if not owner_id:
            return
        # رفع باگ: قبلاً اینجا فقط owner_reseller_id مشتری چک می‌شد، نه اینکه خودِ
        # نماینده هنوز inline_reseller_enabled باشد یا نه. یعنی حتی بعد از اینکه
        # ادمین با disable_inline_reseller نمایندگی را می‌بست، مشتریانی که قبلاً
        # به او وصل شده بودند همچنان تا ابد برایش کارمزد تولید می‌کردند - چون این
        # برچسبِ owner_reseller_id عمداً هنگام غیرفعال‌سازی پاک نمی‌شود (برای حفظ
        # سابقه/امکان فعال‌سازی مجدد بدون گم‌شدن مشتریان). این چک آن رخنه را می‌بندد.
        if not self.is_inline_reseller(owner_id):
            return
        # درصد کمیسیون حالا مخصوص هر نماینده است (نه یک تنظیم سراسری مشترک بین
        # همه)؛ فقط برای نماینده‌های قدیمی که از مسیر قبلی (بدون درصد اختصاصی)
        # فعال شده بودند، تنظیم سراسری reseller_inline_commission_percent به‌عنوان
        # fallback خوانده می‌شود.
        with self._get_conn() as conn:
            prow = conn.execute(
                "SELECT inline_reseller_commission_percent FROM users WHERE telegram_id=?", (owner_id,)
            ).fetchone()
        own_percent = prow["inline_reseller_commission_percent"] if prow else None
        if own_percent is not None:
            percent = int(own_percent)
        else:
            percent = int(self.get_setting("reseller_inline_commission_percent", "10") or 0)
        if percent <= 0:
            return
        commission = (paid_amount * percent) // 100
        if commission <= 0:
            return
        self.add_wallet_credit(owner_id, commission, "reseller_commission", "کارمزد فروش مشتریان لینک اختصاصی")
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO reseller_inline_commission_log (owner_reseller_id, buyer_id, paid_amount, commission_amount) "
                "VALUES (?, ?, ?, ?)",
                (owner_id, buyer_tg_id, paid_amount, commission),
            )


    def get_inline_reseller_stats(self, owner_tg_id: int) -> dict:
        default_percent = int(self.get_setting("reseller_inline_commission_percent", "10") or 0)
        with self._get_conn() as conn:
            customers = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE owner_reseller_id=?", (owner_tg_id,)
            ).fetchone()["c"]
            row = conn.execute(
                "SELECT COUNT(*) cnt, COALESCE(SUM(commission_amount),0) total "
                "FROM reseller_inline_commission_log WHERE owner_reseller_id=?",
                (owner_tg_id,),
            ).fetchone()
            prow = conn.execute(
                "SELECT inline_reseller_commission_percent FROM users WHERE telegram_id=?", (owner_tg_id,)
            ).fetchone()
            own_percent = prow["inline_reseller_commission_percent"] if prow else None
            percent = int(own_percent) if own_percent is not None else default_percent
            return {
                "customers": customers, "paid_orders": row["cnt"], "total_commission": row["total"],
                "percent": percent,
            }


    def list_inline_resellers(self):
        """برای نمایش در پنل ادمین (بند ۴ از موارد باقی‌مانده): لیست همه‌ی
        نماینده‌های «لینک اختصاصی داخل بات اصلی» به‌همراه آمار مشتری/کارمزدشان."""
        default_percent = int(self.get_setting("reseller_inline_commission_percent", "10") or 0)
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT u.telegram_id, u.username, u.first_name, u.referral_credit, "
                "u.inline_reseller_commission_percent, "
                "(SELECT COUNT(*) FROM users c WHERE c.owner_reseller_id=u.telegram_id) AS customers, "
                "(SELECT COUNT(*) FROM reseller_inline_commission_log l WHERE l.owner_reseller_id=u.telegram_id) AS paid_orders, "
                "(SELECT COALESCE(SUM(commission_amount),0) FROM reseller_inline_commission_log l WHERE l.owner_reseller_id=u.telegram_id) AS total_commission "
                "FROM users u WHERE u.inline_reseller_enabled=1 ORDER BY total_commission DESC"
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["percent"] = (
                    int(d["inline_reseller_commission_percent"])
                    if d["inline_reseller_commission_percent"] is not None
                    else default_percent
                )
                result.append(d)
            return result


    def get_reseller_owner_display_name(self, tg_id: int) -> str:
        """نام نمایشی یک نماینده برای ستون reseller_bots.owner_name، وقتی خودِ کاربر
        (نه ادمین با تایپ دستی) درخواست نمایندگی داده و اسم جداگانه‌ای از او پرسیده
        نشده است. قبلاً این‌جا به‌اشتباه متن آزادِ توضیحِ درخواست (request_text)
        گذاشته می‌شد که اسم واقعی کسی نیست و در لیست ادمین گیج‌کننده بود.
        اولویت: نام‌ونام‌خانوادگی/یوزرنیمِ ثبت‌شده در users، وگرنه خودِ آیدی عددی."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT first_name, username FROM users WHERE telegram_id=?", (tg_id,)
            ).fetchone()
        name = (row["first_name"] or "").strip() if row else ""
        username = (row["username"] or "").strip() if row else ""
        if name and username:
            return f"{name} (@{username})"
        if name:
            return name
        if username:
            return f"@{username}"
        return f"کاربر {tg_id}"


    def register_reseller_bot(self, bot_token: str, bot_username: str, owner_telegram_id: int, owner_name: str,
                               db_path: str, has_live_bot: int = 1) -> int:
        with self._get_conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO reseller_bots (bot_token, bot_username, owner_telegram_id, owner_name, db_path, has_live_bot) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (bot_token, bot_username, owner_telegram_id, owner_name, db_path, 1 if has_live_bot else 0),
                )
            except sqlite3.IntegrityError:
                # رفع باگ: قبلاً این استثنا کنترل‌نشده تا هندلر بالا می‌رفت. چون چکِ
                # get_reseller_bot_by_token در لحظه‌ی ورود توکن (چند مرحله قبل‌تر از
                # اینجا) و این INSERT دو عملیات جدا هستند، اگر دقیقاً همان توکن در این
                # فاصله توسط یک ثبت‌نام دیگر مصرف شود، فقط قید UNIQUE ستون bot_token
                # جلوی دوباره‌ثبت‌شدن را می‌گیرد؛ اینجا آن را به خطای قابل‌فهم تبدیل می‌کنیم.
                raise DuplicateBotTokenError(bot_token)
            return cur.lastrowid


    def get_reseller_bot_by_token(self, bot_token: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_bots WHERE bot_token=?", (bot_token,)).fetchone()


    def list_reseller_bots(self, active_only: bool = False):
        with self._get_conn() as conn:
            if active_only:
                return conn.execute("SELECT * FROM reseller_bots WHERE is_active=1 ORDER BY id").fetchall()
            return conn.execute("SELECT * FROM reseller_bots ORDER BY id").fetchall()


    def get_reseller_sales_map(self):
        """برای هر نماینده‌ی اعتباری، تعداد و مجموع حجم کانفیگ‌هایی که از اعتبار
        حجمی خودش برای مشتری‌هایش ساخته (source='reseller' در custom_configs)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, COUNT(*) cnt, COALESCE(SUM(volume_gb),0) gb "
                "FROM custom_configs WHERE source='reseller' GROUP BY user_id"
            ).fetchall()
        return {r["user_id"]: {"configs": r["cnt"], "volume_gb": r["gb"]} for r in rows}


    def get_reseller_bot(self, bot_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_bots WHERE id=?", (bot_id,)).fetchone()


    def get_reseller_bot_by_slug(self, slug: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_bots WHERE link_slug=?", (slug,)).fetchone()


    def set_reseller_link_slug(self, bot_id: int, slug: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE reseller_bots SET link_slug=? WHERE id=?", (slug, bot_id))


    def toggle_reseller_bot(self, bot_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_active FROM reseller_bots WHERE id=?", (bot_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE reseller_bots SET is_active=? WHERE id=?", (0 if row["is_active"] else 1, bot_id)
                )


    def edit_reseller_bot(self, bot_id: int, owner_telegram_id: int = None, owner_name: str = None,
                           bot_token: str = None, bot_username: str = None):
        fields, values = [], []
        if owner_telegram_id is not None:
            fields.append("owner_telegram_id=?"); values.append(owner_telegram_id)
        if owner_name is not None:
            fields.append("owner_name=?"); values.append(owner_name)
        if bot_token is not None:
            fields.append("bot_token=?"); values.append(bot_token)
        if bot_username is not None:
            fields.append("bot_username=?"); values.append(bot_username)
        if not fields:
            return
        values.append(bot_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE reseller_bots SET {', '.join(fields)} WHERE id=?", values)


    def delete_reseller_bot(self, bot_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM reseller_bots WHERE id=?", (bot_id,))


    def transfer_reseller_ownership(self, bot_id: int, new_owner_telegram_id: int, new_owner_name: str = None) -> bool:
        """رفع باگ: edit_reseller_bot فقط owner_telegram_id/owner_name را روی خودِ
        ردیف reseller_bots عوض می‌کرد - یعنی صرفاً یک برچسب نمایشی در پنل ادمین.
        سه جای دیگر که «مالک واقعی» این نماینده از آن‌ها خوانده می‌شود دست‌نخورده
        می‌ماندند: فلگ‌های is_reseller/reseller_credit_gb/reseller_supply_model/
        fixed_product_main_id/reseller_panel_id روی رکورد کاربر *قدیمی* در همین
        دیتابیس اصلی، و مهم‌تر از همه role='owner' در جدول admins دیتابیسِ محلیِ
        خودِ بات نماینده - که reseller_auto_provision.get_owner_telegram_id() از
        همان‌جا می‌خواند. نتیجه این بود که بعد از «تغییر مالک» در پنل وب، اسم مالک
        جدید فقط در لیست دیده می‌شد ولی عملاً بات همچنان مالک قبلی را می‌شناخت و
        اعتبار حجمی هم هنوز از حساب او کسر می‌شد. این تابع هر سه‌جا را با هم عوض
        می‌کند تا مالکیت واقعاً و به‌طور کامل منتقل شود."""
        bot_row = self.get_reseller_bot(bot_id)
        if not bot_row:
            return False
        old_owner = bot_row["owner_telegram_id"]
        if old_owner == new_owner_telegram_id:
            self.edit_reseller_bot(bot_id, owner_name=new_owner_name)
            return True

        with self._get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (new_owner_telegram_id,))
            old_row = conn.execute(
                "SELECT is_reseller, reseller_credit_gb, reseller_supply_model, fixed_product_main_id, "
                "reseller_panel_id FROM users WHERE telegram_id=?", (old_owner,),
            ).fetchone()
            if old_row:
                conn.execute(
                    "UPDATE users SET is_reseller=?, reseller_credit_gb=?, reseller_supply_model=?, "
                    "fixed_product_main_id=?, reseller_panel_id=? WHERE telegram_id=?",
                    (old_row["is_reseller"], old_row["reseller_credit_gb"], old_row["reseller_supply_model"],
                     old_row["fixed_product_main_id"], old_row["reseller_panel_id"], new_owner_telegram_id),
                )
                conn.execute(
                    "UPDATE users SET is_reseller=0, reseller_credit_gb=0, reseller_supply_model='volume_credit', "
                    "fixed_product_main_id=NULL, reseller_panel_id=NULL WHERE telegram_id=?",
                    (old_owner,),
                )
            conn.execute(
                "UPDATE reseller_bots SET owner_telegram_id=?, owner_name=COALESCE(?, owner_name) WHERE id=?",
                (new_owner_telegram_id, new_owner_name, bot_id),
            )

        # هم‌گام‌سازی role='owner' در دیتابیس محلی خودِ بات نماینده (اگر بات زنده/
        # دیتابیس مجزا دارد؛ برای resellerهای has_live_bot=0 هم همین db_path معتبر
        # و init_db شده است، پس بدون شرط اضافه امتحان می‌شود).
        try:
            from config import resolve_db_path
            local_path = resolve_db_path(bot_row["db_path"])
            if os.path.exists(local_path):
                local_db = type(self)(local_path)
                with local_db._get_conn() as lconn:
                    lconn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (new_owner_telegram_id,))
                    lconn.execute("UPDATE admins SET role='owner' WHERE telegram_id=?", (new_owner_telegram_id,))
                    lconn.execute(
                        "UPDATE admins SET role='admin' WHERE telegram_id=? AND role='owner'", (old_owner,)
                    )
        except Exception:
            logger.exception(
                "هم‌گام‌سازی مالک جدید (%s) روی دیتابیس محلی نماینده #%s ناموفق بود؛ "
                "reseller_bots.owner_telegram_id عوض شد ولی ممکن است بات هنوز مالک قبلی را بشناسد.",
                new_owner_telegram_id, bot_id,
            )
        return True

    # ---------------------------------------------------- web panel (reseller) --


    def set_reseller_miniapp_enabled(self, bot_id: int, enabled: bool):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reseller_bots SET miniapp_enabled=? WHERE id=?", (1 if enabled else 0, bot_id)
            )


    def list_orphaned_reseller_users(self):
        """کاربرانی که پرچم/اعتبار/پنل نمایندگی روی رکوردشان مانده ولی هیچ
        بات نمایندگی‌ای (حتی غیرفعال) برایشان در reseller_bots ثبت نیست."""
        with self._get_conn() as conn:
            return conn.execute(
                """
                SELECT telegram_id, first_name, username, is_reseller,
                       reseller_credit_gb, reseller_panel_id
                FROM users
                WHERE (is_reseller = 1 OR reseller_credit_gb > 0 OR reseller_panel_id IS NOT NULL)
                  AND telegram_id NOT IN (SELECT owner_telegram_id FROM reseller_bots)
                ORDER BY telegram_id
                """
            ).fetchall()


    def purge_reseller_leftovers(self, user_tg_id: int):
        """پرچم نماینده‌بودن، اعتبار حجمی و پنل اختصاصی کاربر را در دیتابیس
        اصلی صفر/خالی می‌کند؛ برای پاکسازی کامل رد پای یک نمایندگی حذف‌شده.

        رفع باگ: قبلاً reseller_supply_model/fixed_product_main_id اینجا دست‌نخورده
        می‌ماندند. اگر همین کاربر بعداً دوباره نماینده شود (مثلاً این‌بار با مدل
        اعتبار حجمی)، get_reseller_supply همچنان مدل/محصولِ نمایندگیِ *قبلی* (که
        دیگر برایش reseller_product_credit ای وجود ندارد) را برمی‌گرداند و
        provision_auto_config او را اشتباهاً «مدل محصول آماده با موجودی صفر»
        می‌دید - یعنی هر خریدی با «موجودی محصول کافی نیست» شکست می‌خورد، درحالی‌که
        عملاً اعتبار حجمی جدیدش دست‌نخورده و بلااستفاده می‌ماند. حالا این دو فیلد
        هم به مقدار پیش‌فرض (اعتبار حجمی، بدون محصول ثابت) برمی‌گردند.

        رفع باگ: این تابع inline_reseller_enabled را دست‌نخورده می‌گذاشت، پس یک
        نماینده‌ی «لینک اختصاصی داخل بات اصلی» (که اصلاً ممکن است هیچ ردیفی در
        reseller_bots هم نداشته باشد - وقتی نه پنل وب نه مینی‌اپ خواسته) حتی بعد
        از پاک‌سازی کامل از صفحه‌ی «کاربران یتیم» همچنان لینک/کارمزدش برای همیشه
        فعال می‌ماند و هیچ راهی برای بستن آن وجود نداشت. الان این‌جا هم
        inline_reseller_enabled=0 می‌شود."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET is_reseller=0, reseller_credit_gb=0, reseller_panel_id=NULL, "
                "reseller_supply_model='volume_credit', fixed_product_main_id=NULL, "
                "inline_reseller_enabled=0 "
                "WHERE telegram_id=?",
                (user_tg_id,),
            )


    def is_reseller(self, user_tg_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT is_reseller FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return bool(row and row["is_reseller"])


    def get_reseller_credit(self, user_tg_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT reseller_credit_gb FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return row["reseller_credit_gb"] if row else 0


    def set_reseller_supply_model(self, user_tg_id: int, model: str, product_id: int = None):
        """مدل تامین نمایندگی (بند ۳.۳ اسپک) روی ردیف کاربر در دیتابیس اصلی ذخیره
        می‌شود، تا reseller_auto_provision.py که از داخل بات نمایندگی (دیتابیس جدا)
        به این دیتابیس وصل می‌شود، بدون نیاز به هیچ جدول/تنظیم دیگری بفهمد این
        نماینده باید از reseller_credit_gb مصرف کند یا از reseller_product_credit."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET reseller_supply_model=?, fixed_product_main_id=? WHERE telegram_id=?",
                (model, product_id, user_tg_id),
            )


    def get_reseller_supply(self, user_tg_id: int) -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT reseller_supply_model, fixed_product_main_id FROM users WHERE telegram_id=?",
                (user_tg_id,),
            ).fetchone()
            if not row:
                return {"model": "volume_credit", "product_id": None}
            return {"model": row["reseller_supply_model"] or "volume_credit", "product_id": row["fixed_product_main_id"]}


    def set_reseller_status(self, user_tg_id: int, enabled: bool):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET is_reseller=? WHERE telegram_id=?", (1 if enabled else 0, user_tg_id)
            )
            if enabled:
                conn.execute("UPDATE users SET reseller_tier=NULL WHERE telegram_id=?", (user_tg_id,))


    def adjust_reseller_credit(self, user_tg_id: int, delta_gb: int, admin_id: int = None, reason: str = None):
        """شارژ/تنظیم اعتبار نماینده با تضمین اینکه موجودی هرگز منفی نشود.

        delta مثبت = شارژ، delta منفی = کسر. کسر منفی به‌صورت اتمیک انجام می‌شود
        تا پنل وب/بات نتوانند با مقدار نامعتبر یا درخواست‌های هم‌زمان اعتبار را
        زیر صفر ببرند.
        """
        if not isinstance(delta_gb, int) or delta_gb == 0:
            raise ValueError("delta_gb باید عدد صحیح و غیرصفر باشد")
        with self._get_conn() as conn:
            if delta_gb < 0:
                cur = conn.execute(
                    "UPDATE users SET reseller_credit_gb = reseller_credit_gb + ? "
                    "WHERE telegram_id=? AND reseller_credit_gb >= ?",
                    (delta_gb, user_tg_id, -delta_gb),
                )
                if cur.rowcount == 0:
                    raise ValueError("اعتبار نماینده برای این کسر کافی نیست")
            else:
                cur = conn.execute(
                    "UPDATE users SET reseller_credit_gb = reseller_credit_gb + ? WHERE telegram_id=?",
                    (delta_gb, user_tg_id),
                )
                if cur.rowcount == 0:
                    raise ValueError("نماینده یافت نشد")
            conn.execute(
                "INSERT INTO reseller_credit_log (user_id, delta_gb, reason, admin_id) VALUES (?, ?, ?, ?)",
                (user_tg_id, delta_gb, reason, admin_id),
            )


    def consume_reseller_credit(self, user_tg_id: int, amount_gb, reason: str = None, admin_id: int = None) -> bool:
        """کسر اتمیک اعتبار حجمی نماینده (مدل volume_credit)؛ درست مثل
        consume_reseller_product_credit برای مدل fixed_product. برخلاف
        adjust_reseller_credit با دلتای منفی (که فقط یک UPDATE بدون قید بود)، اینجا
        کسر فقط وقتی واقعاً انجام می‌شود که باقیمانده کافی باشد - همه در یک کوئری
        اتمیک (UPDATE ... WHERE reseller_credit_gb >= ?). این جلوی رفتن اعتبار به
        منفی زیر بار هم‌زمان (مثلاً دو خرید مشتریِ یک نماینده در یک لحظه) را می‌گیرد؛
        قبلاً چک «کافی بودن اعتبار» در پایتون و خودِ کسر دو مرحله‌ی جدا بودند و هیچ
        قفلی بین‌شان نبود. اگر باقیمانده کافی نباشد، هیچ تغییری اعمال نمی‌شود و
        False برمی‌گردد تا صدازننده rollback (پاک‌کردن اکانت واقعی روی پنل) را انجام دهد."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET reseller_credit_gb = reseller_credit_gb - ? "
                "WHERE telegram_id=? AND reseller_credit_gb >= ?",
                (amount_gb, user_tg_id, amount_gb),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "INSERT INTO reseller_credit_log (user_id, delta_gb, reason, admin_id) VALUES (?, ?, ?, ?)",
                    (user_tg_id, -amount_gb, reason, admin_id),
                )
            return cur.rowcount > 0


    def get_reseller_credit_log(self, user_tg_id: int, limit: int = 20):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM reseller_credit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_tg_id, limit),
            ).fetchall()

    # ------------------------------------------------------------------
    # موجودی محصول نمایندگی (مدل تامین «محصول آماده»)
    # ------------------------------------------------------------------


    def adjust_reseller_product_credit(self, reseller_id: int, product_id: int, delta: int,
                                        admin_id: int = None, reason: str = None) -> int:
        """تنظیم اتمیک موجودی یک محصول نماینده. delta مثبت=شارژ، منفی=کسر."""
        if not isinstance(delta, int) or delta == 0:
            raise ValueError("delta باید عدد صحیح غیرصفر باشد")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT qty_remaining FROM reseller_product_credit WHERE reseller_id=? AND product_id=?",
                (reseller_id, product_id),
            ).fetchone()
            current = int(row["qty_remaining"]) if row else 0
            if delta < 0:
                cur = conn.execute(
                    "UPDATE reseller_product_credit SET qty_remaining=qty_remaining + ?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE reseller_id=? AND product_id=? AND qty_remaining >= ?",
                    (delta, reseller_id, product_id, -delta),
                )
                if cur.rowcount == 0:
                    raise ValueError("موجودی محصول نمی‌تواند منفی شود")
                new_qty = current + delta
            else:
                new_qty = current + delta
                if row:
                    conn.execute(
                        "UPDATE reseller_product_credit SET qty_remaining=?, updated_at=CURRENT_TIMESTAMP WHERE reseller_id=? AND product_id=?",
                        (new_qty, reseller_id, product_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO reseller_product_credit (reseller_id, product_id, qty_remaining) VALUES (?, ?, ?)",
                        (reseller_id, product_id, new_qty),
                    )
            conn.execute(
                "INSERT INTO reseller_credit_log (user_id, delta_gb, reason, admin_id) VALUES (?, ?, ?, ?)",
                (reseller_id, 0, reason or f"تنظیم موجودی محصول #{product_id}: {delta:+d}", admin_id),
            )
            return new_qty


    def get_reseller_product_credit(self, reseller_id: int, product_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT qty_remaining FROM reseller_product_credit WHERE reseller_id=? AND product_id=?",
                (reseller_id, product_id),
            ).fetchone()
            return row["qty_remaining"] if row else 0


    def list_reseller_product_credits(self, reseller_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM reseller_product_credit WHERE reseller_id=? ORDER BY id", (reseller_id,)
            ).fetchall()


    def set_reseller_product_credit(self, reseller_id: int, product_id: int, qty: int,
                                     admin_id: int = None, reason: str = None) -> int:
        """تنظیم موجودی اولیه/قطعی محصول نماینده. برخلاف grant، مقدار را دقیقاً روی qty می‌گذارد.
        برای فعال‌سازی اولیه‌ی نمایندگی استفاده می‌شود تا موجودی باقی‌مانده از یک
        نمایندگی/درخواست قبلی به نمایندگی تازه منتقل نشود."""
        if not isinstance(qty, int) or qty < 0:
            raise ValueError("qty باید عدد صحیح بزرگ‌تر یا مساوی صفر باشد")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT qty_remaining FROM reseller_product_credit WHERE reseller_id=? AND product_id=?",
                (reseller_id, product_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE reseller_product_credit SET qty_remaining=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE reseller_id=? AND product_id=?",
                    (qty, reseller_id, product_id),
                )
            else:
                conn.execute(
                    "INSERT INTO reseller_product_credit (reseller_id, product_id, qty_remaining) VALUES (?, ?, ?)",
                    (reseller_id, product_id, qty),
                )
            conn.execute(
                "INSERT INTO reseller_credit_log (user_id, delta_gb, reason, admin_id) VALUES (?, ?, ?, ?)",
                (reseller_id, 0, reason or f"تنظیم موجودی اولیه محصول #{product_id}: {qty}", admin_id),
            )
            return qty


    def grant_reseller_product_credit(self, reseller_id: int, product_id: int, qty: int,
                                       admin_id: int = None, reason: str = None):
        """افزایش موجودی محصول نماینده (تخصیص اولیه یا شارژ مجدد ادمین)."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO reseller_product_credit (reseller_id, product_id, qty_remaining) "
                "VALUES (?, ?, ?) ON CONFLICT(reseller_id, product_id) "
                "DO UPDATE SET qty_remaining = qty_remaining + excluded.qty_remaining, "
                "updated_at = CURRENT_TIMESTAMP",
                (reseller_id, product_id, qty),
            )
            conn.execute(
                "INSERT INTO reseller_credit_log (user_id, delta_gb, reason, admin_id) VALUES (?, ?, ?, ?)",
                (reseller_id, 0, reason or f"تخصیص {qty} عدد از محصول #{product_id}", admin_id),
            )


    def consume_reseller_product_credit(self, reseller_id: int, product_id: int, qty: int = 1) -> bool:
        """کسر اتمیک از موجودی محصول نماینده؛ اگر موجودی کافی نبود False برمی‌گرداند."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE reseller_product_credit SET qty_remaining = qty_remaining - ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE reseller_id=? AND product_id=? AND qty_remaining >= ?",
                (qty, reseller_id, product_id, qty),
            )
            return cur.rowcount > 0


    def get_resellers(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE is_reseller=1 ORDER BY reseller_credit_gb DESC"
            ).fetchall()


    def get_reseller_cohort_churn(self, inactivity_days: int = 30, months: int = 6):
        """تحلیل کوهورت (cohort) و ریزش (churn) نمایندگی‌ها بر پایه‌ی لاگ اعتبار حجمی.

        کوهورت هر نماینده = ماه اولین رکورد او در reseller_credit_log (یعنی اولین
        شارژ/فعال‌سازی)؛ اگر نماینده‌ای هیچ لاگی نداشته باشد (مثلاً با ست دستی
        فلگ is_reseller)، ماه عضویتش (joined_at) به‌عنوان جایگزین در نظر گرفته می‌شود.
        «فعال بودن در ماه» یعنی حداقل یک رکورد لاگ (شارژ یا مصرف) در آن ماه.
        «ریزش» یعنی نماینده‌ای که is_reseller=1 است ولی طی inactivity_days روز
        اخیر هیچ رکورد لاگی نداشته (و بیش از همان مدت از عضویتش گذشته باشد).
        """
        with self._get_conn() as conn:
            first_activity = conn.execute(
                """
                SELECT u.telegram_id AS tg_id, u.username AS username, u.reseller_credit_gb AS credit_gb,
                       u.is_reseller AS is_reseller, u.joined_at AS joined_at,
                       COALESCE(MIN(l.created_at), u.joined_at) AS cohort_at,
                       MAX(l.created_at) AS last_activity
                FROM users u
                LEFT JOIN reseller_credit_log l ON l.user_id = u.telegram_id
                WHERE u.is_reseller = 1 OR EXISTS (
                    SELECT 1 FROM reseller_credit_log l2 WHERE l2.user_id = u.telegram_id
                )
                GROUP BY u.telegram_id
                """
            ).fetchall()

            monthly_activity = conn.execute(
                """
                SELECT user_id, strftime('%Y-%m', created_at) AS ym
                FROM reseller_credit_log
                GROUP BY user_id, ym
                """
            ).fetchall()

        active_months_by_user = {}
        for row in monthly_activity:
            active_months_by_user.setdefault(row["user_id"], set()).add(row["ym"])

        def month_key(dt_str):
            return (dt_str or "")[:7]

        def add_months(ym: str, n: int) -> str:
            y, m = int(ym[:4]), int(ym[5:7])
            total = (y * 12 + (m - 1)) + n
            return f"{total // 12:04d}-{total % 12 + 1:02d}"

        now = datetime.now()
        cur_ym = now.strftime("%Y-%m")
        cohort_months = []
        ym = cur_ym
        for _ in range(months):
            cohort_months.append(ym)
            ym = add_months(ym, -1)
        cohort_months.reverse()

        cohorts_map = {m: [] for m in cohort_months}
        for r in first_activity:
            cm = month_key(r["cohort_at"])
            if cm in cohorts_map:
                cohorts_map[cm].append(r["tg_id"])

        cohorts_out = []
        for cm in cohort_months:
            members = cohorts_map[cm]
            size = len(members)
            retention = []
            max_offset = add_months(cur_ym, 0)
            offset = 0
            probe = cm
            while probe <= cur_ym:
                active = sum(1 for uid in members if probe in active_months_by_user.get(uid, ()))
                retention.append({
                    "offset": offset,
                    "month": probe,
                    "active": active,
                    "pct": round(active * 100 / size, 1) if size else 0.0,
                })
                offset += 1
                probe = add_months(probe, 1)
            cohorts_out.append({"cohort_month": cm, "size": size, "retention": retention})

        churn_list = []
        active_count = 0
        cutoff = now.timestamp() - inactivity_days * 86400

        def to_ts(dt_str):
            if not dt_str:
                return None
            try:
                return datetime.fromisoformat(dt_str.replace("Z", "")).timestamp()
            except ValueError:
                return None

        current_resellers = [r for r in first_activity if r["is_reseller"]]
        for r in current_resellers:
            last_ts = to_ts(r["last_activity"])
            joined_ts = to_ts(r["joined_at"]) or 0
            is_new = joined_ts and joined_ts > cutoff
            if last_ts and last_ts >= cutoff:
                active_count += 1
                continue
            if not last_ts and is_new:
                active_count += 1
                continue
            days_inactive = int((now.timestamp() - (last_ts or joined_ts)) / 86400)
            churn_list.append({
                "telegram_id": r["tg_id"],
                "username": r["username"],
                "credit_gb": r["credit_gb"],
                "last_activity": r["last_activity"],
                "days_inactive": days_inactive,
            })

        total_resellers = len(current_resellers)
        churn_list.sort(key=lambda x: -x["days_inactive"])
        return {
            "cohorts": cohorts_out,
            "churn": {
                "total": total_resellers,
                "active": active_count,
                "churned": len(churn_list),
                "churn_rate": round(len(churn_list) * 100 / total_resellers, 1) if total_resellers else 0.0,
                "inactivity_days": inactivity_days,
                "list": churn_list,
            },
        }


    def create_reseller_request(self, user_id: int, volume_gb: int, request_text: str, wants_custom_config: int = 0,
                                 supply_model: str = "volume_credit", supply_product_id: int = None,
                                 supply_qty: int = None, bot_choice: str = "dedicated",
                                 wants_web_panel: int = 0, wants_miniapp: int = 0, tier_code: str = None,
                                 proposed_percent: int = None) -> int:
        with self._get_conn() as conn:
            # status را صراحتاً اینجا ست می‌کنیم و به مقدار پیش‌فرض ستون در schema
            # تکیه نمی‌کنیم. روی دیتابیس‌های قدیمی‌تر که ستون status از قبل (قبل از
            # اضافه‌شدن DEFAULT 'pending_review') با ALTER TABLE ساخته شده بود، تکیه
            # به دیفالت باعث می‌شد status درخواست‌های تازه NULL بماند و دکمه‌ی
            # «تایید و تعیین هزینه» همیشه با خطای «این درخواست دیگر معتبر نیست»
            # مواجه شود (چون NULL != 'pending_review'). ست‌کردن صریح این مشکل را
            # مستقل از تاریخچه‌ی دیتابیس برای همیشه حل می‌کند.
            known = {
                "user_id": user_id, "volume_gb": volume_gb, "request_text": request_text,
                "status": "pending_review", "wants_custom_config": 1 if wants_custom_config else 0,
                "supply_model": supply_model, "supply_product_id": supply_product_id, "supply_qty": supply_qty,
                "bot_choice": bot_choice, "wants_web_panel": 1 if wants_web_panel else 0,
                "wants_miniapp": 1 if wants_miniapp else 0, "tier_code": tier_code,
                "proposed_percent": proposed_percent,
            }
            fields = list(known.keys())
            values = list(known.values())
            # بعضی نصب‌های خیلی قدیمی ممکن است ستون‌های اضافی/الزامی (NOT NULL بدون
            # مقدار پیش‌فرض) در جدول reseller_requests داشته باشند که کد فعلی اصلاً
            # از آن‌ها استفاده نمی‌کند (مثلاً باقی‌مانده از نسخه‌های قدیمی‌تر پروژه).
            # به‌جای اینکه با هر نصب قدیمی دوباره به خطای «NOT NULL constraint
            # failed» بخوریم، این ستون‌های ناشناخته را این‌جا پویا شناسایی کرده
            # و برایشان یک مقدار بی‌ضرر بر اساس نوعشان می‌فرستیم.
            for row in conn.execute("PRAGMA table_info(reseller_requests)").fetchall():
                name = row["name"]
                if name in known or name in ("id", "created_at", "updated_at"):
                    continue
                if row["notnull"] and row["dflt_value"] is None:
                    col_type = (row["type"] or "").upper()
                    if "INT" in col_type:
                        fallback = 0
                    elif any(t in col_type for t in ("REAL", "FLOA", "DOUB")):
                        fallback = 0.0
                    else:
                        fallback = ""
                    fields.append(name)
                    values.append(fallback)
            placeholders = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO reseller_requests ({', '.join(fields)}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid


    def get_reseller_request(self, request_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_requests WHERE id=?", (request_id,)).fetchone()


    def get_open_reseller_request(self, user_id: int):
        placeholders = ",".join("?" * len(self._RESELLER_REQUEST_OPEN_STATUSES))
        with self._get_conn() as conn:
            return conn.execute(
                f"SELECT * FROM reseller_requests WHERE user_id=? AND status IN ({placeholders}) "
                f"ORDER BY id DESC LIMIT 1",
                (user_id, *self._RESELLER_REQUEST_OPEN_STATUSES),
            ).fetchone()


    def list_reseller_requests(self, status: str = None):
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM reseller_requests WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            return conn.execute("SELECT * FROM reseller_requests ORDER BY id DESC").fetchall()


    def list_open_reseller_requests(self):
        """درخواست‌های نمایندگی‌ای که هنوز باز هستند (رد/کنسل/تکمیل نشده‌اند)."""
        placeholders = ",".join("?" * len(self._RESELLER_REQUEST_OPEN_STATUSES))
        with self._get_conn() as conn:
            return conn.execute(
                f"SELECT * FROM reseller_requests WHERE status IN ({placeholders}) ORDER BY id DESC",
                self._RESELLER_REQUEST_OPEN_STATUSES,
            ).fetchall()


    def is_reseller_request_open(self, status: str) -> bool:
        return status in self._RESELLER_REQUEST_OPEN_STATUSES


    def admin_cancel_reseller_request(self, request_id: int, admin_id: int):
        """کنسل دستی یک درخواست نمایندگی توسط ادمین، در هر مرحله‌ای که باشد (حتی اگر
        claim شده باشد - این عمداً چک claimed_by ندارد تا یک درخواستِ claim-شده‌ی
        رهاشده هم قابل بستن باشد)."""
        self.set_reseller_request_status(request_id, "cancelled", reviewed_by=admin_id)


    def claim_reseller_request(self, request_id: int, admin_id: int) -> bool:
        """قفل خوش‌بینانه‌ی اتمیک: فقط وقتی True برمی‌گرداند که درخواست هنوز
        pending_review و claim‌نشده باشد (یا قبلاً توسط همین ادمین claim شده باشد -
        مثلاً اگر همان ادمین دوباره روی همان پیام کلیک کند). اگر ادمین دیگری قبلاً
        claim کرده باشد، False برمی‌گرداند تا صدازننده پیام «توسط ادمین دیگری در حال
        بررسی است» نشان دهد."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE reseller_requests SET claimed_by=? "
                "WHERE id=? AND status='pending_review' AND (claimed_by IS NULL OR claimed_by=?)",
                (admin_id, request_id, admin_id),
            )
            return cur.rowcount > 0


    def release_reseller_request_claim(self, request_id: int, admin_id: int):
        """آزادکردن claim (مثلاً وقتی ادمین با /cancel یا نرفتن به مرحله‌ی بعد منصرف
        می‌شود) تا ادمین دیگری بتواند این درخواست را بررسی کند."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reseller_requests SET claimed_by=NULL WHERE id=? AND claimed_by=?",
                (request_id, admin_id),
            )


    def claim_reseller_request_finalization(self, request_id: int) -> bool:
        """رزرو اتمیک مرحله‌ی نهایی‌سازی درخواست. فقط یک worker می‌تواند
        درخواست awaiting_bot_info را وارد provisioning کند تا دبل‌تپ/دو callback
        باعث ساخت دوباره‌ی بات، تخصیص دوباره‌ی اعتبار یا موجودی نشود."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE reseller_requests SET status='provisioning', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='awaiting_bot_info'",
                (request_id,),
            )
            return cur.rowcount > 0


    def set_reseller_request_status(self, request_id: int, status: str, **fields):
        cols, values = ["status=?", "updated_at=CURRENT_TIMESTAMP"], [status]
        for key, value in fields.items():
            cols.append(f"{key}=?")
            values.append(value)
        values.append(request_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE reseller_requests SET {', '.join(cols)} WHERE id=?", values)


    def quote_reseller_request(self, request_id: int, price_toman: int, panel_server_id: int, admin_id: int, commission_percent: int = None, discount_percent: int = None, payment_methods=None):
        fields = {
            "price_toman": price_toman, "panel_server_id": panel_server_id, "reviewed_by": admin_id,
        }
        methods = list(dict.fromkeys(str(x) for x in (payment_methods or []) if x))
        if methods:
            fields["payment_methods"] = json.dumps(methods, ensure_ascii=False)
        if commission_percent is not None:
            fields["commission_percent"] = int(commission_percent)
        if discount_percent is not None:
            discount_percent = int(discount_percent)
            if not 1 <= discount_percent <= 100:
                raise ValueError("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد.")
            fields["discount_percent"] = discount_percent
        self.set_reseller_request_status(request_id, "awaiting_payment", **fields)


    def reject_reseller_request(self, request_id: int, status: str, admin_id: int, reason: str = None):
        self.set_reseller_request_status(request_id, status, reviewed_by=admin_id, reject_reason=reason)


    def set_reseller_request_receipt(self, request_id: int, file_id: str, receipt_type: str = "photo"):
        self.set_reseller_request_status(
            request_id, "awaiting_payment_review", receipt_file_id=file_id, receipt_type=receipt_type
        )


    def set_reseller_request_bot(self, request_id: int, token: str, username: str):
        self.set_reseller_request_status(
            request_id, "awaiting_bot_info", bot_token=token, bot_username=username,
        )


    def complete_reseller_request(self, request_id: int, owner_telegram_id: int):
        self.set_reseller_request_status(
            request_id, "completed", owner_telegram_id=owner_telegram_id,
        )
        req = self.get_reseller_request(request_id)
        if req and req["tier_code"]:
            self.set_user_reseller_tier(owner_telegram_id, req["tier_code"])
