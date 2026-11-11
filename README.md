<!--‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍-->
[🇬🇧 English](README.md) | [🇮🇷 فارسی](README.fa.md) | [🇷🇺 Русский](README.ru.md) | [🇨🇳 中文](README.zh.md)

<div align="center">

# 🛰️ ShopVPN — Smart V2Ray Configuration Sales Bot

**An automated Telegram V2Ray sales platform with a dedicated Mini App, AI support assistant, Android management app, web administration, multi-level reseller support, and Persian/English UI.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-MiniApp%20%2B%20Panel-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

</div>

---

## 📚 Table of Contents

- [📖 Overview](#overview)
- [✨ Features](#features)
- [🧠 AI Support Assistant](#ai-support)
- [📣 AI Channel Posts](#channel-ai)
- [💼 Telegram Business](#business)
- [🔐 SSH, OpenVPN & WireGuard Nodes](#ssh-nodes)
- [🏢 Reseller Tiers & Agency Requests](#reseller-tiers)
- [🚨 Config Leak Detection](#leak-detection)
- [💳 Payment Gateways](#payment-gateways)
- [📲 Telegram Mini App](#miniapp)
- [🛍️ Public Web Shop](#web-shop)
- [🖥️ Standalone Web Admin Panel](#admin-panel)
- [📱 Android Management App](#android-app)
- [🔌 Supported VPN Panels](#vpn-panels)
- [🖥️ Requirements](#requirements)
- [🚀 One-Line Automatic Installation](#auto-install)
- [🛠️ Manual Installation](#manual-install)
- [⚙️ Environment Variables](#env-vars)
- [🧰 manage.sh](#manage-sh)
- [🗂️ Project Structure](#project-structure)
- [🧪 Technology Stack](#tech-stack)
- [🆕 Recently Added Features](#new-features)
- [🤖 Bot Features — Complete Reference](#bot-reference)
- [🔎 Additional Features](#additional-features)
- [🔗 Dedicated Subscription Server](#dedicated-sub)
- [🤝 Contributing & License](#contributing)

---

<a id="overview"></a>

## 📖 Overview

**ShopVPN** is a production-oriented Telegram bot for selling and managing V2Ray/VPN configurations. It combines automated provisioning, multiple payment methods, reseller management, AI support, a Telegram Mini App, a standalone web admin panel, and Android management infrastructure.

The project is designed for real-world operation, with wallets, referrals, discounts, support tickets, monitoring, backups, reports, configurable products, and multi-bot reseller support.

### 📢 Official Links

- 📢 **Project:** [@celenorbot](https://t.me/celenorbot)
- 👤 **Author:** [@celenor](https://t.me/celenor)
- 💎 **Donation addresses:**
  - `USDT-BNB (BEP20):` `0x3c026D27DEbE24d659d6dDcF074b3063Fd47bc63`
  - `USDT-TRX (TRC20):` `TBm712Gdcbfp3Tkv1CpNgfwUfKuFNn8iWE`

### ⚡ Quick Summary

- 🔑 Automatic configuration delivery on supported VPN panels
- 💳 Multiple automatic payment methods
- 🧠 AI support assistant
- 🔄 Flexible service renewal
- 🏢 Independent and linked reseller modes
- 🖥️ Telegram admin + web admin + Android management app
- 📲 Telegram Mini App storefront
- 🌍 Server map and panel health monitoring
- 🌐 Polling and Webhook support
- 🚀 Anti-spam, reports, backups, cashback, coins, lottery, gifts and Integration API
- 🛍️ Public web shop (own domain, Telegram or email login) next to the Mini App
- 🔐 SSH, OpenVPN and WireGuard nodes with shared VPN+SSH quota pools
- 🥉🥈🥇👑 Four reseller tiers with agency requests and postpaid credit
- 🚨 Config leak detection with smart Telegram discovery
- 🏆 Seasons, lucky boxes, streaks and a daily quiz
- 🔄 One-button project updates from inside the bot (with automatic rollback)
- 🧩 Telegram widgets, 🧠 AI smart buy guide, 🚚 panel-to-panel user migration and 🔎 config search
- 📦 Per-product delivery text/sticker, post-delivery media and WireGuard/OpenVPN files sent in the bot
- ⌨️ Full command list and every admin-menu feature in the [Bot Features reference](#bot-reference)

> **Detailed sections are collapsed below. Click any section to expand it.**

---

<a id="features"></a>

## ✨ Features

<details>
<summary><strong>🤖 Main Bot — click to expand</strong></summary>

- 🔑 Unique configuration inventory per user with automatic provisioning
- 🔗 Direct product-to-panel assignment
- 🔄 Free-form renewal by traffic/time amount
- 👤 Unified **My Account** for purchased, gifted and test services
- 🧪 Multiple configurable test plans
- 🔢 Multi-quantity purchases with automatic total calculation
- 💱 Automatic USD/USDT exchange-rate lookup with fallback rates
- 💰 Internal wallet with top-up requests and admin approval
- 🗂️ Product/category management with pricing and stock controls
- 🚫 User blocking and mandatory channel membership
- 📊 Live subscription information and expiration/traffic reminders
- ⚠️ Low-stock alerts for administrators
- 📱 Configuration delivery as text + QR code
- 🎫 Support tickets and live support chat
- 🎨 Customizable main-menu layout, labels and colors
- 🏷️ Store branding controls
- 🏢 Independent reseller bots with isolated databases
- 🌐 Polling or Webhook mode
- 💾 Persistent FSM state on SQLite
- ⏳ Temporary/sensitive-message cleanup
- 📣 Channel advertising and deep-link utilities

</details>

<details>
<summary><strong>🤝 Resellers, Referrals, Discounts & Wallet — click to expand</strong></summary>

- 🏢 Linked reseller mode inside the main bot
- 🤖 Independent reseller bots
- 👥 Referral links with multiple reward models
- 💸 Percentage commissions and fixed wallet rewards
- 🎁 Free configuration rewards after referral thresholds
- 🏷️ Discount codes with limits, expiration and product/category scope
- 🎡 Lucky wheel with configurable rewards and cooldown
- 🪜 Reseller tiers, fees, expiration, reminders and credit limits
- 📦 Product-based reseller supply
- 💰 Wallet and cashback features

</details>

<details>
<summary><strong>👑 Telegram Admin Panel — click to expand</strong></summary>

- 👑 Owner, Admin, Mid-level Admin and Support roles
- 📢 Broadcast messaging
- 📈 Sales statistics with date filters
- 📝 Full administrator audit logs
- 🗄️ Automatic daily backups to Telegram
- ♻️ Immediate backup and full database restore
- 📅 Jalali/Persian calendar support
- 👥 Users, products, categories, gateways, panels and reseller management
- 🎫 Support, reports and system settings

</details>

<details>
<summary><strong>🚀 Growth, Security & Monitoring — click to expand</strong></summary>

### 🔐 Security

- 🛡️ User anti-spam/rate limiting
- 🎟️ Advanced discount-code limits
- 🔒 Sensitive payment/card message cleanup

### 📊 Operations

- 🩺 VPN panel health monitoring and recovery alerts
- 📊 Daily sales reports
- 📣 Topic-based report groups
- 🎁 Bulk traffic/time gifts
- 🧹 Automatic cleanup of expired services
- 🔌 Token-scoped Integration API

### 💰 Sales & Retention

- ⏸️ On-hold services that start expiration on first connection
- 📦 Per-panel capacity limits
- 📍 Service location/panel migration
- 💰 Bulk product price editing with undo
- 💸 Renewal/wallet cashback
- 🎁 Wallet top-up gift codes
- 🪙 Coins and scheduled lottery
- 🎫 Department-based support tickets and outage reports

</details>

---

<a id="ai-support"></a>

## 🧠 AI Support Assistant

<details>
<summary><strong>Click to expand</strong></summary>

The AI layer answers repetitive customer questions before escalating to human support.

- 🔌 Selectable providers: Gemini, Groq, OpenRouter, OpenAI, Claude (Anthropic), Mistral, Cohere and Cloudflare Workers AI, plus custom providers with their own URL, model and keys; providers, keys (several per provider) and models are managed from the bot's admin menu (**AI settings**) without editing `.env` or restarting
- 📚 Administrator-managed FAQ knowledge
- 🔎 Real user-specific answers for services, expiration, wallet and orders
- 🛒 Real purchase cards with current prices and payment buttons
- 🔒 Wallet purchases/renewals and service changes run only through the bot's validated flows after explicit user confirmation; refunds and complaints go to human support
- 🙋 Automatic escalation for financial complaints or explicit human-support requests
- ⚡ If no API provider is configured, requests can go directly to human support
- 🎙️ Customers can send voice messages, audio files or photos; Gemini turns them into text or a description before the assistant answers (images up to 8 MB, audio up to 10 MB and 180 seconds)
- ⚡ Live answer streaming in private chats through Telegram's `sendMessageDraft` (Bot API 9.5+); the final message is always sent normally and a streaming error never blocks it
- 🧠 **Admin AI assistant** — a read-only natural-language assistant for senior admins (`/ai` or the admin menu), by text or voice: sales trends, user lookup, pending orders and tickets, expiring services, panel and gateway status, and "which button do I press" guidance. It never changes anything; per-section help guides are also built into the admin panel

</details>

---

<a id="leak-detection"></a>

## 🚨 Config Leak Detection & Smart Discovery

<details>
<summary><strong>Click to expand</strong></summary>

Customers sometimes post their config or subscription link in public channels. The leak scanner finds those posts and ties them to the owning service.

- 🔐 **Fingerprint index** — for every active service on 3X-UI, PasarGuard and Hiddify, the secret values (UUID, protocol passwords, subscription token) are hashed with SHA-256 into a credential index; raw values are never stored. The index is rebuilt every few minutes, and a single service is refreshed right after a purchase or an access cut
- 🔎 **Scanner on the userbot session** — it parses `vless` / `vmess` / `trojan` / `ss` links and subscription links inside public Telegram posts, hashes them and matches them against the index; listed channels are scanned for new posts and a global keyword search runs as well
- 🚨 **Admin alert** — on a hit, admins get an alert (in the "🚨 config leak" topic when a report group is set) with *Rotate link / Warn / Ignore* buttons; a warning can be sent with or without automatic access revocation
- 🛡️ **Account protection** — a per-minute request cap with random spacing, a full stop on Telegram FloodWait, and customers always come first: the scanner stays quiet for a few seconds after every incoming customer message

**Smart discovery** (🚨 Leak detection → 🧭 Smart discovery) lets it find sources on its own instead of only watching channels you add by hand:

- **Telegram search** with built-in Persian / English / Russian / Chinese keywords. Keywords learn: productive ones run more often, and new ones are derived from the titles of good channels. Admins can add their own keywords and enable/disable or delete any keyword from the bot menu.
- **Link crawling**: `t.me/...`, `@username` and invite links found in posts, channel descriptions and search results become candidates.
- **Scored before joining**: the last ~40 posts are read *without joining* (and scanned for leaks right away). Score = config density, freshness, posting rate, title relevance, member count.
- **Careful joining**: daily cap, total cap, random delays, full stop on FloodWait. Modes: automatic, admin approval, or watch-only (public channels, no joining).
- **Real-time monitoring** of joined channels (new *and* edited posts), including links hidden behind text hyperlinks and buttons.
- **Auto-leave** of channels the scanner joined that produced no configs or leaks after 14 days. Channels you were already in are never left.

Everything is off by default (`leak_scanner_enabled`, `leak_discovery_enabled`). Because the scanner shares the userbot account, keep the join caps low, or give the scanner its own Telegram account: `manage.sh` option 40 (Telegram accounts) or `python userbot.py login-scanner` (undo: `logout-scanner`, status: `status-scanner`). It starts without a restart and never touches the customer-facing account.

Tests: `python -m unittest test_leak_scanner test_leak_discovery`

</details>

---

<a id="channel-ai"></a>

## 📣 AI Channel Posts

<details>
<summary><strong>Click to expand</strong></summary>

Captions and banners for the sales channel are generated through the [Jarvis](https://jarvis.you) gateway (default API URL `https://api.jarvis.you/v1`). This part is fully separate from the support assistant and the admin assistant.

**Setup (inside the bot):** Marketing & Growth → channel posts / Deep-link & channel post tools → AI post → ⚙️ AI settings & learning

1. Create a Jarvis account and an API key (keys start with `pmai_`), press "🔑 Jarvis key" and send it (several keys: one per line, rotated automatically on errors).
2. Press "🧪 Test text". Change the text or image model if needed (defaults: `CLAUDE_6_5_HAIKU` and `gemini-3-1-flash-image`).
3. For banner quality, send a transparent PNG logo and, optionally, a sample banner as the style reference.
4. The full in-bot guide is under "📖 Jarvis guide".

**Features**

- ✍️ One complete caption (up to 1500 characters) on the admin's topic, built only from real products, prices, discounts and discount codes (plus whatever the admin wrote); rewrite and change-topic actions; a manual-caption mode works without any AI key
- 🏷️ Correct pricing: the AI receives both the original and the discounted price, the real percentage, the real end date (never an hour countdown) and the remaining purchases/uses, plus test-config plans, lucky-wheel prizes and other offers as facts
- 🖼️ Banners with a design template per post type (discount, code, product, test, wheel) and real urgency chips taken from the database (a deadline within 7 days, or few purchases/uses left)
- 🎯 Logo mode: "exact" (default) places the original logo without AI interference; "AI reference" passes it as a reference image and falls back to exact automatically
- 🖼 Style-reference banner, an editable base prompt and a brand template (colors, logo, Persian font, default size, preview)
- 🗳 AI-generated polls and quizzes
- 📅 Weekly plan: the AI proposes several posts with different angles and the admin approves them in one step
- 🗂 Post manager: drafts, scheduled posts (sent automatically), send, edit, pin/unpin, delete and statistics
- 💡 Automatic suggestions to admins to create a post when a new product is added, stock runs low or a public discount code is created
- 🔗 Deep-link buttons (discount code, test config, lucky wheel or a custom campaign parameter) and the standalone tools `channel_post_tool.py` and `channel_add_button_tool.py`

</details>

---

<a id="business"></a>

## 💼 Telegram Business

<details>
<summary><strong>Click to expand</strong></summary>

The seller can connect the main bot to their own Telegram Business account (Settings → Telegram Business → Chatbots). The bot then answers customers inside the seller's personal chats on their behalf. This works on the main bot only (not on reseller bots) and is **off by default** until an administrator turns it on.

- 🔗 **Connection handling** — `business_connection` and `business_message` updates are stored per connection (owner, reply/read rights, enabled/disabled); admins are notified when a connection is activated or cut
- 🤖 **Automatic AI replies** — customer messages are answered through the AI support assistant with real data; only read-only tools are available here: prices and products, payment methods, service status, server countries, service history and free test config
- 🔒 **No financial actions in business chats** — wallet purchases, renewals and service changes are disabled; such requests are handed to the seller
- 🛡 **Safety filters** — the bot ignores the seller's own messages, administrators, other bots and blocked users; the anti-spam guard and the global bot on/off switch apply to this path as well; non-text messages are ignored
- 🤝 **Human handoff** — when the assistant escalates, it goes silent in that chat and the seller gets a notice in the main bot with the last messages, a button to open the chat and a button to return the chat to automatic mode
- ✏️ **Edit/delete tracking** — customer edits and deletions in handed-off chats are reported to the seller (can be turned off); message log is pruned automatically after a few days
- ✅ **Mark as read** — optional; requires the `can_read_messages` right from the account owner
- 🛒 **Purchase card (optional, off by default)** — when a customer wants to buy, the bot sends a product card (name, price, volume, duration, description) with a link button that opens the bot at that product. Payment and delivery always run inside the bot; no payment happens in the business chat
- ⚙️ **Admin panel** — **Admin & Access → 💼 Telegram Business**: master switch, mark-as-read, edit/delete notices, purchase card switch, list of active connections, per-connection auto-reply switch, first message (sent once at the start of each new chat), exception list of customer IDs and the list of chats handed to a human

> Inline callback buttons inside business chats are intentionally not used: URL buttons are used instead, because callback delivery in business chats has not been verified.

</details>

---

<a id="reseller-tiers"></a>

## 🏢 Reseller Tiers & Agency Requests

<details>
<summary><strong>Click to expand</strong></summary>

Reseller access is organised into four admin-editable tiers (Telegram admin → Resellers, the web panel and the Mini App admin). Each tier has its own title, icon, summary and description, can be switched on or off, can carry a membership fee with a validity period (expiry and reminders are automatic) and can be set to auto-approve requests.

| Tier | Model | What the reseller gets |
|---|---|---|
| 🥉 Bronze | Commission | A personal link inside the main bot; a percentage of every purchase made by customers who come through it is added to the reseller's wallet. No capital needed |
| 🥈 Silver | Discount | No link and no bot: buys from the main bot at a permanent discount, and the more bought at once the bigger the discount (quantity-based discounts per tier) |
| 🥇 Gold | Fixed products | Own web panel, Mini App and dedicated bot; buys ready-made products in bulk (prepaid, counted by quantity) and resells them |
| 👑 VIP | Volume credit | Own web panel, Mini App and dedicated bot; buys a pool of traffic and creates any product at any price; services are provisioned directly on the panel assigned to the reseller (VIP has no config bank) |

- 📝 **Agency requests from the bot** — a user asks for a tier with a button. For Bronze the user proposes the commission percentage (1–100) and the admin accepts it or answers with his own; for Silver the user asks for the discount tier and the admin sets the approved permanent discount (1–100); tiers marked auto-approve are activated immediately
- 🧭 **Request form for Gold/VIP** — bot type (dedicated bot / personal link / no bot), web panel, Mini App and supply model (volume or ready products); the owner can remove any of these axes from the form entirely. Admins see requests, receipts and statuses in the bot, the web panel and the Mini App, and the membership fee is paid from the wallet or a gateway
- 🪜 **Tier limits and upgrades** — minimum quantity and volume, commission range, permanent discount and per-tier quantity discounts; users can ask for an upgrade
- 💳 **Postpaid credit** — a default credit limit per tier plus an optional per-reseller limit set by the admin from the reseller card. The wallet may go negative down to minus the limit; the wallet screen shows balance, limit, debt and spendable credit; purchases, renewals and auto-renew stop with a "top up first" message at the cap; wallet transfers use the real balance only. Every movement is written to the wallet ledger
- 🌐 **Resellers without their own bot** can create services from their web panel (`/api/reseller/self-service`), and the bot can issue them a web-panel login link
- 🔗 The older modes still exist next to the tiers: linked resellers with their own catalog and card number, and independent reseller bots with isolated databases

</details>

---

<a id="ssh-nodes"></a>

## 🔐 SSH, OpenVPN & WireGuard Nodes

<details>
<summary><strong>Click to expand</strong></summary>

Besides VPN panels, ShopVPN can sell accounts on plain Linux servers over **SSH, OpenVPN and WireGuard**. These "nodes" behave like panel nodes: they are only used to create accounts, and users get them through the normal purchase, subscription and delivery flows.

- 🧩 **Node agent** — each node runs a small authenticated agent (`ssh_node_agent.py`, TLS with a pinned certificate fingerprint) and the bot talks to it through a documented HTTP API instead of running raw root commands. Secrets are referenced from the environment (`env:NAME`) and never stored as raw values in SQLite
- ⚡ **One-step install** — from the admin panel only an IP and the root password are needed: the panel connects over SSH, uploads and installs the agent, creates the token and certificate, limits agent access to the panel server's IP, registers the node and runs a real test (creating and deleting a trial account), with live install progress. The root password is used in memory only and is never stored or logged. Protocols can be added to an existing node later, or installed by hand with `deploy/install-shopvpn-ssh-agent.sh [ssh|openvpn|wireguard]`
- 🔌 **SSH accounts** — every account gets its own isolated `sshd` listener on a unique port (the port range is configurable per node), and traffic is counted per account with nftables port counters
- 🛡️ **OpenVPN and WireGuard** — per-account accounting for both, plus NAT services and an OpenVPN disconnect script in `deploy/`
- 🌐 **Hosts** — like PasarGuard hosts: a node can have one or more host entries per protocol (the node's domain/IP or a tunnel/relay address, optional port). Only the user-facing output is built at display time, so editing a host also updates existing accounts
- 📤 **Delivery formats** — `ssh://BASE64(user:pass)@host:port#remark` links, `.ovpn` files and WireGuard `.conf` files; SSH passwords are encrypted at rest (Fernet, key from `SHOPVPN_SSH_CREDENTIAL_KEY`) for user self-service delivery
- 🔗 **Shared quota pools** — a combined service puts a VPN config and SSH accounts in one pool with one volume and one expiry. `quota_reconciler.py` reads VPN panel counters through the existing panel providers and node counters through the agents (a node counter is accepted only when the node reports accounting as ready, and a missing counter is never treated as zero), then enforces the shared limit. SSH usage is reflected on the VPN panel by lowering the user's volume limit there (limit = panel usage + what is left in the pool), so the panel itself cuts the user off the moment the shared volume runs out; renewals push the new expiry to the nodes
- 🧰 **Management** — nodes, accounts and pools are managed from the Telegram admin bot, the web admin panel and the Mini App admin; the CLI `ssh_admin.py` covers operations from the shell. If a node is unreachable, "force delete" removes it from the panel only
- ✅ Tests: `python -m unittest test_ssh_hosts test_ssh_uri test_ssh_order_row test_ssh_unreachable_node test_quota_panel_sync`

</details>

---

<a id="payment-gateways"></a>

## 💳 Payment Gateways

<details>
<summary><strong>Supported payment methods — click to expand</strong></summary>

| Method | Confirmation | Notes |
|---|---|---|
| 💳 Manual card-to-card | Admin | Receipt/image flow |
| 📲 Bank SMS card-to-card | Automatic | Unique invoice amount and rotating cards |
| 🏧 Aban Gateway | Automatic | API-based invoice and verification |
| 💎 Plisio | Automatic | Crypto with callback/signature validation |
| 🔵 Blupal | Automatic | Automated card-to-card |
| ⭐ NoaPay / Telegram Stars | Automatic | Telegram Stars |
| 🟡 ZarinPal | Automatic | Main bot |
| 🔵 Mr. Pardakht | Automatic | Main bot |
| 💸 Tetra98 | Automatic | Main bot |
| 💳 CubePay | Automatic | Main bot |
| 💰 NowPayments | Automatic | Crypto invoice + IPN |
| ⭐ Telegram Stars | Automatic | Native `XTR` invoices |
| 🧩 Generic Gateway | Automatic | Configure HTTP APIs without writing code |

All gateways are independent and can be enabled or disabled separately.

</details>

---

<a id="miniapp"></a>

## 📲 Telegram Mini App

<details>
<summary><strong>Click to expand</strong></summary>

The `miniapp/` directory contains a full Telegram Mini App with both a customer storefront and web administration.

### 🛍️ Customer Side

- ⚡ FastAPI backend with secure Telegram `initData` verification
- 🎨 Responsive storefront
- 🛒 Products, cart, wallet, lucky wheel, referrals and test configurations
- 🔔 Expiration and traffic alerts
- 📲 Add subscriptions to popular VPN apps using deep links
- 🎫 Support tickets and live support chat
- 🌐 Persian/English switch with automatic RTL/LTR direction

### 🛠️ Web Administration Side

- 📊 Dashboard and order exports
- 🗂️ Categories, products, panels and configuration management
- 🏢 Reseller management
- 🏷️ Discounts, lucky wheel, referrals and reminders
- 👥 User search, blocking and targeted broadcasts
- 💰 Wallet lookup and balance adjustments
- 🎨 Branding and theme customization
- 🧩 Telegram main-menu layout management
- 🎫 Ticket/support management
- 📝 System and admin logs
- 🗄️ Backup and database restore

</details>

---

<a id="web-shop"></a>

## 🛍️ Public Web Shop

<details>
<summary><strong>Click to expand</strong></summary>

`web_store/` is a public website on its own domain where customers can buy without opening Telegram: pick a plan, pay and get the subscription link right away. It is served by FastAPI (`uvicorn web_store.server:app`, port 8005 behind nginx and SSL) and works for the main bot only.

- ⚙️ **Setup from `manage.sh`** — option 10 (domain + SSL + service), 11 remove, 12 update, `S` status; option 13 configures the email service (SMTP codes) and option 14 Cloudflare Turnstile
- 🌐 **Persian and English pages** (`/` and `/en`) with automatic RTL/LTR, SEO tags, `robots.txt`, `sitemap.xml` and PWA installation
- 🛒 **Catalog and checkout** — active categories and products with price, original price, volume, duration and stock; the same payment methods as the Mini App (wallet, crypto, Aban, Blupal, NoaPay, the extra and custom gateways, automatic card-to-card and receipt upload)
- 🔐 **Login** — through the Telegram bot (start + poll) or an emailed verification code; Cloudflare Turnstile protects the login endpoints
- 🔗 **Account merge** — a web account can be merged with a Telegram account with a code and `/merge CODE` in the bot, with a preview before confirming
- 👤 **My services** — services, orders, QR codes, live usage from the subscription link, support tickets, terms acceptance and full renewal
- 🗺️ **Live network map** on the front page — shop locations come from the config links of each product, with the products of each location and routes drawn from the visitor's country (taken from CDN headers such as Cloudflare); coastlines and country borders are served from the server's own cache, because the strict content-security policy blocks external CDNs
- 🔒 **Security headers** — strict CSP, HSTS, `X-Frame-Options` and a restricted `Permissions-Policy`; the page can only be embedded in the admin panel's preview

</details>

---

<a id="admin-panel"></a>

## 🖥️ Standalone Web Admin Panel

<details>
<summary><strong>Click to expand</strong></summary>

The `admin_panel/` package provides a standalone web administration panel independent of Telegram.

- 🔐 Username/password login with independent sessions
- 👥 Separate web-admin roles and permissions
- 📊 Sales, orders, wallet and system dashboards
- 🎨 Multiple visual themes
- 📱 PWA installation on mobile
- 🌍 Global server map: the master subscription link is scanned, server IPs are geolocated and real protocol-level health checks decide online/offline
- 💱 Exchange-rate management
- ✅ Order, wallet and payment approval
- 🏢 Reseller management and analytics
- 🎫 Support tickets and conversations
- 📢 Broadcast messaging
- 🗄️ Backup and restore
- 🔔 Web Push notifications
- 📱 Android app token management
- 📝 Web-admin audit logs
- 🌐 Persian/English UI with automatic RTL/LTR

### Quick Setup

**Automatic:** use the relevant `manage.sh` option for the web panel.

**Manual:**

```bash
python -m admin_panel.create_admin <username> <password>
uvicorn admin_panel.server:app --host 127.0.0.1 --port 8002
```

</details>

---

<a id="android-app"></a>

## 📱 Android Management App

<details>
<summary><strong>Click to expand</strong></summary>

The backend provides infrastructure for a native Android management application.

- 🔑 Secure long-lived administrator token (PAT)
- 🧩 Server-Driven UI
- 🔔 Firebase Cloud Messaging (FCM) push notifications
- 📋 Orders, tickets, users, products, discounts, VPN panels and web admins
- 🌍 Server map through WebView
- 🎨 Light/dark interface
- 🔕 Per-section notification controls

</details>

---

<a id="vpn-panels"></a>

## 🔌 Supported VPN Panels

<details>
<summary><strong>Click to expand</strong></summary>

| Panel | Status | Notes |
|---|---|---|
| PasarGuard | ✅ Full | Automatic provisioning |
| Marzban | ✅ Full | Automatic provisioning |
| Marzneshin | ✅ Full | Service-based provisioning |
| Hiddify | ✅ Full | API-key based |
| 3X-UI | ✅ Full | Bearer API token |
| Alireza X-UI | ✅ Full | Cookie-based login |
| Rebecca | ✅ Full | Marzban-based provider |
| S-UI | ✅ Full | Token-based API |
| WGDashboard | ✅ Full | Configuration-based |
| MikroTik / User Manager | ⚠️ Limited | Profile-based |
| IBSng | ⚠️ Limited | Admin-panel integration |
| W-UI | ✅ Full | Interface-based (WireGuard/AmneziaWG/OpenVPN), API token |
| Other panels | ➕ Extensible | Add a provider |

</details>

---

<a id="requirements"></a>

## 🖥️ Requirements

- 🐧 Ubuntu 20.04+ / Debian 11+ recommended
- 🐍 Python 3.10+
- 🖥️ Linux VPS/server with a stable public IP
- 🤖 Telegram bot token
- 🌐 Public HTTPS domain for Mini App/web panel/webhook features
- 🔑 API credentials for the payment/VPN providers you enable

> 🔒 Never publish bot tokens, `.env` files, API keys or production secrets.

---

<a id="auto-install"></a>

## 🚀 One-Line Automatic Installation

**Recommended:** on a fresh Ubuntu/Debian server, run:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/mehdirafatpanah/Shopvpn/main/manage.sh)
```

<details>
<summary><strong>What does the installer do?</strong></summary>

1. Installs system prerequisites
2. Clones or updates the project
3. Creates the Python virtual environment
4. Installs required packages
5. Installs/updates the local translation runtime and language models automatically
6. Creates/configures `.env`
7. Creates the systemd service
7. Starts the bot and keeps it running after server reboots

### Basic service commands

```bash
sudo systemctl status v2raybot
sudo journalctl -u v2raybot -f
sudo systemctl restart v2raybot
sudo systemctl stop v2raybot
```

The same one-line installer can be run again for future updates. Translation runtime and language models are installed/updated automatically; no manual translation setup is required.

</details>

---

<a id="manual-install"></a>

## 🛠️ Manual Installation

<details>
<summary><strong>Click to expand</strong></summary>

### 1. Clone

```bash
git clone https://github.com/mehdirafatpanah/Shopvpn.git
cd Shopvpn
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env`

```bash
cp .env.example .env
nano .env
```

At minimum:

```env
BOT_TOKEN=your_bot_token
OWNER_ID=your_numeric_telegram_id
```

### 4. Start

```bash
python main.py
```

For production, use the automatic installer/systemd approach or another process manager.

</details>

---

<a id="env-vars"></a>

## ⚙️ Environment Variables

<details>
<summary><strong>Click to expand</strong></summary>

The exact variables depend on enabled features. Common configuration areas include:

| Area | Examples |
|---|---|
| Telegram | `BOT_TOKEN`, `OWNER_ID` |
| Database | database/storage paths |
| Web | domain, authentication, webhook settings |
| Payments | gateway API keys |
| VPN Panels | URLs, credentials, tokens, IDs |
| AI | provider API keys |
| Backups | destinations and SFTP credentials |
| Android | FCM credentials |

Keep production secrets outside the repository.

</details>

---

<a id="manage-sh"></a>

## 🧰 `manage.sh`

<details>
<summary><strong>Click to expand</strong></summary>

`manage.sh` is the main installation and maintenance helper.

Depending on the project version, it can handle:

- 🚀 Installation and dependency setup
- ⚙️ Environment/configuration
- ▶️ Start/stop/restart
- 📲 Mini App and web panel setup
- 🗄️ Backup/restore
- 🔌 VPN panel setup
- 📋 Logs and diagnostics
- 🔗 Integration API setup
- 🌐 Persian/English management menu
- 🌐 Local translation runtime install/repair and unused-language cleanup
- 🏭 Full cleanup / factory reset

Run:

```bash
chmod +x manage.sh
./manage.sh
```

> The script itself is the authoritative source for the current menu options.

</details>

---

<a id="project-structure"></a>

## 🗂️ Project Structure

<details>
<summary><strong>Click to expand</strong></summary>

```text
Shopvpn/
├── server.py
├── bot_manager.py
├── handlers_admin.py
├── payment_*.py
├── ai_support.py
├── business_chat.py
├── ssh_*.py, quota_reconciler.py   # SSH/OpenVPN/WireGuard nodes and shared quota pools
├── leak_*.py                       # config leak detection
├── seasons.py, engagement.py, daily_quiz.py
├── updater.py, admin_update.py     # updates from inside the bot
├── panel_providers/
├── web_store/                      # public web shop
├── sub_server/                     # dedicated subscription server
├── api/                            # Integration API
├── deploy/                         # node agent installer and services
├── db/
├── miniapp/
│   ├── server.py
│   └── static/
├── admin_panel/
│   ├── server.py
│   └── static/
├── manage.sh
├── requirements*.txt
├── VERSION
├── README.md
└── README.fa.md
```

</details>

---

<a id="tech-stack"></a>

## 🧪 Technology Stack

<details>
<summary><strong>Click to expand</strong></summary>

- **Python 3.10+**
- **aiogram 3.x**
- **FastAPI**
- **SQLite**
- **HTML/CSS/JavaScript**
- **Telegram Mini Apps / WebApp authentication**
- **Firebase Cloud Messaging**
- **HTTP/API integrations for VPN panels, payments and AI providers**

</details>

---

<a id="new-features"></a>

## 🆕 Recently Added Features

<details>
<summary><strong>Click to expand</strong></summary>

### 🧾 AI Fake/Duplicate Receipt Detection

Manual card-to-card receipts are screened before they reach the admin chat. Most findings are advisory notes; the final decision stays with the admin.

- 🔁 Exact-duplicate detection through the file SHA-256 hash and the receipt reference number, plus a perceptual hash (dHash) that flags re-compressed or cropped reuse (warning only)
- 🤖 Multi-model vision analysis: Gemini, plus every other configured agent in parallel (Groq, OpenRouter, Mistral, Cohere, Cloudflare Workers AI, OpenAI, Claude and custom providers)
- 🏦 More advisory checks: the bank implied by the source card's prefix vs. the bank branding visible in the receipt, and the sent file's name (a screenshot timestamp far from the send time, or photo-editor keywords; only when the receipt is sent as a Telegram file)
- 🏛️ Bank inquiry (optional, off by default): the IBAN's bank code is always compared with the card's bank, and you can plug in any official card/IBAN inquiry HTTP API (URL, headers, body and response paths are set in the settings) to verify card ↔ IBAN and the cardholder name; results are cached, an unavailable service is never treated as approval, and a definite destination mismatch is auto-rejected only when you enable that
- 🔢 Deterministic OCR checks: card number (Luhn + known Iranian bank prefix), IBAN checksum, amount match in Toman or Rial, reference-number reuse
- 🕵️ Forensics: Error Level Analysis on JPEGs, image-metadata scan, screenshot status-bar time vs. send time, bank/holder-name and amount-in-words consistency
- ⚖️ Automatic rejection only for exact duplicates (when auto-reject is on) or when at least two independent signals agree
- 🎛️ Admin toggles for the check, auto-reject, strict mode and multi-model, plus a learning report that tunes per-model weights from admin approve/reject decisions

### 🌐 Automatic Translation Engine & 16 Languages

- 🗺️ Built-in language catalog: Persian, English, Turkish, Arabic, Russian, German, French, Spanish, Italian, Portuguese, Chinese, Japanese, Korean, Dutch, Polish and Ukrainian
- 🏠 Offline-first: local Argos Translate and LibreTranslate need no API key; public translation APIs are not used unless explicitly allowed; Gemini/OpenRouter are optional providers
- 🛡️ Quality guard: placeholders, URLs, markup, code and emoji are protected and verified, and broken provider output is rejected
- ⚡ Strings missing from a language catalog are translated on the fly just before a message is sent
- 📊 Admin-panel translation dashboard: status, health, providers, history, live logs, per-language and bulk sync
- ✍️ Admin-written content (broadcasts, product names, etc.) is never auto-translated; background notifications use each recipient's language
- 🧰 Languages are chosen at install time; `manage.sh` options 33, 34 and 35 repair the runtime, remove LibreTranslate and delete unwanted languages to free disk space

### 🧠 AI Assistant Account Actions

Beyond answering questions, the assistant can prepare account actions that the bot then executes through its own validated flows.

- 🛒 Purchase with wallet and 🔄 renewal from wallet (with cost calculation), only after a separate explicit confirmation message from the user
- 🔁 Auto-renew toggle, QR code, individual configs, enable/disable, rename, new access link, transfer to another user and service history
- 🗑️ Deleting a service always ends with a final confirmation button
- 🎟️ Discount-code check, referral info, recent tickets and server countries
- 🙋 Refunds, complaints and financial disputes are still escalated to human support

### ➕ Add Existing Account

- 🔗 Users attach a service they already own by pasting its subscription link or (optionally) the config username; it is matched against your connected panels
- 🔒 Conflict protection: a config already linked to another account is refused, and repeated failures temporarily block the user
- 🎛️ The button and the username option can be switched off separately from the admin panel

### 📚 Contextual Tutorials

- 📍 Tutorials can be attached to specific bot sections: main-menu buttons, the purchase flow, each payment method, wallet actions and more
- 📚 A "Tutorial" button is added automatically under the matching page, with no handler changes needed
- 🎁 A tutorial can also be offered right after a successful purchase

### 📜 Terms & Conditions

- ✅ Admins can require users to accept written terms before using the bot
- 📲 The Mini App has its own accept flow, so acceptance is shared across both

### 🧾 Renewal Warnings & Log

- ⚠️ Users see the current state of a service (remaining time and traffic) before they confirm a renewal
- 📣 Every renewal (full, volume, time or extra users) is logged to the admin report group with before/after values

### 🎴 Gift Cards

- 🎁 In **Wallet → Gift Card**, users send a gift as a ready-made card image: wallet credit, one of their existing configs, or a newly purchased config, with an optional recipient name and message
- 🖼️ Admin-managed card themes: upload a base image, the AI detects where the text goes and exact Persian text is printed on it; a config's subscription link never appears on the image and is delivered only after redemption
- 🔗 Recipients redeem with the code or a deep link; senders can cancel unredeemed cards; admins can disable/enable a card, revoke it (the amount and fee, or the config, goes back to the sender), view its image and log, and manage themes (upload, enable/disable, re-detect layout, preview, delete)
- ⚙️ Settings (Marketing & Growth → Gift cards): master switch, switches for wallet/config/purchase gifts, minimum and maximum amount, fee percent, validity days and the maximum number of open cards per user; expired cards are closed automatically in the background

### 🔔 Product Waitlist

- ⏸️ Inactive products stay visible in the category list tagged "(inactive)"; tapping one puts the user on that product's waitlist
- 🔔 When an admin activates the product (from the bot, the Mini App admin or the web panel), every waiting user receives a "now available" message with a quick-buy button; the list is then cleared, sending is throttled and nothing is sent while the product has no stock

### 🤖 Telegram Userbot (AI Replies in Your Personal Chats)

- 🤝 An alternative to Telegram Business: the bot logs in to the owner's own Telegram account (MTProto) and answers customers in the owner's private chats through the AI support assistant. It is fully independent of Business, with its own settings, tables and admin menu (**Admin & Access → Userbot**)
- 🔑 Login and logout happen on the server: `python userbot.py login`, or `manage.sh` option 40 (Telegram accounts)
- ⏸️ Pauses automatically while the owner is active (per chat or globally) and resumes after a configurable away time; can run always or only outside working hours
- 🧑‍💼 Human-handoff chats with an optional automatic return timer, an exception list, an option to skip saved contacts, a first message and a persona text
- 🛒 Optional product cards, sending a customer's own config/QR inside the chat, voice/image understanding with an acknowledgement for other files, merging of quick consecutive messages and optional mark-as-read

### 📉 Churn Prediction & Win-back Offers

- 📊 Finds customers whose time since their last purchase exceeds 90% of their own usual purchase interval (at least one confirmed purchase is required), considers their live service usage and sends a personal renewal offer with a unique, time-limited discount code
- 🧠 Optional AI decision per customer (risk 0–100, offer or skip, discount percentage and expiry within your caps); with AI off a rule-based score is used
- 🎛️ Settings (Reminders & Alerts → Churn prediction): on/off (off by default), AI on/off, minimum risk score, default and maximum discount percent, code validity in hours, per-user cooldown days, maximum offers per run and the default purchase cycle; every decision is recorded

### 🧩 Custom Gateway Amount Options

- 🔢 Each custom (generic) payment gateway can send the amount as Toman, Rial or USD (USD is calculated from the order amount and the dollar rate) and apply an amount multiplier
- 🧾 Amount matching and tolerance checks still use the real Toman amount; the options are available in both the web panel and the Mini App gateway settings

### 🖧 Panel & Service Improvements

- 👥 Concurrent-user limit (`limitIp`) for panel-linked products on 3X-UI and Alireza: the base price includes one user, an extra-user price is set per product, and customers can add users later from the service page (increase only)
- 🧬 3X-UI multi-inbound: a product or server can use several inbounds selected by checkbox, with a backward-compatible fallback to the old single inbound
- ♾️ `0` GB or `0` days on panel-linked products means unlimited; a full renewal onto an unlimited plan now removes the old volume cap on the panel providers that support it
- 🔐 Panel login reuse: Alireza and IBSng cookies and Marzban/Marzneshin/PasarGuard tokens are cached in memory until they expire instead of logging in on every API call
- ⏯️ One button enables or disables all of a user's panel-linked configs (admin user view)
- 🌍 World map: the master subscription link is scanned (URI lists, Xray JSON and sing-box outbounds), server IPs are geolocated and real protocol-level health checks (including `httpupgrade`) decide online/offline, with CDN fallbacks and a local cache

### 🏆 Seasons, Lucky Boxes, Streaks & Daily Quiz

- 🏁 **Competitive referral seasons** — monthly seasons (Jalali months) ranked by points: points per new invite plus a bonus when the invited user buys. Ranks 1–3 get prizes (wallet credit, a discount code and/or a free product), badges (gold, silver, bronze and top 10) are recorded, users get a standings page, seasons start and close automatically and the result is announced in the promo channel; names are masked in public tables
- 🎁 **Lucky boxes** — admin-defined box types with prize lists and odds; users buy and open them with an opening animation, with a daily purchase limit per user and a validity period for prize codes
- 🔥 **Streaks and milestones** — consecutive days of use, successful invites and renewals are tracked with a progress bar, and reaching a milestone grants a reward (wallet credit or a time-limited discount code)
- ❓ **Daily channel quiz** — a question is posted to the promo channel every day at a set hour (Tehran time); users answer through a bot deep link and the first correct answers win a time-limited discount code. Questions come from an admin-managed question bank with an AI fallback, and the quiz closes automatically
- ⚙️ Every part is off by default and has its own switch, limits and prizes in the admin panel

### 🔄 Update from Inside the Bot

- 🔔 The bot reads the repository's `VERSION` file every few hours (default 6) and tells the owner and full admins when a newer version exists, with an "Update now" button
- 🛡️ After confirmation, `update_runner.sh` runs detached from the bot process (`systemd-run`): database and code backup → fetch the new code → install packages → syntax check → restart services → health check. If any step fails it rolls back to the previous version automatically, and the result is reported back to the admin
- 🧰 The update menu (owner and full admins, main bot only) shows the installed and latest versions, runs a manual check, shows release notes (`update.json`), updates with one button, rolls back to a previous snapshot and switches the automatic notice on or off
- 📦 For maintainers, `release.sh <version> "note" ...` bumps `VERSION`, writes `update.json`, commits and pushes. Nothing is sent to the developer: only a few text files are read from GitHub (with a jsDelivr mirror as fallback)

### 📞 Support Contact Methods

- 🔘 Admins can switch each support method on or off from the bot: AI assistant, direct chat with an admin, new ticket, my tickets and the admin-chat button. A switched-off method answers "currently unavailable", and the direct-chat button only appears when the admin ID is set

### 🧰 Full `manage.sh` Menu

| Option | Action |
|:---:|---|
| S | Web shop status |
| 1 | Full bot install (first time) |
| 2 | Update bot |
| 3 | Completely remove the bot from the server |
| 4 | View bot status |
| 5 | View live logs |
| 6 | Restart bot |
| 7 | Stop bot |
| 8 | View sales stats |
| 9 | Change admin token or ID |
| 10 | Set up the web shop (domain + SSL + service) |
| 11 | Remove the web shop (service + nginx, SSL kept) |
| 12 | Update the web shop |
| 13 | Configure the email service (SMTP verification codes) |
| 14 | Configure Cloudflare Turnstile (web shop protection) |
| 15 | Set up the Mini App (automatic: domain + SSL + service) |
| 16 | Remove the Mini App |
| 17 | Update the Mini App |
| 18 | Set up the admin panel (domain + SSL + service) |
| 19 | Remove the admin panel |
| 20 | Update the admin panel |
| 21 | Generate VAPID keys (admin panel push) |
| 22 | Add a domain proxy for a VPN panel (share port 443) |
| 23 | List panel/config domain proxies |
| 24 | Remove a VPN panel domain proxy |
| 25 | Mini App / admin panel domains (view + delete) |
| 26 | Set up the Integration API (domain + SSL + service) |
| 27 | Remove the Integration API |
| 28 | Update the Integration API |
| 29 | Set up the dedicated sub server (domain + SSL + service) |
| 30 | Turn the dedicated sub ON / OFF |
| 31 | Update the dedicated sub server |
| 32 | Remove the dedicated sub server |
| D | Dedicated sub status |
| 33 | Install/repair the local translation runtime (automatic) |
| 34 | Remove LibreTranslate |
| 35 | Remove unwanted translation languages (free disk space) |
| 36 | Full cleanup / factory reset |
| 37 | Restore a backup (new-server migration wizard) |
| 38 | Bot update mode (Polling / Webhook) |
| 39 | Change the admin panel username/password |
| 40 | Telegram accounts: log in the userbot (AI replies to customers), log in a separate leak-scanner account (recommended) or use one account for both, show status, log out either account |
| L | Language (English ⇄ فارسی) |
| 0 | Exit |

</details>

---

<a id="bot-reference"></a>

## 🤖 Bot Features — Complete Reference

<details>
<summary><strong>Full list of bot, admin-menu and delivery features (click to expand)</strong></summary>

Everything below is implemented in the code (v9.2.0) and complements the sections above.

### ⌨️ Bot Commands

| Command | Who | What it does |
|---|---|---|
| `/start` | Everyone | Entry point; also handles deep links (product, discount code, test config, lucky wheel, referral `ref<id>`, reseller `resref_<id>`) |
| `/buy` · `/charge` · `/help` | Users | Open the purchase menu, wallet top-up and the tutorial/help text |
| `/language` | Users | Choose the interface language |
| `/transfer_wallet` | Users | Transfer wallet balance to another user |
| `/smartsub` | Users | Merge several services into one smart subscription link |
| `/merge CODE` | Users | Merge a web-shop account with the Telegram account |
| `/myssh` | Users | Receive own SSH credentials (private chat only) |
| `/reseller_link` | Commission resellers | Personal link plus commission statistics |
| `/ai` · `/admin` · `/update` | Admins | Admin AI assistant, admin panel, in-bot update |
| `/token2` | Admins | Issue a personal Integration API token (the previous one is revoked) |
| `/bot_off` · `/bot_on` · `/bot_status` | Admins | Global bot switch |
| `/pin` · `/unpin` | Admins | Reply to a message in a group/channel to pin or unpin it |
| `/seasonadmin` · `/giftadmin` | Admins | Shortcuts to the seasons/quiz and gift-card admin screens |
| `/wstats` `/wfeatures` `/wqueue` `/whealth` `/wusers` | Admins | Telegram widgets (see below) |
| `/wservices` · `/wwallet` | Users | "My services" and "Wallet & invite" widgets |

### 🧩 Telegram Widgets

- 📊 **Admin widgets** inside the message: statistics with Today / 7 days / 30 days / All tabs and a 14-day chart, feature toggles (bot status, terms, phone verification, smart subscription), approval queue cards with approve/reject (with a second confirmation), panel health lights with live check and latency, quick user management (newest, blocked, top balances, block/unblock, quick top-up), live pulse, alerts center, leaderboards and sales analysis (30-day heat map, category share, peak hours)
- 🎚️ **User widgets**: custom-plan sliders (volume/days) for the personal-config builder, "My services" with quick actions, "Wallet & invite" with top-up presets
- 🔒 Private chat only; can be disabled with `SHOPVPN_WIDGETS=0` or the `widgets_enabled` setting

### 🛒 Purchase & Catalog

- 🧠 **Smart buy guide (AI)** — a few button questions followed by a free chat; only real products are suggested (including each product's "AI note"), and nothing is charged without the user's own confirmation on a real purchase card. The questions (up to 8 × 8 options) and the tone prompt are editable (`buy_guide_questions`, `buy_guide_prompt`); safety rules stay locked in code. Works in the bot and the Mini App
- 💲 **Discount display** — the pre-discount price is shown struck through next to the new price (display only; payment always uses the real price)
- 🔄 **Full-renewal rules per product** — switches for: renewable on/off, only same-type services (unlimited vs. volume), full reset, carry remaining volume, carry remaining time (reset disables both carry options)
- 🏷️ **Account naming modes per panel** — 8 modes for auto-provisioned usernames: user-chosen name, hash + name, prefix + name, name + suffix, counter + name, prefix + counter, counter + suffix, Telegram ID + counter (affix up to 12 characters)
- 🧩 **Multi-panel products** — one product can target several panels and SSH nodes with a per-panel configuration; capacity is checked on every panel, and delete/disable actions are synchronised to the extra panels
- 🗂️ **Category descriptions with a photo** (also shown in the web shop) and configurable emojis for category, product and test-plan buttons
- 📱 **Phone verification gate** — purchases can be limited to verified phone numbers by country code (Telegram share-contact button; Iran by default, 20+ countries in the list)
- 📢 **Unlimited mandatory-channel list** — any number of required channels (the old single-channel setting keeps working)
- 🎁 **Welcome config gift** — a service from a chosen panel-linked product (volume/days, `0` = unlimited) is created and sent to every new user after a delay such as `30m`, `2h` or `3d`; once per user, only for users who join after activation

### 📦 Delivery (new in 9.2.0)

- 📝 **Per-product delivery text and sticker** sent right after the config
- 🎞️ **Post-delivery media message** (text, photo, sticker or a whole album copied from any chat), with a separate one for test configs
- 📨 **Delivery message template per panel type** (14 templates: generic, PasarGuard, 3X-UI, Marzban, Marzneshin, Hiddify, Alireza, Rebecca, S-UI, WGDashboard, MikroTik, IBSng, W-UI, Stealth)
- 📎 **WireGuard / AmneziaWG / OpenVPN files** from SSH/Linux nodes and panels such as W-UI are sent as documents at delivery (`deliver_vpn_files_enabled`; max 20 files, 200 KB each)
- 📦 **"Delivered subscriptions" report topic** — every delivered subscription is logged with copyable links
- 💳 **Card-to-card per card**: an optional photo and a description template for each card; "beautiful" or "classic" message style, copy buttons (card number, Toman, Rial, holder name) with selectable colors, content protection against copy/forward/screenshot, bank-name display

### 👑 Admin Menu (in the bot)

The admin panel has 10 categories — Products & sales, Finance, Alerts & retention, Infrastructure, Resellers, Marketing & growth, Communication, Support & AI, Appearance, Management — each with a built-in help button describing every item.

- 📢 **Broadcast menu** — to one user, to everyone, forward to everyone, expired accounts, active users, inactive users, test-only users, to the channel; background job with progress status and cancel; photos and albums supported; scheduled broadcasts keep their media and target; the admin gets a preview copy first
- 🔎 **Config search** — find the owner of a config by panel sub link, dedicated sub link/token, config ID or username; actions: enable/disable, auto-renew, rename, transfer, history, add volume/days, new sub token, cut access + new link, full delete
- 👤 **User card** — full config list and per-config management, enable/disable all configs, direct message, personal discount code, wallet edit, block/unblock
- 🧭 **Link management** — Mini App, web shop, web panel, dedicated sub and support links in one place, health probe, editing the sub/support/panel URLs without server access, sub-link lookup for a service
- 🚚 **Panel user migration** — moves all active services between panels (even different panel types): remaining volume/time are read from the source, the user is created on the target, the record is switched, and the new user is rolled back if switching fails; options: notify users, retarget sales, disable old users, estimate from the database when the source is down. Owner/senior admins, main bot only. A resync tool repairs old users after a node/host/group change
- 🎛️ **Main-menu display** — reply menu and inline menu enabled separately, 1 or 2 buttons per row; separate color settings for the admin panel and the purchase flow; Mini App button name and color
- 📝 **Admin audit forwarding** — every admin action (bot, web panel, Mini App) is forwarded to the "📝 Admin log" topic with secrets masked
- 🪪 **Bot profile** — "description" (512 chars) and "short description" (120 chars) in Persian and English, synchronised to Telegram (only changes are sent)
- 🎁 **Welcome gift, signup gift, wallet top-up/deduct in bulk, gift cards, seasons, quiz, lucky boxes** each have their own menu and switches

### 🖥️ Web Panel Additions

- 👥 **Dynamic user groups** — saved groups defined by rules over join date, blocked, phone-verified, wallet balance, purchase count, total purchases, last purchase, top-ups, active services, expiry date and referrals
- 🩺 **Hourly system checks** — panels, capacity, stock, server resources, backups, config scan, exchange rate, renewal loop, database, SSH nodes, payment gateways, AI, translation, sessions, SMTP and SSL-certificate expiry, shown on the dashboard
- 🛰️ **Stealth VLESS node** — a panel type installed in one step from an IP, root password and domain; the agent builds the subscription itself (no inbound or template needed)

### 🔎 Ported from the Persian Documentation

- 🎁 Signup gift for users without a purchase; 💸 automatic service refund based on real unused volume
- 📖 Step-by-step connection tutorials per device (also offered right after purchase) and contextual tutorials attached to bot sections
- 🧾 Every bot text editable from the web panel (the AST-based text scanner finds all `db.get_text(...)` texts)
- 🔌 Global bot on/off switch · 🕵️ referral-fraud alerts · 📶 connect / not-connected alerts · 📣 channel notice for finished/deleted configs
- 🗳 Order satisfaction surveys (1–5 stars, per panel) and ⭐ per-service star ratings
- 🎁 Early full-renewal discount · ➕➖ bulk wallet credit/deduction with before/after preview
- 🧩 Personal config builder with per-product panel, ranges, flat or tiered pricing and allowed payment methods
- 🛠 Service management from "My Account": auto-renew from wallet, enable/disable, rename, transfer, extra users, cut access + new link, delete with refund, history; each button has its own switch
- 💸 Wallet transfers · 🧾 wallet ledger with before/after balance · 💳 payment methods restricted per product
- 🔗 Multiple domains/IPs per server for sub links · 📎 smart subscription (`/sub/smart/<token>`, needs the dedicated sub server)
- 🔧 3X-UI tools: create inbounds, panel backup/restore, full panel statistics · 🎛 per-server usage flags (personal purchase, test, reseller)
- 🗄 Full backup (main bot + all reseller databases) and restore, secondary destinations (second Telegram chat, SFTP) · 🏭 owner-only factory reset · 🧹 orphan-config cleanup
- ⏰ Scheduled broadcasts · 🔘 automatic Mini App menu-button sync · 📈 advanced statistics (trends, per-gateway success rate, funnel, hourly activity)
- 🔗 In-bot deep-link builder (purchase, product, discount code, test config, lucky wheel, custom parameter; counts as mandatory-channel exemption and records the source)
- 🟢 Live-chat routing by admin presence · 🔀 multi-level referral and fraud suspension · 💳 reseller postpaid credit · 🌐 resellers without a bot

</details>

---

<a id="additional-features"></a>

## 🔎 Additional Features

<details>
<summary><strong>Click to expand</strong></summary>

- 🩺 VPN panel health monitoring
- 📊 Advanced sales and activity analytics
- 📣 Topic-based reporting
- 🎁 Bulk gifts
- 🧹 Expired-service cleanup
- 🔌 Token-scoped Integration API
- ⏸️ On-hold services
- 📦 Panel capacity limits
- 📍 Service migration
- 💰 Bulk price editing with undo
- 💸 Cashback
- 🎁 Wallet gift codes
- 🪙 Coins and lottery
- ⭐ Order/service ratings
- 💸 Wallet transfers
- 🧾 Wallet transaction ledger
- 📦 Configurable delivery modes and QR backgrounds
- 🔗 Multi-domain subscription links
- 🧩 Custom configuration-builder products
- 🛠️ 3X-UI utilities
- 🗄️ Multi-bot backup/restore
- 📨 Secondary backup destinations
- 🏭 Owner-only factory reset
- ⏰ Scheduled broadcasts
- 🔘 Automatic Mini App menu-button synchronization
- 🔗 Advertising/deep-link tracking
- 🟢 Admin-presence routing
- 🔔 Pending-invoice push notifications
- 🖼️ Mini App banner/catalog management
- 🔀 Multi-level referral commissions and fraud suspension
- 💳 Reseller postpaid credit
- 📉 Reseller-tier quantity discounts
- 🌐 Resellers without their own Telegram bot through the web API
- 🎴 Gift cards
- 🔔 Product waitlist notifications
- 🤖 Telegram userbot AI replies
- 📉 Churn prediction and win-back offers
- 🧠 Admin AI assistant
- 🏛️ Optional bank inquiry for receipt checks

</details>

---

<a id="dedicated-sub"></a>

## 🔗 Dedicated Subscription Server

Subscription links are served from your own domain (the panel address is never exposed). Opened in a browser, a link shows a web page (black-and-white design with light/dark mode) with usage, expiry, a usage chart, configs, QR codes, an "Add to app" button and app lists for iOS / Android / Windows / macOS / Linux; VPN apps receive the same link as a normal subscription.

- **First-time setup (only from `manage.sh`)**: option 29 (domain, nginx, SSL, `v2raybot-sub` service on port 8004, saves `DEDICATED_SUB_URL`), 30 on/off, 31 update, 32 remove (`D` shows the status). Point the domain's A record to the server first.
- **Everything else is configured in the Telegram bot**: Admin panel → Products & configs → Dedicated sub — on/off (no restart), page look (sections, brand, logo, notice, support, footer, theme), sub output (profile title, update interval, "first line" with remaining volume/days, placeholder config for expired/exhausted services), apps (hide/show, recommended, custom apps), FAQ, stats and access log.
- Turning it off keeps already-issued links working (plain pass-through) while new links use the panel address again.
- `/sub/smart/<token>` (`/smartsub`) is also served by this server and merges several subscriptions into one link.
- Code: `dedicated_sub.py` (core), `sub_server/` (server + web page), `admin_dedicated_sub.py` (bot menu), `db/dedicated_sub.py`; tests: `python -m unittest test_dedicated_sub`.
- The output format (Clash / sing-box / v2ray) is chosen by the panel from the app's User-Agent, which the sub server forwards. The "first line" and placeholder config apply only to link-list subscriptions (vless/vmess/...).

<a id="contributing"></a>

## 🤝 Contributing & License

<details>
<summary><strong>Click to expand</strong></summary>

Bug reports, feature suggestions, documentation improvements and pull requests are welcome.

Before opening a pull request:

1. Keep secrets and production credentials out of the repository.
2. Preserve database compatibility where possible.
3. Run relevant Python/JavaScript checks.
4. Keep Persian and English user-facing text synchronized through the i18n layer.

### 📄 License

This project is released under the **MIT License**.

### 👤 Author

Created by **Mehdi Rafatpanah**

- Telegram: [@celenor](https://t.me/celenor)
- GitHub: [@mehdirafatpanah](https://github.com/mehdirafatpanah)

</details>

---

## 🌍 Documentation Languages

- 🇬🇧 **English:** `README.md`
- 🇮🇷 **Persian:** `README.fa.md`
- 🇷🇺 **Russian:** `README.ru.md`
- 🇨🇳 **Chinese:** `README.zh.md`

The application supports multiple UI languages with persisted user language selection and automatic RTL/LTR switching. The built-in catalog has 16 languages (Persian, English, Turkish, Arabic, Russian, German, French, Spanish, Italian, Portuguese, Chinese, Japanese, Korean, Dutch, Polish, Ukrainian); they are chosen at install time and managed from the admin panel's language manager, which auto-generates the in-app translations.
<!--‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍-->
<!-- 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 -->
