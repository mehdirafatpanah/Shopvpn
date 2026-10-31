#!/usr/bin/env bash
set -Eeuo pipefail

# Install the ShopVPN node agent on a Debian/Ubuntu Linux node.
# Usage (from the project root, as root): bash deploy/install-shopvpn-ssh-agent.sh [ssh|openvpn|wireguard|comma-separated mix]
# Optional environment: OVPN_PORT (default 1194), OVPN_PROTO (udp|tcp, default udp), WG_PORT (default 51820), SHOPVPN_ENABLE_NFT=1

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install-shopvpn-ssh-agent.sh" >&2
  exit 1
fi

WANT_SSH=0
WANT_OVPN=0
WANT_WG=0
IFS=',' read -r -a REQUESTED <<< "${1:-${SHOPVPN_INSTALL_PROTOCOLS:-ssh}}"
for item in "${REQUESTED[@]}"; do
  case "${item}" in
    ssh) WANT_SSH=1 ;;
    openvpn) WANT_OVPN=1 ;;
    wireguard) WANT_WG=1 ;;
    *) echo "Unknown protocol: ${item}" >&2; exit 1 ;;
  esac
done
if [[ "${WANT_SSH}" -eq 0 && "${WANT_OVPN}" -eq 0 && "${WANT_WG}" -eq 0 ]]; then
  echo "Select at least one protocol: ssh, openvpn, wireguard" >&2
  exit 1
fi
PROTOCOLS=""
[[ "${WANT_SSH}" -eq 1 ]] && PROTOCOLS="ssh"
[[ "${WANT_OVPN}" -eq 1 ]] && PROTOCOLS="${PROTOCOLS:+${PROTOCOLS},}openvpn"
[[ "${WANT_WG}" -eq 1 ]] && PROTOCOLS="${PROTOCOLS:+${PROTOCOLS},}wireguard"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_SOURCE="${PROJECT_ROOT}/ssh_node_agent.py"
SERVICE_SOURCE="${PROJECT_ROOT}/deploy/shopvpn-ssh-agent.service"
SSHD_TEMPLATE_SOURCE="${PROJECT_ROOT}/deploy/shopvpn-sshd@.service"
OVPN_DISCONNECT_SOURCE="${PROJECT_ROOT}/deploy/shopvpn-ovpn-disconnect.sh"
OVPN_NAT_SOURCE="${PROJECT_ROOT}/deploy/shopvpn-ovpn-nat.service"
OVPN_AUTH_SOURCE="${PROJECT_ROOT}/deploy/shopvpn-ovpn-auth.py"
WG_NAT_SOURCE="${PROJECT_ROOT}/deploy/shopvpn-wg-nat.service"
ENV_FILE=/etc/shopvpn-ssh-agent.env

required=("${AGENT_SOURCE}" "${SERVICE_SOURCE}")
[[ "${WANT_SSH}" -eq 1 ]] && required+=("${SSHD_TEMPLATE_SOURCE}")
[[ "${WANT_OVPN}" -eq 1 ]] && required+=("${OVPN_DISCONNECT_SOURCE}" "${OVPN_NAT_SOURCE}" "${OVPN_AUTH_SOURCE}")
[[ "${WANT_WG}" -eq 1 ]] && required+=("${WG_NAT_SOURCE}")
for file in "${required[@]}"; do
  if [[ ! -f "${file}" ]]; then
    echo "Run this script from the extracted ShopVPN project; missing ${file}" >&2
    exit 1
  fi
done

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This helper supports Debian/Ubuntu (apt-get) only. Install Python 3 and aiohttp manually." >&2
  exit 1
fi

packages=(python3 python3-aiohttp nftables openssl)
[[ "${WANT_SSH}" -eq 1 ]] && packages+=(openssh-server)
[[ "${WANT_OVPN}" -eq 1 ]] && packages+=(openvpn easy-rsa)
[[ "${WANT_WG}" -eq 1 ]] && packages+=(wireguard wireguard-tools)
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y "${packages[@]}"

install -d -o root -g root -m 0755 /opt/shopvpn /var/lib/shopvpn-ssh-agent /etc/shopvpn
install -o root -g root -m 0755 "${AGENT_SOURCE}" /opt/shopvpn/ssh_node_agent.py

