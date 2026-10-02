#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#   SVM+ V11.3 • ANKITCODER • PRODUCTION INSTALLER / UPGRADER
#
#   sudo bash install.sh                  install or upgrade (keeps your .env + DB)
#   sudo bash install.sh --configure      only run the configuration wizard
#   sudo bash install.sh --local-bot FILE use this bot.py instead of the GitHub one
#   sudo bash install.sh --non-interactive   no questions (use SVM_ENV_<KEY>=value)
#   sudo bash install.sh --rollback [SNAPSHOT]   restore bot.py from a backup
#   sudo bash install.sh --no-start       deploy but do not (re)start the service
#
#   Non-interactive example:
#     SVM_ENV_DISCORD_TOKEN=xxx SVM_ENV_MAIN_ADMIN_ID=123 \
#     SVM_ENV_PAYMENT_GATEWAYS=razorpay,upi sudo -E bash install.sh --non-interactive
# ══════════════════════════════════════════════════════════════════════════════
set -Eeuo pipefail

REPO="${SVM_REPO:-https://github.com/AnkitKing7/Svm-v11.2-bot.git}"
BRANCH="${SVM_BRANCH:-main}"
APP_DIR="${SVM_DIR:-/opt/svm}"
SERVICE="${SVM_SERVICE:-svm}"
ENV_FILE="${APP_DIR}/.env"
BACKUP_DIR="${APP_DIR}/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOCK_FILE="/var/lock/svm-plus-ankitcoder.lock"
KEEP_SNAPSHOTS="${SVM_KEEP_SNAPSHOTS:-10}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="install"; INTERACTIVE=1; NO_START=0; LOCAL_BOT="${SVM_LOCAL_BOT:-}"; ROLLBACK_TARGET=""
[[ -t 0 ]] || INTERACTIVE=0

R='\033[0m'; B='\033[1m'; C='\033[36m'; G='\033[32m'; Y='\033[33m'; E='\033[31m'
info(){ printf "${C}➜${R} %s\n" "$*"; }
ok(){ printf "${G}✓${R} %s\n" "$*"; }
warn(){ printf "${Y}!${R} %s\n" "$*"; }
die(){ printf "${E}✗${R} %s\n" "$*" >&2; exit 1; }
section(){ printf "\n${B}${C}━━━ %s ━━━${R}\n" "$*"; }

banner() {
cat <<'EOF'

  ╔════════════════════════════════════════════════════════════╗
  ║   S V M +   V 1 1 . 3  —  A N K I T C O D E R              ║
  ║   VPS • IP POOL • PORT FORWARDING • PAYMENT GATEWAYS       ║
  ╚════════════════════════════════════════════════════════════╝

EOF
}

# ─────────────────────────── .env helpers ───────────────────────────────────
get_env() {   # get_env KEY -> current value (quotes stripped)
    local key="$1" line
    [[ -f "$ENV_FILE" ]] || return 0
    line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n1 || true)"
    line="${line#*=}"
    line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
    printf '%s' "$line"
}

set_env() {   # set_env KEY VALUE  (replace or append; single-quoted for dotenv + systemd)
    local key="$1" val="$2"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Invalid env key: $key"
    [[ "$val" != *$'\n'* && "$val" != *"'"* ]] || die "Value for $key may not contain a newline or a single quote"
    ENV_KEY="$key" ENV_VAL="$val" ENV_PATH="$ENV_FILE" python3 - <<'PY'
import os, re
key, val, path = os.environ["ENV_KEY"], os.environ["ENV_VAL"], os.environ["ENV_PATH"]
lines = open(path).read().splitlines() if os.path.exists(path) else []
new, done = f"{key}='{val}'", False
for i, line in enumerate(lines):
    if re.match(rf"^\s*(export\s+)?{re.escape(key)}=", line):
        lines[i], done = new, True
if not done:
    lines.append(new)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as fh:
    fh.write("\n".join(lines) + "\n")
PY
}

ensure_env() {   # ensure_env KEY DEFAULT -> only if missing
    local key="$1" val="$2"
    grep -qE "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null || set_env "$key" "$val"
}

apply_env_overrides() {   # SVM_ENV_<KEY>=value  ->  KEY in .env
    local var key
    while IFS='=' read -r var _; do
        [[ "$var" == SVM_ENV_* ]] || continue
        key="${var#SVM_ENV_}"
        set_env "$key" "${!var}"
    done < <(env)
}

