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

# Verify that the local engine can import Argos without contacting a provider.
"$PYTHON_BIN" - <<'PY'
import argostranslate
print("[translation] Argos Translate: ready")
PY

echo "[translation] Local translation setup completed."
echo "[translation] Public APIs remain disabled by default."