if [[ ! -f "${ENV_FILE}" ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  umask 077
  cat > "${ENV_FILE}" <<EOF
SHOPVPN_AGENT_TOKEN=${TOKEN}
SHOPVPN_AGENT_HOST=127.0.0.1
SHOPVPN_AGENT_PORT=8765
SHOPVPN_AGENT_DB=/var/lib/shopvpn-ssh-agent/agent.db
SHOPVPN_NFT_ACCOUNTING=0
EOF
  chmod 0600 "${ENV_FILE}"
  echo
  echo "A new Agent token was created in ${ENV_FILE}."
  echo "Copy SHOPVPN_AGENT_TOKEN securely to the ShopVPN main server's environment as the matching secret."
else
  chmod 0600 "${ENV_FILE}"
  echo "Existing ${ENV_FILE} preserved."
fi

set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    echo "${key}=${value}" >> "${ENV_FILE}"
  fi
}

set_env SHOPVPN_PROTOCOLS "${PROTOCOLS}"
if [[ "${WANT_SSH}" -eq 1 && "${SHOPVPN_ENABLE_NFT:-0}" == "1" ]]; then
  set_env SHOPVPN_NFT_ACCOUNTING 1
fi

if [[ "${WANT_SSH}" -eq 1 ]]; then
  install -d -o root -g root -m 0755 /etc/shopvpn/sshd
  ssh-keygen -A
  install -o root -g root -m 0644 "${SSHD_TEMPLATE_SOURCE}" /etc/systemd/system/shopvpn-sshd@.service
  groupadd --system shopvpnssh 2>/dev/null || true

  SSHD_CONFIG=/etc/ssh/sshd_config
  SSHD_BACKUP="${SSHD_CONFIG}.shopvpn-backup.$(date +%Y%m%d%H%M%S)"
  if ! grep -Fq '# BEGIN SHOPVPN SSH ACCOUNT RESTRICTIONS' "${SSHD_CONFIG}"; then
    cp -a "${SSHD_CONFIG}" "${SSHD_BACKUP}"
    cat >> "${SSHD_CONFIG}" <<'EOF'

# BEGIN SHOPVPN SSH ACCOUNT RESTRICTIONS
Match Group shopvpnssh
    AllowTcpForwarding no
    AllowStreamLocalForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    MaxSessions 0
    ForceCommand /usr/sbin/nologin
# END SHOPVPN SSH ACCOUNT RESTRICTIONS
EOF
    if ! /usr/sbin/sshd -t -f "${SSHD_CONFIG}"; then
      cp -a "${SSHD_BACKUP}" "${SSHD_CONFIG}"
      echo "OpenSSH configuration validation failed; restored the previous config." >&2
      exit 1
    fi
  fi
fi

if [[ "${WANT_OVPN}" -eq 1 ]]; then
  OVPN_BASE=/etc/openvpn/server
  OVPN_DIR="${OVPN_BASE}/shopvpn"
  PKI=/etc/shopvpn/ovpn-pki
  OVPN_CONF="${OVPN_BASE}/shopvpn.conf"

  install -d -o root -g root -m 0755 "${OVPN_BASE}" "${OVPN_DIR}" "${OVPN_DIR}/ccd"
  install -d -o root -g root -m 1733 /var/lib/shopvpn-ovpn-events
  install -o root -g root -m 0755 "${OVPN_DISCONNECT_SOURCE}" /opt/shopvpn/ovpn-disconnect.sh
  install -o root -g root -m 0755 "${OVPN_AUTH_SOURCE}" /opt/shopvpn/ovpn-auth.py
  install -d -o root -g nogroup -m 0750 "${OVPN_DIR}" 2>/dev/null || install -d -o root -g nobody -m 0750 "${OVPN_DIR}"
  touch "${OVPN_DIR}/auth-users"
  chown root:nogroup "${OVPN_DIR}/auth-users" 2>/dev/null || chown root:nobody "${OVPN_DIR}/auth-users"
  chmod 0640 "${OVPN_DIR}/auth-users"
  install -o root -g root -m 0644 "${OVPN_NAT_SOURCE}" /etc/systemd/system/shopvpn-ovpn-nat.service

  if [[ ! -f "${OVPN_CONF}" ]]; then
    OVPN_PORT="${OVPN_PORT:-1194}"
    OVPN_PROTO="${OVPN_PROTO:-udp}"
    if ! [[ "${OVPN_PORT}" =~ ^[0-9]+$ ]] || (( OVPN_PORT < 1 || OVPN_PORT > 65535 )); then
      echo "Invalid OVPN_PORT" >&2; exit 1
    fi
    if [[ "${OVPN_PROTO}" != "udp" && "${OVPN_PROTO}" != "tcp" ]]; then
      echo "Invalid OVPN_PROTO" >&2; exit 1
    fi

    EASYRSA_BIN="$(command -v easyrsa || true)"
    [[ -z "${EASYRSA_BIN}" ]] && EASYRSA_BIN=/usr/share/easy-rsa/easyrsa
    export EASYRSA_PKI="${PKI}" EASYRSA_BATCH=1 EASYRSA_ALGO=ec EASYRSA_CURVE=prime256v1
    export EASYRSA_CA_EXPIRE=3650 EASYRSA_CERT_EXPIRE=3650 EASYRSA_CRL_DAYS=3650 EASYRSA_REQ_CN=shopvpn-ca
    if [[ ! -f "${PKI}/ca.crt" ]]; then
      "${EASYRSA_BIN}" init-pki
      "${EASYRSA_BIN}" build-ca nopass
      "${EASYRSA_BIN}" build-server-full server nopass
      "${EASYRSA_BIN}" gen-crl
    fi
    chmod 0700 "${PKI}"

    install -m 0644 "${PKI}/ca.crt" "${OVPN_DIR}/ca.crt"
    install -m 0644 "${PKI}/issued/server.crt" "${OVPN_DIR}/server.crt"
    install -m 0600 "${PKI}/private/server.key" "${OVPN_DIR}/server.key"
    install -m 0644 "${PKI}/crl.pem" "${OVPN_DIR}/crl.pem"
    if [[ ! -f "${OVPN_DIR}/ta.key" ]]; then
      openvpn --genkey secret "${OVPN_DIR}/ta.key" 2>/dev/null || openvpn --genkey --secret "${OVPN_DIR}/ta.key"
      chmod 0600 "${OVPN_DIR}/ta.key"
    fi

    NOGROUP="nogroup"
    getent group nogroup >/dev/null 2>&1 || NOGROUP="nobody"
    OVPN_VERSION="$(openvpn --version | awk 'NR==1{print $2}')"
    if [[ "$(printf '%s\n2.5.0\n' "${OVPN_VERSION}" | sort -V | head -n1)" == "2.5.0" ]]; then
      CIPHER_LINE="data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305"
    else
      CIPHER_LINE="ncp-ciphers AES-256-GCM:AES-128-GCM"
    fi
    {
      echo "port ${OVPN_PORT}"
      echo "proto ${OVPN_PROTO}"
      echo "dev tun"
      echo "topology subnet"
      echo "server 10.89.0.0 255.255.0.0"
      echo "ca ${OVPN_DIR}/ca.crt"
      echo "cert ${OVPN_DIR}/server.crt"
      echo "key ${OVPN_DIR}/server.key"
      echo "dh none"
      echo "ecdh-curve prime256v1"
      echo "tls-crypt ${OVPN_DIR}/ta.key"
      echo "crl-verify ${OVPN_DIR}/crl.pem"
      echo "client-config-dir ${OVPN_DIR}/ccd"
      echo "auth SHA256"
      echo "auth-user-pass-verify /opt/shopvpn/ovpn-auth.py via-file"
      echo "username-as-common-name"
      echo "cipher AES-256-GCM"
      echo "${CIPHER_LINE}"
      echo "tls-version-min 1.2"
      echo 'push "redirect-gateway def1 bypass-dhcp"'
      echo 'push "dhcp-option DNS 1.1.1.1"'
      echo 'push "dhcp-option DNS 8.8.8.8"'
      echo "keepalive 10 60"
      echo "persist-key"
      echo "persist-tun"
      echo "user nobody"
      echo "group ${NOGROUP}"
      echo "script-security 2"
      echo "client-disconnect /opt/shopvpn/ovpn-disconnect.sh"
      echo "management /run/openvpn-server/shopvpn.sock unix"
      [[ "${OVPN_PROTO}" == "udp" ]] && echo "explicit-exit-notify 1"
      echo "verb 3"
    } > "${OVPN_CONF}"
    chmod 0644 "${OVPN_CONF}"

    set_env SHOPVPN_OVPN_PORT "${OVPN_PORT}"
    set_env SHOPVPN_OVPN_PROTO "${OVPN_PROTO}"

    cat > /etc/shopvpn/ovpn-nat.nft <<'EOF'
table ip shopvpn_nat
delete table ip shopvpn_nat
table ip shopvpn_nat {
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr 10.89.0.0/16 masquerade
  }
}
EOF
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-shopvpn-ovpn.conf
    sysctl -q -p /etc/sysctl.d/99-shopvpn-ovpn.conf || true
  else
    echo "Existing OpenVPN server config found; enabling ShopVPN username/password authentication."
    install -d -o root -g root -m 0755 "${OVPN_DIR}" "${OVPN_DIR}/ccd"
    install -d -o root -g root -m 0755 /opt/shopvpn
    install -o root -g root -m 0755 "${OVPN_AUTH_SOURCE}" /opt/shopvpn/ovpn-auth.py
    touch "${OVPN_DIR}/auth-users"
    chmod 0640 "${OVPN_DIR}/auth-users"
    chown root:nogroup "${OVPN_DIR}/auth-users" 2>/dev/null || chown root:nobody "${OVPN_DIR}/auth-users"
    if ! grep -q '^auth-user-pass-verify /opt/shopvpn/ovpn-auth.py via-file$' "${OVPN_CONF}"; then
      printf '\nauth-user-pass-verify /opt/shopvpn/ovpn-auth.py via-file\nusername-as-common-name\n' >> "${OVPN_CONF}"
    fi
    if ! grep -q '^script-security 2$' "${OVPN_CONF}"; then
      printf 'script-security 2\n' >> "${OVPN_CONF}"
    fi
  fi