ask() {   # ask KEY "Prompt" [default] [secret]
    local key="$1" prompt="$2" def="${3:-}" secret="${4:-}" cur reply shown
    cur="$(get_env "$key")"; [[ -n "$cur" ]] && def="$cur"
    (( INTERACTIVE )) || return 0
    if [[ "$secret" == "secret" ]]; then
        shown=""; [[ -n "$cur" ]] && shown=" [keep current]"
        read -r -s -p "  ${prompt}${shown}: " reply; echo
    else
        shown=""; [[ -n "$def" ]] && shown=" [${def}]"
        read -r -p "  ${prompt}${shown}: " reply
    fi
    reply="${reply:-$def}"
    [[ -n "$reply" ]] && set_env "$key" "$reply"
    return 0
}

yesno() {   # yesno "Question" default(y/n) -> 0 yes / 1 no
    local q="$1" def="${2:-n}" reply
    (( INTERACTIVE )) || { [[ "$def" == y ]]; return; }
    read -r -p "  ${q} [$([[ $def == y ]] && echo Y/n || echo y/N)]: " reply
    reply="${reply:-$def}"; [[ "${reply,,}" == y* ]]
}

detect_public_ip() {
    curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null \
        || curl -4 -fsS --max-time 5 https://ifconfig.me 2>/dev/null \
        || ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -n1 \
        || true
}

default_iface() { ip -4 route show default 2>/dev/null | awk '{print $5}' | head -n1; }

# ─────────────────────── defaults merged into .env ──────────────────────────
write_default_env() {
    ensure_env PAYMENT_GATEWAYS "razorpay,upi"
    ensure_env DEFAULT_GATEWAY ""
    ensure_env RAZORPAY_KEY_ID ""
    ensure_env RAZORPAY_KEY_SECRET ""
    ensure_env RAZORPAY_WEBHOOK_SECRET ""
    ensure_env RAZORPAY_ACCEPT_AUTHORIZED "false"
    ensure_env STRIPE_SECRET_KEY ""
    ensure_env STRIPE_WEBHOOK_SECRET ""
    ensure_env STRIPE_CURRENCY "inr"
    ensure_env STRIPE_AMOUNT_RATE "1.0"
    ensure_env UPI_ENABLED "false"
    ensure_env UPI_ID ""
    ensure_env UPI_NAME "AnkitCoder"
    ensure_env UPI_QR_URL ""
    ensure_env PAYMENT_WEBHOOK_HOST "127.0.0.1"
    ensure_env PAYMENT_WEBHOOK_PORT "8787"
    ensure_env SVM_PUBLIC_URL ""
    ensure_env PAYMENT_SUCCESS_URL ""
    ensure_env PAYMENT_ADMIN_CHANNEL_ID "0"
    ensure_env ORDER_TTL_MINUTES "60"
    ensure_env UPI_ORDER_TTL_MINUTES "1440"
    ensure_env MAX_PENDING_ORDERS "3"
    ensure_env RENEW_DAYS "30"
    ensure_env PLAN_PERIOD_DAYS "30"
    ensure_env PLAN_STARTER_PRICE "0"
    ensure_env PLAN_BASIC_PRICE "0"
    ensure_env PLAN_STANDARD_PRICE "0"
    ensure_env PLAN_PRO_PRICE "0"
    ensure_env PORT_RANGE_START "20000"
    ensure_env PORT_RANGE_END "50000"
    ensure_env PORT_RESERVED ""
    ensure_env PORT_MAX_PER_VPS "20"
    ensure_env PORT_ALLOW_CUSTOM "false"
    ensure_env IPAM_BIND_MODE "record"
    ensure_env IPAM_AUTO_ASSIGN "false"
    ensure_env IPAM_HOST_IFACE ""
    ensure_env IPAM_POOLS ""
    ensure_env IPAM_POOL_MAX_ADDRS "4096"
    ensure_env DEFAULT_V11_2V_OS "ubuntu:22.04"
}

