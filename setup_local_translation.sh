#!/bin/bash
# Fully automatic local translation setup for ShopVPN.
# Installs system/Python prerequisites, Argos Translate and the language models
# required by ShopVPN. No API key is required and public translation APIs are
# never enabled by this script.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python3}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONUNBUFFERED=1

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "ERROR: root privileges are required to install system packages." >&2
    exit 1
  fi
}

install_system_prereqs() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "[translation] Installing system prerequisites..."
    as_root env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      python3 python3-pip python3-venv ca-certificates curl >/dev/null
  elif ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required on this operating system." >&2
    exit 1
  fi
}

install_system_prereqs

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[translation] Creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel >/dev/null
"$PYTHON_BIN" -m pip install -q 'argostranslate>=1.11.0'

# Ask the project's own language registry which target languages are needed.
# This avoids maintaining a second hard-coded language list in the installer.
mapfile -t TARGETS < <(SHOPVPN_ROOT="$ROOT_DIR" "$PYTHON_BIN" - <<'PY'
import os
import sys
sys.path.insert(0, os.environ["SHOPVPN_ROOT"])
from i18n import LANGUAGE_CATALOG
for code in sorted(LANGUAGE_CATALOG):
    if code not in {"en", "fa"}:
        print(code)
PY
)

# Argos package metadata is public/open and does not require an API key.
"$VENV_DIR/bin/argospm" update

install_pair() {
  local pair="$1"
  echo "[translation] Installing Argos model: $pair"
  if ! "$VENV_DIR/bin/argospm" install "translate-${pair}"; then
    echo "[translation] Warning: model translate-${pair} is unavailable; continuing." >&2
  fi
}

for lang in "${TARGETS[@]}"; do
  install_pair "en_${lang}"
done

# The admin panel can contain raw Persian strings that need direct fa -> en.
install_pair "fa_en"

# Keep public providers disabled unless an operator explicitly opts in.
ENV_FILE="$ROOT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  if grep -q '^SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS=' "$ENV_FILE"; then
    sed -i 's/^SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS=.*/SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS=0/' "$ENV_FILE"
  else
    printf '\nSHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS=0\n' >> "$ENV_FILE"
  fi
fi

# ---------------------------------------------------------------------------
# Self-hosted LibreTranslate (free, local, no API key).
# The bot uses this service first; Argos remains available as a direct
# in-process fallback. LibreTranslate documents --load-only as the way to
# limit the installed/loaded model set.
# ---------------------------------------------------------------------------
LIBRETRANSLATE_DIR="${SHOPVPN_LIBRETRANSLATE_DIR:-$HOME/.shopvpn-libretranslate}"
LIBRETRANSLATE_SERVICE="${SHOPVPN_TRANSLATION_SERVICE:-v2raybot-libretranslate}"
LIBRETRANSLATE_PORT="${SHOPVPN_LIBRETRANSLATE_PORT:-5050}"
LIBRETRANSLATE_VENV="$LIBRETRANSLATE_DIR/venv"
LIBRETRANSLATE_BIN="$LIBRETRANSLATE_VENV/bin/libretranslate"

if command -v systemctl >/dev/null 2>&1; then
  echo "[translation] Installing/updating self-hosted LibreTranslate..."
  mkdir -p "$LIBRETRANSLATE_DIR"
  if [ ! -x "$LIBRETRANSLATE_BIN" ]; then
    python3 -m venv "$LIBRETRANSLATE_VENV"
  fi
  "$LIBRETRANSLATE_VENV/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$LIBRETRANSLATE_VENV/bin/pip" install -q --upgrade 'libretranslate>=1.9.6'

  LOAD_ONLY="en,fa,tr,ar,ru,de,fr,es,it,pt,zh,ja,ko,nl,pl,uk"
  SERVICE_FILE="/etc/systemd/system/${LIBRETRANSLATE_SERVICE}.service"
  sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=ShopVPN self-hosted LibreTranslate
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$LIBRETRANSLATE_DIR
Environment=HOME=$HOME
Environment=PYTHONUNBUFFERED=1
ExecStart=$LIBRETRANSLATE_BIN --host 127.0.0.1 --port $LIBRETRANSLATE_PORT --load-only $LOAD_ONLY --update-models --disable-web-ui --disable-files-translation
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable "$LIBRETRANSLATE_SERVICE" >/dev/null 2>&1 || true
  sudo systemctl restart "$LIBRETRANSLATE_SERVICE"

  echo -n "[translation] Waiting for LibreTranslate"
  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${LIBRETRANSLATE_PORT}/languages" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
    printf '.'
  done
  echo
  if [ "$ready" = "1" ]; then
    echo "[translation] LibreTranslate: ready on http://127.0.0.1:${LIBRETRANSLATE_PORT}"
    # If .env already exists (normal install.sh flow), wire the bot to the
    # local service. If it does not, install.sh will do this after collecting
    # BOT_TOKEN/OWNER_ID.
    ENV_FILE="$ROOT_DIR/.env"
    if [ -f "$ENV_FILE" ]; then
      if grep -q '^SHOPVPN_LIBRETRANSLATE_URL=' "$ENV_FILE"; then
        sed -i "s|^SHOPVPN_LIBRETRANSLATE_URL=.*|SHOPVPN_LIBRETRANSLATE_URL=http://127.0.0.1:${LIBRETRANSLATE_PORT}|" "$ENV_FILE"
      else
        printf '\nSHOPVPN_LIBRETRANSLATE_URL=http://127.0.0.1:%s\n' "$LIBRETRANSLATE_PORT" >> "$ENV_FILE"
      fi
    fi
  else
    echo "[translation] WARNING: LibreTranslate did not become ready yet." >&2
    echo "[translation] The service will keep retrying; cached/Argos translations remain available." >&2
  fi
else
  echo "[translation] systemd is unavailable; skipping the LibreTranslate service setup." >&2
fi

# Verify that the local engines can import without contacting a public provider.
"$PYTHON_BIN" - <<'PY'
import argostranslate
print("[translation] Argos Translate: ready")
try:
    import libretranslate
    print("[translation] LibreTranslate package: ready")
except Exception as exc:
    print(f"[translation] LibreTranslate package unavailable: {exc}")
PY

echo "[translation] Local translation setup completed."
echo "[translation] Public APIs remain disabled by default."
