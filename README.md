[🇬🇧 English](README.md) | [🇮🇷 فارسی](README.fa.md)

<div align="center">

# 🛰️ ShopVPN — Smart V2Ray Configuration Sales Bot

**An automated Telegram V2Ray sales platform with a dedicated Mini App, AI support assistant, Android management app, three management panels, multi-level reseller support, and a full Persian/English UI.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-MiniApp%20%2B%20Panel-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![Made by](https://img.shields.io/badge/Made%20by-Mehdi%20Rafatpanah-orange?style=for-the-badge)](https://github.com/mehdirafatpanah)

</div>

---

## 📚 Table of Contents

- [📖 Overview](#overview)
- [✨ Features](#features)
- [🧠 AI Support Assistant](#ai-support)
- [💳 Payment Gateways](#payment-gateways)
- [📲 Telegram Mini App](#miniapp)
- [🖥️ Standalone Web Admin Panel](#admin-panel)
- [📱 Android Management App](#android-app)
- [🔌 Supported VPN Panels](#vpn-panels)
- [🖥️ Requirements](#requirements)
- [🚀 Automatic Installation](#auto-install)
- [🛠️ Manual Installation](#manual-install)
- [⚙️ Environment Variables](#env-vars)
- [🧰 manage.sh](#manage-sh)
- [🗂️ Project Structure](#project-structure)
- [🧪 Technology Stack](#tech-stack)
- [🔎 Additional Features](#additional-features)
- [🤝 Contributing](#contributing)
- [📄 License](#license)

<a id="overview"></a>

## 📖 Overview

**ShopVPN** is a production-oriented Telegram bot for selling and managing V2Ray/VPN configurations. It is written in Python with **aiogram 3** and combines automated provisioning, multiple payment methods, reseller management, an AI support layer, a Telegram Mini App, a standalone web administration panel, and an Android management application.

The project is designed for real-world operation rather than a simple demo. It supports multiple VPN panels, automatic delivery, configurable products and plans, wallets, referrals, discounts, support tickets, monitoring, backups, reporting, and independent reseller bots.

### 📢 Official links

- 📢 **Project channel:** [@celenorbot](https://t.me/celenorbot)
- 👤 **Author:** [@celenor](https://t.me/celenor)
- 💎 **Donation addresses:**
  - `USDT-BNB (BEP20):` `0x3c026D27DEbE24d659d6dDcF074b3063Fd47bc63`
  - `USDT-TRX (TRC20):` `TBm712Gdcbfp3Tkv1CpNgfwUfKuFNn8iWE`

> **Security note:** never commit real bot tokens, API keys, database credentials, private keys, or production secrets to Git. Store them in environment variables or the project configuration system.

<a id="features"></a>

## ✨ Features

### Quick summary

- 🔑 Automatic provisioning on multiple VPN panels plus manual configuration inventory
- 💳 Multiple automated payment methods, including card-to-card, crypto, Telegram Stars, and online gateways
- 🧠 AI support assistant with selectable providers
- 🔄 Flexible service renewal by custom traffic/time amounts
- 🏢 Independent and linked reseller modes with multi-level referrals
- 🖥️ Three management layers: Telegram admin bot, web panel, and Android app
- 📲 Telegram Mini App storefront with wallet, orders, tickets, referrals, and service management
- 🌍 Live server map and panel health monitoring
- 🌐 Both Telegram Polling and Webhook operation modes
- 🚀 Anti-spam, scheduled reports, backups, cashback, coins, lottery, gifts, campaign links, and Integration API
- 🌍 Full **Persian / English** UI with persisted per-user language selection

### 🤖 Main bot

- Unique configuration inventory per user and automatic provisioning from supported VPN panels
- Direct product-to-panel assignment for products that should create a real user immediately after payment
- Free-form renewal with administrator-configurable traffic/day pricing
- Unified **My Account** hub for purchased, gifted, and test services
- Multi-plan test configurations with independent panel, traffic, duration, and naming rules
- Multi-quantity purchases with automatic total calculation and batch delivery
- Automatic USD/USDT-to-local-currency rate lookup with fallback sources and manual fallback rates
- Internal wallet with top-up requests, receipts, and administrator approval
- Category/product management with stock, pricing, and activation controls
- User blocking and mandatory channel membership
- Live subscription information and expiration/traffic reminders
- Low-stock alerts for administrators
- Configuration delivery as text and QR code
- Full support-ticket flow and live support chat
- Customizable main-menu layout, button visibility, labels, and colors
- Store branding controls for the shop name and Mini App banner
- Independent reseller bots with isolated databases and shared dispatcher support
- Persistent FSM state on SQLite so interrupted conversations survive restarts
- Temporary messages and automatic cleanup of sensitive card/payment messages
- Advertising/channel post utilities and deep-link buttons

### 🤝 Resellers, referrals, discounts and wallet

- **Linked reseller** mode inside the main bot
- Independent reseller bots with separate catalogs and payment settings
- Referral links with multiple reward models
- Percentage-based purchase commissions
- Fixed wallet rewards per invited user
- Free configuration rewards after a configurable referral threshold
- Discount codes with usage limits, expiration, audience, and product/category scope
- Lucky wheel with configurable rewards, probabilities, cooldown, and expiration
- Reseller tiers, fees, expiration, renewal reminders, quantity discounts, and credit limits
- Commission-only referral/reseller links without a separate catalog
- Product-based reseller supply as an alternative to traffic-based supply

### 👑 Telegram admin panel

- Owner, Admin, Mid-level Admin, and Support roles
- Broadcast messaging
- Sales statistics with date-range filters
- Full administrator audit logs
- Automatic daily database backups to Telegram
- Immediate backup and full database restore
- Jalali/Persian calendar support where applicable
- User management, wallet operations, products, categories, gateways, panels, resellers, referrals, discounts, support, reports, and system settings

<a id="ai-support"></a>

## 🧠 AI Support Assistant

The AI support layer can answer repetitive customer questions before escalating to a human administrator.

- 🔌 Selectable providers such as Gemini, Groq, and OpenRouter
- 📚 Administrator-managed FAQ knowledge
- 🔎 Real user-specific answers for services, expiration, wallet, and orders through database function calls
- 🛒 Real purchase cards with current prices and payment buttons
- 🔒 No direct financial/write operations from the AI layer; final actions remain behind normal user confirmation flows
- 🙋 Automatic escalation to human support for financial complaints or explicit requests
- ⚡ If no provider/API key is configured, the conversation can immediately be routed to human support

<a id="payment-gateways"></a>

## 💳 Payment Gateways

The project contains independent payment adapters so several methods can be enabled at the same time. Depending on configuration, supported methods include:

| Method | Confirmation | Notes |
|---|---|---|
| 💳 Manual card-to-card | Admin approval | Receipt/image based flow |
| 📲 Bank SMS card-to-card | Automatic | Unique invoice amount, rotating cards, configurable timeout |
| 🏧 Aban Gateway | Automatic | API-based invoice and verification |
| 💎 Plisio | Automatic | Crypto payments with callback/signature validation |
| 🔵 Blupal | Automatic | Automated card-to-card alternative |
| ⭐ NoaPay / Telegram Stars | Automatic | Telegram Stars payment flow |
| 🟡 ZarinPal | Automatic | Main bot gateway |
| 🔵 Mr. Pardakht | Automatic | Main bot gateway |
| 💸 Tetra98 | Automatic | Main bot gateway |
| 💳 CubePay | Automatic | Main bot gateway |
| 💰 NowPayments | Automatic | Crypto invoice and IPN verification |
| ⭐ Telegram Stars | Automatic | Native `XTR` invoices |
| 🧩 Generic Gateway | Automatic | Define HTTP API, headers/body, response paths and webhook authentication without writing code |

All gateways are isolated from each other and can be enabled or disabled independently.

<a id="miniapp"></a>

## 📲 Telegram Mini App

The `miniapp/` directory contains a full Telegram Mini App with both a customer storefront and a web administration interface.

### 🛍️ Customer side

- FastAPI backend with secure Telegram `initData` HMAC-SHA256 verification
- Modern responsive storefront
- Products, cart, wallet, lucky wheel, referrals, and test configurations
- Expiration and traffic alerts
- Add subscriptions directly to popular VPN applications through platform-specific deep links
- Support tickets and live support chat
- Persian/English language switch with automatic RTL/LTR document direction

### 🛠️ Web administration side

- Dashboard and order exports
- Category, product, panel, and configuration management
- Reseller management and bot-token validation
- Discount codes, lucky wheel, referrals, renewal reminders, and traffic reminders
- User search, blocking, direct messaging, and targeted broadcasts
- Wallet lookup and manual balance adjustments
- Branding, color theme, and store header customization
- Main Telegram menu layout management
- Ticket/support management
- System and administrator logs
- Immediate backup and database restore

<a id="admin-panel"></a>

## 🖥️ Standalone Web Admin Panel (`admin_panel`)

The `admin_panel/` package provides a standalone web administration experience parallel to the Telegram admin interface.

It includes role-based access control, dashboard statistics, product/catalog management, payment configuration, VPN panel management, user and reseller tools, support tickets, backups, reports, branding, and operational settings.

The web UI supports **Persian and English**, persists the selected language, and switches between RTL and LTR automatically.

<a id="android-app"></a>

## 📱 Android Management App

The project includes infrastructure for an Android management application, including:

- Secure administrator authentication
- Push notifications through FCM
- Dynamic settings/branding schema
- Telegram/web-panel integration
- Background notification and operational workflows
- Remote configuration updates without requiring an application release for every UI/settings change

<a id="vpn-panels"></a>

## 🔌 Supported VPN Panels

The provisioning layer is designed to work with several VPN/server management systems, including:

- PasarGuard
- Marzban
- Marzneshin
- Hiddify
- 3X-UI
- Alireza X-UI
- Rebecca
- S-UI
- WGDashboard
- MikroTik
- IBSng

Panel availability depends on the specific feature and adapter implementation. Some operations are panel-specific.

<a id="requirements"></a>

## 🖥️ Requirements

Typical deployment requirements:

- Linux server/VPS
- Python **3.10+**
- SQLite for the default database layer
- A Telegram bot token
- A public HTTPS domain when using the web panel/Mini App or webhook features
- Appropriate API credentials for the payment/VPN providers you enable
- Optional Android/FCM credentials when using push notifications

The exact Python packages are listed in the project requirements files.

<a id="auto-install"></a>

## 🚀 Automatic Installation

The project provides `manage.sh` to simplify deployment and maintenance. On a fresh Linux server, make the script executable and run it:

```bash
chmod +x manage.sh
./manage.sh
```

Follow the interactive setup. The script provides installation, configuration, service management, backup, restore, Mini App, panel, and operational utilities.

> The exact menu entries can change as the project evolves. Use `./manage.sh` itself as the authoritative list for the current version.

<a id="manual-install"></a>

## 🛠️ Manual Installation

A typical manual deployment is:

```bash
git clone <your-repository-url>
cd Shopvpn
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure the required environment variables, initialize the database/configuration, and start the bot and the required web services.

For production, run the services under a process manager such as systemd/supervisor and put the web applications behind a reverse proxy with HTTPS.

<a id="env-vars"></a>

## ⚙️ Environment Variables (`.env`)

The exact variables depend on the enabled features. Common configuration areas include:

- Telegram bot token and owner/admin identifiers
- Database path and storage settings
- Web/Mini App domain and authentication settings
- Payment gateway API keys
- VPN panel URLs, usernames, passwords, tokens, and IDs
- AI provider/API keys
- Webhook secret/token settings
- Backup destinations and SFTP credentials
- FCM/Android push credentials

**Never commit production secrets to the repository.** Use `.env`, server-side secrets, or the project's secure configuration mechanism.

<a id="manage-sh"></a>

## 🧰 `manage.sh`

`manage.sh` is the main operational helper. Depending on the current version it can be used for:

- Installation and dependency setup
- Environment/configuration management
- Starting/stopping/restarting the bot
- Installing or managing the Mini App and web panel
- Backup and restore operations
- VPN panel setup/maintenance
- Logs and service diagnostics
- Integration API setup

The management menu itself supports Persian and English. The selected language can be persisted.

<a id="project-structure"></a>

## 🗂️ Project Structure

```text
Shopvpn-main/
├── server.py                 # Main bot/service entry point
├── bot_manager.py            # Bot and reseller lifecycle management
├── handlers_admin.py         # Telegram admin handlers
├── payment_*.py              # Payment integrations and delivery flows
├── ai_support.py             # AI support assistant
├── db/                       # Database models and data-access layer
├── miniapp/
│   ├── server.py             # Mini App backend
│   └── static/               # Customer Mini App frontend
├── admin_panel/
│   ├── server.py             # Standalone web admin backend
│   └── static/               # Web admin frontend
├── manage.sh                 # Deployment/maintenance helper
├── requirements*.txt         # Python dependencies
├── VERSION                   # Application version
├── README.md                 # English documentation (default)
└── README.fa.md              # Persian documentation
```

<a id="tech-stack"></a>

## 🧪 Technology Stack

- **Python 3.10+**
- **aiogram 3.x** for Telegram Bot API integration
- **FastAPI** for Mini App and web services
- **SQLite** for the default persistent data layer
- HTML/CSS/JavaScript for web frontends
- Telegram Mini Apps / WebApp authentication
- FCM for Android push notifications
- Multiple HTTP/API integrations for VPN panels, payments, AI providers, and external services

<a id="additional-features"></a>

## 🔎 Additional Features

The codebase also contains a number of operational and advanced features, including:

- 🩺 VPN panel health monitoring and recovery alerts
- 📊 Daily sales reports and advanced statistics
- 📣 Topic-based report groups
- 🎁 Bulk gifts for traffic/time
- 🧹 Automatic cleanup of expired services and orphaned records
- 🔌 Token-scoped Integration API
- ⏸️ On-hold services that start expiration on first connection for supported panels
- 📦 Per-panel service capacity limits
- 📍 Service location/panel migration with configurable fees and quotas
- 💰 Bulk product price editing with rounding and undo support
- 💸 Renewal/wallet cashback
- 🎁 Wallet top-up gift codes
- 🪙 Coins and scheduled lottery rewards
- 🎫 Department-based support tickets and outage reports
- ⭐ Order and service rating systems
- 💸 Wallet transfers between users
- 🧾 Wallet transaction ledger with before/after balances
- 📦 Configurable delivery modes and QR backgrounds
- 🔗 Multi-domain subscription links
- 🧩 Custom configuration builder products
- 🛠️ 3X-UI management utilities
- 🗄️ Full multi-bot backup/restore workflows
- 📨 Secondary Telegram/SFTP backup destinations
- 🏭 Factory-reset workflow restricted to the owner
- ⏰ Scheduled broadcasts
- 🔘 Automatic Telegram Mini App menu-button synchronization
- 📈 Advanced sales, gateway, campaign, reseller, retention, and activity analytics
- 🔗 Advertising/deep-link tracking
- 🟢 Admin-presence routing for live support
- 🔐 Separate web-admin permissions
- 🔔 Pending-invoice push notifications
- 🖼️ Mini App banner and catalog management
- 🔀 Multi-level referral commissions and fraud suspension
- 💳 Reseller postpaid credit
- 📉 Reseller-tier quantity discounts and upgrades
- 🌐 Resellers without their own Telegram bot through the web self-service API

<a id="contributing"></a>

## 🤝 Contributing

Bug reports, feature suggestions, documentation improvements, and pull requests are welcome.

Please use the repository [Issues](https://github.com/mehdirafatpanah/Shopvpn/issues) for discussions and bug reports.

Before opening a pull request:

1. Keep secrets and production credentials out of the repository.
2. Preserve backward compatibility for existing database installations where possible.
3. Run the relevant Python/JavaScript syntax checks.
4. Keep Persian and English user-facing text synchronized through the project's i18n layer.

<a id="license"></a>

## 📄 License

This project is released under the [MIT License](LICENSE).

## 👤 Author

Created by **Mehdi Rafatpanah**

- Telegram: [@celenor](https://t.me/celenor)
- GitHub: [@mehdirafatpanah](https://github.com/mehdirafatpanah)

<div align="center">

If this project is useful to you, consider giving it a ⭐

</div>

---

## 🌍 Documentation Languages

GitHub opens **English (`README.md`) by default**.

- 🇬🇧 **English:** `README.md` — default repository documentation
- 🇮🇷 **Persian:** [`README.fa.md`](README.fa.md)

The application itself also supports Persian and English through the shared i18n layer. User language is persisted, `/language` and the main-menu language button can switch languages, and the web interfaces automatically switch between RTL and LTR.