# ────────────────────────── configuration wizard ────────────────────────────
configure_env() {
    section "CONFIGURATION WIZARD"
    (( INTERACTIVE )) && info "Press Enter to keep the value shown in [brackets]. Secrets are hidden while typing." \
                      || info "Non-interactive: using SVM_ENV_* variables and existing .env values."

    if (( INTERACTIVE )); then
        echo; info "1/5  Discord"
        ask DISCORD_TOKEN   "Discord bot token" "" secret
        ask MAIN_ADMIN_ID   "Main admin Discord user ID"
        local ip; ip="$(get_env YOUR_SERVER_IP)"; [[ -z "$ip" || "$ip" == "127.0.0.1" ]] && ip="$(detect_public_ip)"
        ask YOUR_SERVER_IP  "Public server IP (shown to users for SSH/ports)" "${ip}"

        echo; info "2/5  Public webhook URL (needed for automatic Razorpay / Stripe verification)"
        ask SVM_PUBLIC_URL  "Public HTTPS URL, e.g. https://pay.example.com (blank = no auto-payments)"
        local url; url="$(get_env SVM_PUBLIC_URL)"
        if [[ "$url" == https://* ]]; then
            if yesno "Install Caddy as an HTTPS reverse proxy for ${url}?" y; then SETUP_CADDY=1; fi
        fi

        echo; info "3/5  Payment gateways"
        local gws=()
        if yesno "Enable Razorpay (cards/UPI/netbanking, auto verification)?" y; then
            gws+=(razorpay)
            ask RAZORPAY_KEY_ID "  Razorpay Key ID"
            ask RAZORPAY_KEY_SECRET "  Razorpay Key Secret" "" secret
            if [[ -z "$(get_env RAZORPAY_WEBHOOK_SECRET)" ]]; then set_env RAZORPAY_WEBHOOK_SECRET "$(openssl rand -hex 24)"; fi
            info "  Razorpay dashboard → Webhooks: URL  ${url:-https://YOUR-DOMAIN}/razorpay/webhook"
            info "  events: payment_link.paid, payment.captured   secret: (run 'svm env RAZORPAY_WEBHOOK_SECRET' to view)"
        fi
        if yesno "Enable Stripe Checkout (international cards)?" n; then
            gws+=(stripe)
            ask STRIPE_SECRET_KEY "  Stripe secret key (sk_live_/sk_test_)" "" secret
            ask STRIPE_WEBHOOK_SECRET "  Stripe webhook signing secret (whsec_)" "" secret
            ask STRIPE_CURRENCY "  Stripe currency code" "inr"
            ask STRIPE_AMOUNT_RATE "  Conversion rate: INR paise → Stripe minor units (1.0 for INR)" "1.0"
            info "  Stripe dashboard → Webhooks: ${url:-https://YOUR-DOMAIN}/stripe/webhook  event: checkout.session.completed"
        fi
        if yesno "Enable manual UPI (admin approves each payment)?" y; then
            gws+=(upi); set_env UPI_ENABLED true
            ask UPI_ID "  UPI ID (VPA)"
            ask UPI_NAME "  Payee name" "AnkitCoder"
            ask UPI_QR_URL "  QR image URL (optional)"
        else
            set_env UPI_ENABLED false
        fi
        if ((${#gws[@]})); then set_env PAYMENT_GATEWAYS "$(IFS=,; echo "${gws[*]}")"; ask DEFAULT_GATEWAY "  Default gateway for !buy" "${gws[0]}"; fi
        ask PLAN_STARTER_PRICE  "  Price ₹ Starter (1 vCPU/2 GB/20 GB)" "0"
        ask PLAN_BASIC_PRICE    "  Price ₹ Basic   (2 vCPU/4 GB/40 GB)" "0"
        ask PLAN_STANDARD_PRICE "  Price ₹ Standard(4 vCPU/8 GB/80 GB)" "0"
        ask PLAN_PRO_PRICE      "  Price ₹ Pro     (8 vCPU/16 GB/160 GB)" "0"
        ask PAYMENT_ADMIN_CHANNEL_ID "  Discord channel ID for payment alerts (0 = DM main admin)" "0"

        echo; info "4/5  IP pool"
        ask IPAM_BIND_MODE "  Bind mode: record (bookkeeping) | bridged (LXD static IP) | nat (host iptables)" "record"
        if [[ "$(get_env IPAM_BIND_MODE)" == "nat" ]]; then ask IPAM_HOST_IFACE "  Host interface that carries the public IPs" "$(default_iface)"; fi
        if yesno "Auto-assign a pool IP to every newly purchased VPS?" n; then set_env IPAM_AUTO_ASSIGN true; else set_env IPAM_AUTO_ASSIGN false; fi
        ask IPAM_POOLS "  Pools: name|cidr|gateway|node_id;name2|cidr2  (blank = add later with !ipool add)"

        echo; info "5/5  Port forwarding"
        ask PORT_RANGE_START "  Public port range start" "20000"
        ask PORT_RANGE_END   "  Public port range end"   "50000"
        ask PORT_RESERVED    "  Reserved ports (comma separated)" ""
        ask PORT_MAX_PER_VPS "  Max forwards per VPS" "20"
        if yesno "Let users pick their own public port?" n; then set_env PORT_ALLOW_CUSTOM true; else set_env PORT_ALLOW_CUSTOM false; fi
    fi

    if [[ "$(get_env SVM_PUBLIC_URL)" == https://* && "${SETUP_CADDY:-0}" == "1" ]]; then
        set_env PAYMENT_WEBHOOK_HOST "127.0.0.1"
    elif [[ -n "$(get_env SVM_PUBLIC_URL)" && "${SETUP_CADDY:-0}" != "1" ]]; then
        warn "Webhook server stays on ${APP_DIR}/.env host; put your own HTTPS proxy in front of port $(get_env PAYMENT_WEBHOOK_PORT)."
    fi
    validate_env
}

validate_env() {
    local n lo hi tok
    lo="$(get_env PORT_RANGE_START)"; hi="$(get_env PORT_RANGE_END)"
    for n in "$lo" "$hi"; do [[ "$n" =~ ^[0-9]+$ ]] || die "Port range values must be numbers"; done
    (( lo >= 1024 && hi <= 65535 && lo < hi )) || die "Port range must satisfy 1024 <= start < end <= 65535"
    case "$(get_env IPAM_BIND_MODE)" in record|bridged|nat) ;; *) die "IPAM_BIND_MODE must be record, bridged or nat";; esac
    tok="$(get_env DISCORD_TOKEN)"
    [[ -z "$tok" || "$tok" == "your_discord_bot_token_here" ]] && warn "DISCORD_TOKEN is not set yet — the bot cannot log in until you add it."
    if [[ "$(get_env PAYMENT_GATEWAYS)" == *razorpay* ]]; then
        [[ -n "$(get_env RAZORPAY_KEY_ID)" && -n "$(get_env RAZORPAY_KEY_SECRET)" ]] || warn "Razorpay is enabled but key id/secret are missing (gateway stays hidden until set)."
    fi
    ok "Configuration validated"
}

# ─────────────────────────── system pieces ──────────────────────────────────
install_packages() {
    section "SYSTEM DEPENDENCIES"
    export DEBIAN_FRONTEND=noninteractive
    local log="/tmp/svm-install-pkgs-${STAMP}.log"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y >"$log" 2>&1 || warn "apt-get update reported problems (see $log)"
        apt-get install -y python3 python3-venv python3-pip python3-dev curl ca-certificates git sqlite3 \
            openssh-client iproute2 iptables procps util-linux rsync unzip jq openssl >>"$log" 2>&1 \
            || die "Core packages failed to install (see $log)"
        local pkg                                    # optional virtualization tools: one by one so a missing one cannot block the rest
        for pkg in dnsutils lxc lxc-utils libvirt-clients qemu-utils qemu-system-x86 qemu-kvm; do
            apt-get install -y "$pkg" >>"$log" 2>&1 || warn "Optional package unavailable: $pkg"
        done
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip python3-devel curl ca-certificates git sqlite openssh-clients \
            iproute iptables procps-ng rsync unzip jq openssl qemu-img libvirt-client >"$log" 2>&1 || warn "Some packages unavailable (see $log)"
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-pip curl ca-certificates git sqlite openssh-clients iproute iptables \
            procps-ng rsync unzip jq openssl qemu-img libvirt-client >"$log" 2>&1 || warn "Some packages unavailable (see $log)"
    else
        warn "No supported package manager detected."
    fi
    for c in python3 git curl openssl; do command -v "$c" >/dev/null 2>&1 || die "$c is required"; done
    python3 -c 'import sys; assert sys.version_info >= (3,9), sys.version' || die "Python 3.9+ is required"
    ok "System dependencies ready"
}

backup_snapshot() {
    section "SAFE BACKUP"
    mkdir -p "$APP_DIR" "$BACKUP_DIR" "$APP_DIR/data" "$APP_DIR/logs" "$APP_DIR/db_backups"
    chmod 700 "$APP_DIR" "$APP_DIR/data" "$BACKUP_DIR"
    SNAP="${BACKUP_DIR}/upgrade-${STAMP}"; mkdir -p "$SNAP"
    local f
    for f in bot.py webssh.html requirements.txt .env; do
        if [[ -f "$APP_DIR/$f" ]]; then cp -a "$APP_DIR/$f" "$SNAP/$f"; fi
    done
    if [[ -f "$APP_DIR/vps.db" ]]; then      # consistent copy even while the bot is running
        sqlite3 "$APP_DIR/vps.db" ".backup '$SNAP/vps.db'" 2>/dev/null || cp -a "$APP_DIR/vps.db" "$SNAP/vps.db"
    fi
    chmod 700 "$SNAP"
    { ls -1dt "$BACKUP_DIR"/upgrade-* 2>/dev/null || true; } | tail -n +"$((KEEP_SNAPSHOTS + 1))" | xargs -r rm -rf
    ok "Backup created: $SNAP (keeping last $KEEP_SNAPSHOTS)"
}

fetch_sources() {
    section "SOURCES"
    TMP_DIR="$(mktemp -d)"; trap 'rm -rf "${TMP_DIR:-}"' EXIT
    local need_clone=0
    [[ -z "$LOCAL_BOT" && -f "$SCRIPT_DIR/bot.py" ]] && LOCAL_BOT="$SCRIPT_DIR/bot.py"
    [[ -z "$LOCAL_BOT" ]] && need_clone=1
    [[ -f "$SCRIPT_DIR/webssh.html" ]] || need_clone=1
    [[ -f "$SCRIPT_DIR/requirements.txt" ]] || need_clone=1
    if (( need_clone )); then
        if git clone --depth 1 --branch "$BRANCH" "$REPO" "$TMP_DIR/repo" >/dev/null 2>&1; then ok "Cloned $REPO"
        else
            [[ -n "$LOCAL_BOT" && -f "$APP_DIR/webssh.html" && -f "$APP_DIR/requirements.txt" ]] \
                || die "Could not clone $REPO and no local files were provided"
            warn "Clone failed; reusing webssh.html/requirements.txt already installed"
            mkdir -p "$TMP_DIR/repo"; cp "$APP_DIR/webssh.html" "$APP_DIR/requirements.txt" "$TMP_DIR/repo/"
        fi
    else mkdir -p "$TMP_DIR/repo"; fi
    SRC_BOT="${LOCAL_BOT:-$TMP_DIR/repo/bot.py}"
    SRC_WEBSSH="$SCRIPT_DIR/webssh.html";   [[ -f "$SRC_WEBSSH" ]] || SRC_WEBSSH="$TMP_DIR/repo/webssh.html"
    SRC_REQ="$SCRIPT_DIR/requirements.txt"; [[ -f "$SRC_REQ" ]] || SRC_REQ="$TMP_DIR/repo/requirements.txt"
    [[ -f "$SRC_BOT" ]]    || die "bot.py not found"
    [[ -f "$SRC_WEBSSH" ]] || die "webssh.html not found"
    [[ -f "$SRC_REQ" ]]    || die "requirements.txt not found"
    [[ -n "$LOCAL_BOT" ]] && info "Using local bot.py: $LOCAL_BOT"
    info "bot.py: $(wc -l < "$SRC_BOT") lines, $(du -h "$SRC_BOT" | awk '{print $1}')"
}

merge_env() {
    section "ENVIRONMENT"
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$TMP_DIR/repo/.env.example" ]]; then cp "$TMP_DIR/repo/.env.example" "$ENV_FILE"; else : > "$ENV_FILE"; fi
        chmod 600 "$ENV_FILE"; ok "Created $ENV_FILE"
    else ok "Existing .env preserved"; fi
    if [[ -f "$TMP_DIR/repo/.env.example" ]]; then      # merge new keys from the repo template, never overwrite
        local line key
        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]] || continue
            key="${BASH_REMATCH[1]}"
            grep -qE "^[[:space:]]*${key}=" "$ENV_FILE" || printf '%s\n' "$line" >> "$ENV_FILE"
        done < "$TMP_DIR/repo/.env.example"
    fi
    chmod 600 "$ENV_FILE"
    ensure_env BOT_NAME "SVM V11.2"; ensure_env PREFIX "!"; ensure_env YOUR_SERVER_IP "127.0.0.1"
    ensure_env BOT_VERSION "11.3-PLUS"; ensure_env DISCORD_TOKEN ""; ensure_env MAIN_ADMIN_ID ""
    write_default_env
    apply_env_overrides
    ok "New keys merged (existing values untouched)"
}

deploy_files() {
    section "DEPLOY"
    install -m 750 "$SRC_BOT" "$APP_DIR/bot.py"
    install -m 644 "$SRC_WEBSSH" "$APP_DIR/webssh.html"
    install -m 644 "$SRC_REQ" "$APP_DIR/requirements.txt"
    ok "bot.py + webssh.html + requirements.txt deployed"
}

setup_venv() {
    section "PYTHON ENVIRONMENT"
    PY="$APP_DIR/venv/bin/python"; PIP="$APP_DIR/venv/bin/pip"
    [[ -x "$PY" ]] || python3 -m venv "$APP_DIR/venv"
    "$PY" -m pip install --quiet --upgrade pip setuptools wheel
    "$PIP" install --quiet --upgrade -r "$APP_DIR/requirements.txt"
    # modules bot.py imports even if requirements.txt forgot them
    "$PIP" install --quiet "discord.py>=2.3" python-dotenv requests paramiko flask flask-cors   # only adds what is missing
    ok "Python dependencies installed"
}

validate_bot() {
    section "STATIC VALIDATION"
    APP_DIR_FOR_PY="$APP_DIR" "$PY" - <<'PY'
import ast, os, sys
from pathlib import Path
src = (Path(os.environ["APP_DIR_FOR_PY"]) / "bot.py").read_text(encoding="utf-8")
tree = ast.parse(src)
for needle in ("import discord", "from dotenv import load_dotenv", "import sqlite3", "from flask import Flask"):
    if needle not in src:
        sys.exit(f"Required component missing: {needle}")
runs = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run"
        and getattr(getattr(n.func, "value", None), "id", "") == "bot"]
last_def = max((n.end_lineno for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), default=0)
if runs and min(runs) < last_def:
    sys.exit(f"bot.run() at line {min(runs)} is before code that ends at line {last_def}: everything after it would never load!")
print(f"AST OK • {len(src.splitlines())} lines • bot.run() is last")
PY
    ok "bot.py validated (syntax + 'bot.run must be last' check)"
}

setup_firewall() {
    section "FIREWALL"
    local lo hi port
    lo="$(get_env PORT_RANGE_START)"; hi="$(get_env PORT_RANGE_END)"; port="$(get_env PAYMENT_WEBHOOK_PORT)"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow "${lo}:${hi}/tcp" >/dev/null; ufw allow "${lo}:${hi}/udp" >/dev/null
        [[ "${SETUP_CADDY:-0}" == "1" ]] && { ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; }
        ok "ufw: opened ${lo}-${hi} (tcp+udp)"
    else
        info "ufw not active — make sure your firewall/cloud security group allows ${lo}-${hi} tcp+udp"
    fi
    [[ "$(get_env PAYMENT_WEBHOOK_HOST)" == "0.0.0.0" ]] && warn "Webhook port ${port} listens on 0.0.0.0 over plain HTTP — use an HTTPS proxy."
    return 0
}

setup_caddy() {
    [[ "${SETUP_CADDY:-0}" == "1" ]] || return 0
    section "HTTPS REVERSE PROXY (Caddy)"
    local url host port; url="$(get_env SVM_PUBLIC_URL)"; host="${url#https://}"; host="${host%%/*}"; port="$(get_env PAYMENT_WEBHOOK_PORT)"
    command -v caddy >/dev/null 2>&1 || { apt-get install -y caddy >/dev/null 2>&1 || { warn "Could not install caddy; set up HTTPS manually."; return 0; }; }
    mkdir -p /etc/caddy; touch /etc/caddy/Caddyfile
    python3 - "$host" "$port" <<'PY'
import re, sys
host, port = sys.argv[1], sys.argv[2]
path = "/etc/caddy/Caddyfile"
text = open(path).read()
text = re.sub(r"\n?# SVM\+ BEGIN.*?# SVM\+ END\n?", "\n", text, flags=re.S)
block = f"""
# SVM+ BEGIN
{host} {{
    @svm path /razorpay/webhook /stripe/webhook /health
    handle @svm {{
        reverse_proxy 127.0.0.1:{port}
    }}
    handle {{
        respond "Not found" 404
    }}
}}
# SVM+ END
"""
open(path, "w").write(text.rstrip("\n") + "\n" + block)
PY
    systemctl enable caddy >/dev/null 2>&1 || true
    systemctl reload caddy 2>/dev/null || systemctl restart caddy 2>/dev/null || warn "Caddy failed to reload — check: journalctl -u caddy"
    ok "Caddy serves https://${host} → 127.0.0.1:${port} (only /razorpay/webhook, /stripe/webhook, /health)"
}

install_service() {
    section "SYSTEMD"
    cat > "/etc/systemd/system/${SERVICE}.service" <<UNIT
[Unit]
Description=SVM+ V11.3 VPS Platform — Made by AnkitCoder
Documentation=https://github.com/AnkitKing7/Svm-v11.2-bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/bot.py
Restart=always
RestartSec=5
StartLimitIntervalSec=120
StartLimitBurst=10
TimeoutStopSec=30
KillSignal=SIGINT
LimitNOFILE=65535
StandardOutput=journal
StandardError=journal
SyslogIdentifier=svm
# the bot drives LXC/iptables on the host, so it runs as root without sandboxing

[Install]
WantedBy=multi-user.target
UNIT
    cat > "/etc/systemd/system/${SERVICE}-backup.service" <<UNIT
[Unit]
Description=SVM+ database backup
[Service]
Type=oneshot
ExecStart=/usr/local/bin/svm backup --quiet
UNIT
    cat > "/etc/systemd/system/${SERVICE}-backup.timer" <<UNIT
[Unit]
Description=Daily SVM+ database backup
[Timer]
OnCalendar=daily
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable "${SERVICE}.service" "${SERVICE}-backup.timer" >/dev/null 2>&1
    systemctl start "${SERVICE}-backup.timer" >/dev/null 2>&1 || true
    ok "service + daily backup timer installed"
}

install_cli() {
    cat > /usr/local/bin/svm <<'CLI'
#!/usr/bin/env bash
# SVM+ management helper
APP_DIR="__APP_DIR__"; SERVICE="__SERVICE__"; ENV_FILE="$APP_DIR/.env"
envval() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"; }
case "${1:-help}" in
  status)  systemctl status "$SERVICE" --no-pager ;;
  logs)    journalctl -u "$SERVICE" -f -n "${2:-100}" ;;
  restart) systemctl restart "$SERVICE" && echo restarted ;;
  stop)    systemctl stop "$SERVICE" ;;
  config)  "${EDITOR:-nano}" "$ENV_FILE" && echo "Run: svm restart" ;;
  env)     [[ -n "${2:-}" ]] && envval "$2" && echo || echo "usage: svm env KEY" ;;
  backup)
    dest="$APP_DIR/db_backups/vps-$(date +%Y%m%d-%H%M%S).db"; mkdir -p "$APP_DIR/db_backups"
    sqlite3 "$APP_DIR/vps.db" ".backup '$dest'" && chmod 600 "$dest"
    ls -1t "$APP_DIR"/db_backups/vps-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f
    [[ "${2:-}" == "--quiet" ]] || echo "Backup: $dest" ;;
  rollback) shift; exec bash "$APP_DIR/source/install.sh" --rollback "$@" ;;
  update)   exec bash "$APP_DIR/source/install.sh" "${@:2}" ;;
  doctor)
    echo "service : $(systemctl is-active "$SERVICE")"
    echo "token   : $([[ -n "$(envval DISCORD_TOKEN)" ]] && echo set || echo MISSING)"
    echo "gateways: $(envval PAYMENT_GATEWAYS)"
    echo "ip mode : $(envval IPAM_BIND_MODE)   ports: $(envval PORT_RANGE_START)-$(envval PORT_RANGE_END)"
    p="$(envval PAYMENT_WEBHOOK_PORT)"
    curl -fsS --max-time 3 "http://127.0.0.1:${p:-8787}/health" >/dev/null 2>&1 && echo "webhook : up on :${p:-8787}" || echo "webhook : down (needs a *_WEBHOOK_SECRET)"
    u="$(envval SVM_PUBLIC_URL)"; [[ -n "$u" ]] && { curl -fsS --max-time 5 "$u/health" >/dev/null 2>&1 && echo "public  : $u reachable" || echo "public  : $u NOT reachable"; }
    journalctl -u "$SERVICE" -n 80 --no-pager | grep -Ei "traceback|error" | tail -n 5 ;;
  *) echo "svm status|logs|restart|stop|config|env KEY|backup|rollback [snapshot]|update|doctor" ;;
