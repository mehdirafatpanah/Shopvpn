#!/bin/bash
# Fully automatic local translation setup for ShopVPN.
# Installs system/Python prerequisites, Argos Translate and the language models
# required by ShopVPN. No API key is required and public translation APIs are
# never enabled by this script.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/venv}"
TRANSLATION_VENV_DIR="${TRANSLATION_VENV_DIR:-$ROOT_DIR/translation-venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python3}"
LT_PYTHON="${LT_PYTHON:-$TRANSLATION_VENV_DIR/bin/python3}"
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

# Keep LibreTranslate in its own virtualenv so its large dependency tree cannot
# conflict with ShopVPN/aiogram/FastAPI dependencies during future updates.
if [ ! -x "$LT_PYTHON" ]; then
  echo "[translation] Creating isolated LibreTranslate environment..."
  python3 -m venv "$TRANSLATION_VENV_DIR"
fi
"$LT_PYTHON" -m pip install --upgrade pip setuptools wheel >/dev/null
"$LT_PYTHON" -m pip install -q --upgrade 'libretranslate>=1.9.0'

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

# The local engine is the source of truth. Public providers are disabled by
# default so Google/MyMemory/OpenRouter rate limits can never break the UI.
ENV_FILE="$ROOT_DIR/.env"
touch "$ENV_FILE"
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}
set_env SHOPVPN_TRANSLATION_ALLOW_PUBLIC_APIS 0
set_env SHOPVPN_TRANSLATION_PROVIDERS 'argos,libretranslate'
set_env SHOPVPN_LIBRETRANSLATE_URL 'http://127.0.0.1:5000'

# Run LibreTranslate locally as a second free/offline-capable fallback. Argos
# remains first and therefore avoids HTTP overhead for normal short UI strings.
if command -v systemctl >/dev/null 2>&1; then
  SERVICE_FILE=/etc/systemd/system/shopvpn-libretranslate.service
  as_root bash -c "cat > '$SERVICE_FILE' <<EOF
[Unit]
Description=ShopVPN Local LibreTranslate
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
ExecStart=$LT_PYTHON -m libretranslate --host 127.0.0.1 --port 5000 --load-only en,fa,tr,ar,ru,de,fr,es,it,pt,zh,ja,ko,nl,pl,uk --update-models --disable-web-ui
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"
  as_root systemctl daemon-reload
  as_root systemctl enable --now shopvpn-libretranslate.service || true
fi

"$PYTHON_BIN" - <<'PY'
import argostranslate
print("[translation] Argos Translate: ready")
PY

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 5 http://127.0.0.1:5000/health >/dev/null 2>&1; then
    echo "[translation] Local LibreTranslate: ready"
  else
    echo "[translation] Local LibreTranslate is not reachable; Argos remains the primary provider."
  fi
fi

echo "[translation] Local translation setup completed."
echo "[translation] Public translation APIs are disabled by default."