fi

if [[ "${WANT_WG}" -eq 1 ]]; then
  WG_IFACE=wg-shopvpn
  WG_CONF="/etc/wireguard/${WG_IFACE}.conf"

  install -d -o root -g root -m 0700 /etc/wireguard
  install -o root -g root -m 0644 "${WG_NAT_SOURCE}" /etc/systemd/system/shopvpn-wg-nat.service

  if [[ ! -f "${WG_CONF}" ]]; then
    WG_PORT="${WG_PORT:-51820}"
    if ! [[ "${WG_PORT}" =~ ^[0-9]+$ ]] || (( WG_PORT < 1 || WG_PORT > 65535 )); then
      echo "Invalid WG_PORT" >&2; exit 1
    fi

    WG_PRIVATE="$(wg genkey)"
    (
      umask 077
      cat > "${WG_CONF}" <<WGEOF
[Interface]
Address = 10.88.0.1/16
ListenPort = ${WG_PORT}
PrivateKey = ${WG_PRIVATE}
WGEOF
    )
    chmod 0600 "${WG_CONF}"

    set_env SHOPVPN_WG_PORT "${WG_PORT}"
    set_env SHOPVPN_WG_IFACE "${WG_IFACE}"

    cat > /etc/shopvpn/wg-nat.nft <<'NATEOF'