esac
CLI
    sed -i "s|__APP_DIR__|${APP_DIR}|g; s|__SERVICE__|${SERVICE}|g" /usr/local/bin/svm
    chmod 755 /usr/local/bin/svm
    mkdir -p "$APP_DIR/source"
    if [[ "$(readlink -f "${BASH_SOURCE[0]}")" != "$APP_DIR/source/install.sh" ]]; then cp -f "${BASH_SOURCE[0]}" "$APP_DIR/source/install.sh"; fi
    chmod 700 "$APP_DIR/source/install.sh"
    ok "CLI installed: svm status | logs | restart | config | backup | rollback | update | doctor"
}

health_check_or_rollback() {
    section "HEALTH CHECK"
    (( NO_START )) && { warn "--no-start: skipping restart"; return 0; }
    systemctl restart "${SERVICE}.service"
    local i healthy=0
    for i in $(seq 1 20); do
        sleep 2
        systemctl is-active --quiet "${SERVICE}.service" || continue
        if (( i >= 5 )) && ! journalctl -u "${SERVICE}.service" --since "-30s" --no-pager 2>/dev/null | grep -Eq 'Traceback|SyntaxError|ImportError|ModuleNotFoundError'; then healthy=1; break; fi
    done
    if (( healthy )); then ok "Service is running with no startup errors"; return 0; fi
    warn "Service unhealthy after upgrade — rolling bot.py back to the previous version"
    journalctl -u "${SERVICE}.service" -n 40 --no-pager || true
    if [[ -f "$SNAP/bot.py" ]]; then
        cp -a "$SNAP/bot.py" "$APP_DIR/bot.py"; [[ -f "$SNAP/requirements.txt" ]] && cp -a "$SNAP/requirements.txt" "$APP_DIR/requirements.txt"
        systemctl restart "${SERVICE}.service" || true
        die "Upgrade failed; previous bot.py restored from $SNAP"
    fi
    die "Upgrade failed and there was no previous version to restore. Fix the logs above (svm logs)."
}

