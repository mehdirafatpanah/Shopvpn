# -*- coding: utf-8 -*-
"""Portable ShopVPN server-migration assistant.

The full backup intentionally excludes .env and credentials. This helper detects
whether an archive came from another machine and interactively configures only
public endpoint URLs on the destination server.
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
MARKER_PATH = BASE_DIR / ".shopvpn_migration_pending.json"
URL_KEYS = ("MINIAPP_URL", "API_BASE_URL", "DEDICATED_SUB_URL", "ADMIN_PANEL_URL", "WEBHOOK_BASE_URL")


def machine_fingerprint() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
            if raw:
                return hashlib.sha256(raw.encode()).hexdigest()
        except OSError:
            pass
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()


def read_manifest(archive: str) -> dict:
    with zipfile.ZipFile(archive, "r") as zf:
        try:
            raw = zf.read("manifest.json")
        except KeyError:
            return {"format": "legacy", "source_host": "unknown", "environment": {}}
    data = json.loads(raw.decode("utf-8"))
    if data.get("format") not in ("shopvpn-full-backup", None):
        raise ValueError("Unsupported ShopVPN backup manifest")
    return data


def _read_env_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def update_env(values: dict[str, str]) -> None:
    lines = _read_env_lines(ENV_PATH)
    found = set()
    output = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            output.append(f'{key}="{values[key].replace(chr(34), chr(92)+chr(34))}"')
            found.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in found:
            output.append(f'{key}="{value}"')
    tmp = ENV_PATH.with_suffix(".env.migration.tmp")
    tmp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)


def create_pending_marker(manifest: dict) -> bool:
    source_fp = manifest.get("source_machine_fingerprint")
    current_fp = machine_fingerprint()
    changed = bool(source_fp and source_fp != current_fp)
    if not source_fp:
        changed = bool(manifest.get("source_host") and manifest.get("source_host") != socket.gethostname())
    if changed:
        marker = {
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source_host": manifest.get("source_host", "unknown"),
            "destination_host": socket.gethostname(),
            "source_environment": manifest.get("environment", {}),
            "status": "pending_domain_configuration",
        }
        MARKER_PATH.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(MARKER_PATH, 0o600)
    return changed


def interactive_setup(archive: Optional[str] = None, force: bool = False, pending: bool = False) -> int:
    if pending:
        if not MARKER_PATH.is_file():
            print("No pending server migration was detected.")
            return 0
        marker = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
        manifest = {"source_host": marker.get("source_host", "unknown"),
                    "environment": marker.get("source_environment", {})}
        changed = True
    else:
        if not archive:
            raise ValueError("A backup archive is required unless --pending is used")
        manifest = read_manifest(archive)
        changed = create_pending_marker(manifest)
    print("\nShopVPN — Server migration setup")
    print(f"Source server: {manifest.get('source_host', 'unknown')}")
    print(f"Current server: {socket.gethostname()}")
    if not changed and not force:
        print("\nNo machine change was detected. Use --force to reconfigure endpoints anyway.")
        return 0
    if not ENV_PATH.exists():
        print(f"\n.env was not found at {ENV_PATH}. Run the normal ShopVPN installer first.")
        return 2
    previous = manifest.get("environment", {}) or {}
    values = {}
    prompts = {
        "MINIAPP_URL": "New Mini App HTTPS URL (blank keeps current)",
        "API_BASE_URL": "New API HTTPS URL (blank keeps current/auto-derived)",
        "DEDICATED_SUB_URL": "New dedicated-subscription HTTPS URL (blank keeps current)",
        "ADMIN_PANEL_URL": "New web-admin HTTPS URL (blank keeps current)",
        "WEBHOOK_BASE_URL": "New Telegram webhook HTTPS URL (blank keeps current)",
    }
    print("\nEnter the destination server URLs. Leave a field blank to keep its current .env value.")
    for key, prompt in prompts.items():
        old = previous.get(key) or "not stored in backup"
        entered = input(f"{prompt}\n  Previous: {old}\n  New value: ").strip()
        if entered:
            if not (entered.startswith("https://") or entered.startswith("http://")):
                print(f"Invalid URL for {key}; expected http:// or https://")
                return 2
            values[key] = entered.rstrip("/")
    if values:
        update_env(values)
    try:
        marker = json.loads(MARKER_PATH.read_text(encoding="utf-8")) if MARKER_PATH.exists() else {}
        marker.update({"status": "configured", "configured_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                       "updated_keys": sorted(values)})
        MARKER_PATH.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    print("\nEndpoint values saved to .env (permissions restricted).")
    print("Review nginx/SSL and firewall rules for the new domains, then restart ShopVPN services.")
    print("The .env file, bot tokens, API keys and SSH credentials are not copied from the old server.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure ShopVPN after restoring a full backup on a new server")
    parser.add_argument("backup", nargs="?", help="Path to full_backup_*.zip")
    parser.add_argument("--pending", action="store_true", help="Use the pending migration marker created by restore")
    parser.add_argument("--force", action="store_true", help="Run the URL wizard even if the machine appears unchanged")
    args = parser.parse_args()
    try:
        return interactive_setup(args.backup, force=args.force, pending=args.pending)
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"Migration setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