table ip shopvpn_wg_nat
delete table ip shopvpn_wg_nat
table ip shopvpn_wg_nat {
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr 10.88.0.0/16 masquerade
  }
}
NATEOF
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-shopvpn-wg.conf
    sysctl -q -p /etc/sysctl.d/99-shopvpn-wg.conf || true
  else
    echo "Existing WireGuard server config preserved."
  fi
fi

install -o root -g root -m 0644 "${SERVICE_SOURCE}" /etc/systemd/system/shopvpn-ssh-agent.service
systemctl daemon-reload
if [[ "${WANT_SSH}" -eq 1 ]]; then
  if systemctl is-active --quiet ssh; then
    systemctl reload ssh
  elif systemctl is-active --quiet sshd; then
    systemctl reload sshd
  fi
fi
if [[ "${WANT_OVPN}" -eq 1 ]]; then
  systemctl enable --now shopvpn-ovpn-nat
  systemctl enable openvpn-server@shopvpn
  systemctl restart openvpn-server@shopvpn
fi
if [[ "${WANT_WG}" -eq 1 ]]; then
  systemctl enable --now shopvpn-wg-nat
  systemctl enable "wg-quick@wg-shopvpn"
  systemctl restart "wg-quick@wg-shopvpn"
fi
systemctl enable --now shopvpn-ssh-agent

systemctl --no-pager --full status shopvpn-ssh-agent || true
echo
echo "Agent installed (protocols: ${PROTOCOLS}) and bound per ${ENV_FILE}; default is 127.0.0.1:8765."
echo "Do not expose the agent port directly to the public Internet. Use a private network or an IP-restricted TLS reverse proxy."
if [[ "${WANT_SSH}" -eq 1 ]]; then
  echo "SSH accounts listen on unique TCP ports in 20000-39999; open this range in your firewall/security group."
  echo "Per-account nftables accounting stays OFF until SHOPVPN_NFT_ACCOUNTING=1 is set in ${ENV_FILE} and the Agent is restarted."
fi
if [[ "${WANT_OVPN}" -eq 1 ]]; then
  echo "OpenVPN listens on the port/protocol configured in ${ENV_FILE}; open it in your firewall/security group."
fi
if [[ "${WANT_WG}" -eq 1 ]]; then
  echo "WireGuard listens on the UDP port configured in ${ENV_FILE} (SHOPVPN_WG_PORT); open it in your firewall/security group."
fi