do_rollback() {
    section "ROLLBACK"
    local target="${ROLLBACK_TARGET:-}"
    [[ -n "$target" ]] || target="$(ls -1dt "$BACKUP_DIR"/upgrade-* 2>/dev/null | head -n1 || true)"
    [[ -d "$target" ]] || target="$BACKUP_DIR/$target"
    [[ -d "$target" ]] || die "No snapshot found. Available: $(ls "$BACKUP_DIR" 2>/dev/null | tr '\n' ' ')"
    [[ -f "$target/bot.py" ]] || die "Snapshot has no bot.py"
    cp -a "$target/bot.py" "$APP_DIR/bot.py"
    [[ -f "$target/requirements.txt" ]] && cp -a "$target/requirements.txt" "$APP_DIR/requirements.txt"
    [[ -f "$target/webssh.html" ]] && cp -a "$target/webssh.html" "$APP_DIR/webssh.html"
    systemctl restart "${SERVICE}.service"
    ok "Restored bot.py from $target (your .env and vps.db were not touched; DB copy is in the snapshot if needed)"
}

print_summary() {
    local url; url="$(get_env SVM_PUBLIC_URL)"
    printf "\n${B}${G}SVM+ V11.3 installed${R}\n"
    cat <<EOF
  App      : ${APP_DIR}          Config : ${ENV_FILE}
  Backup   : ${SNAP:-n/a}
  Commands : svm status | logs | restart | config | doctor | backup | rollback | update
  Gateways : $(get_env PAYMENT_GATEWAYS)    IP mode: $(get_env IPAM_BIND_MODE)    Ports: $(get_env PORT_RANGE_START)-$(get_env PORT_RANGE_END)
  Webhooks : ${url:-<set SVM_PUBLIC_URL>}/razorpay/webhook   ${url:-<set SVM_PUBLIC_URL>}/stripe/webhook

  In Discord (admin):  !gateways  !svm-health  !ipool add pub 203.0.113.0/28 203.0.113.1  !portadmin stats  !orders
  Users:               !plans  !buy <plan> [gateway]  !renew <vps#>  !myorders  !ports add <vps#> <port>

EOF
    warn "Secrets live only in ${ENV_FILE} (chmod 600). Never paste them into Discord or commit them to GitHub."
}

main() {
    while (( $# )); do
        case "$1" in
            --configure) MODE="configure" ;;
            --rollback) MODE="rollback"
                        if [[ -n "${2:-}" && "${2:-}" != --* ]]; then ROLLBACK_TARGET="$2"; shift; fi ;;
            --local-bot) LOCAL_BOT="${2:?--local-bot needs a file}"; shift ;;
            --non-interactive|-y) INTERACTIVE=0 ;;
            --no-start) NO_START=1 ;;
            -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
            *) die "Unknown option: $1 (see --help)" ;;
        esac; shift
    done
    trap 'die "Failed at line ${LINENO}. Check: journalctl -u ${SERVICE} -n 150 --no-pager"' ERR
    banner
    [[ "$(id -u)" == "0" ]] || die "Run as root: sudo bash $0"
    exec 9>"$LOCK_FILE"; flock -n 9 || die "Another SVM installer is already running"

    case "$MODE" in
        rollback)  do_rollback; return ;;
        configure) mkdir -p "$APP_DIR"; touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
                   command -v python3 >/dev/null || die "python3 required"
                   write_default_env; apply_env_overrides; configure_env; setup_firewall; setup_caddy
                   systemctl restart "${SERVICE}.service" 2>/dev/null && ok "Service restarted" || warn "Service not installed yet"
                   return ;;
    esac

    section "SYSTEM"
    info "OS: $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}")  •  kernel $(uname -r)  •  $(uname -m)"
    install_packages
    backup_snapshot
    fetch_sources
    merge_env
    (( INTERACTIVE )) && yesno "Run the configuration wizard now (gateways, IP pool, ports)?" "$([[ -z "$(get_env DISCORD_TOKEN)" ]] && echo y || echo n)" && configure_env || validate_env
    deploy_files
    setup_venv
    validate_bot
    setup_firewall
    setup_caddy
    install_service
    install_cli
    health_check_or_rollback
    print_summary
}

if [[ "${SVM_SOURCE_ONLY:-0}" != "1" ]]; then main "$@"; fi
