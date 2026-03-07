#!/usr/bin/env bash
# install.sh — One-line Proxmox LXC installer for Media Downloader
#
# Run on the PROXMOX HOST:
#   bash -c "$(wget -qO- https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/install.sh)"
#
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
CT_START_ID=200
CT_CORES=1
CT_RAM=512       # MB
CT_DISK=4        # GB
CT_HOSTNAME="media-downloader"
CT_BRIDGE="vmbr0"
CT_STORAGE="local-lvm"      # Change if your storage pool differs
CT_TEMPLATE_STORAGE="local"
TEMPLATE_ALIAS="debian-12-standard"

APP_PORT=8080

# ── Colours ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[1;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[install]${NC} $*"; }
ok()   { echo -e "${GREEN}[  ok  ]${NC} $*"; }
err()  { echo -e "${RED}[ FAIL ]${NC} $*" >&2; exit 1; }

# ── Verify we're on Proxmox ──────────────────────────────────────────
command -v pct  &>/dev/null || err "This script must run on a Proxmox host (pct not found)."
command -v pvesh &>/dev/null || err "pvesh not found — are you on the Proxmox host?"

# ── Find next free CT ID ─────────────────────────────────────────────
log "Finding next available CT ID (starting at $CT_START_ID)…"
CT_ID=$CT_START_ID
while pct status "$CT_ID" &>/dev/null; do
    CT_ID=$((CT_ID + 1))
done
ok "Using CT ID: $CT_ID"

# ── Download LXC template if needed ─────────────────────────────────
log "Checking for $TEMPLATE_ALIAS template…"
TEMPLATE=$(pveam list "$CT_TEMPLATE_STORAGE" 2>/dev/null \
    | grep "$TEMPLATE_ALIAS" | head -1 | awk '{print $1}')

if [[ -z "$TEMPLATE" ]]; then
    log "Template not found locally. Downloading…"
    pveam update
    DL_TEMPLATE=$(pveam available --section system \
        | grep "$TEMPLATE_ALIAS" | head -1 | awk '{print $2}')
    [[ -z "$DL_TEMPLATE" ]] && err "Could not find a Debian 12 template in pveam. Please download one manually."
    pveam download "$CT_TEMPLATE_STORAGE" "$DL_TEMPLATE"
    TEMPLATE="${CT_TEMPLATE_STORAGE}:vztmpl/${DL_TEMPLATE}"
fi
ok "Template: $TEMPLATE"

# ── Create the LXC container ─────────────────────────────────────────
log "Creating LXC container CT$CT_ID ($CT_HOSTNAME)…"
pct create "$CT_ID" "$TEMPLATE" \
    --hostname  "$CT_HOSTNAME" \
    --cores     "$CT_CORES"   \
    --memory    "$CT_RAM"     \
    --rootfs    "${CT_STORAGE}:${CT_DISK}" \
    --net0      "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
    --unprivileged 1 \
    --features  "nesting=1" \
    --start     1 \
    --onboot    1

ok "Container CT$CT_ID created and started."

# ── Wait for container to boot ───────────────────────────────────────
log "Waiting for container to come up…"
sleep 6

# ── Run setup.sh inside the container ───────────────────────────────
log "Running in-container setup…"
pct exec "$CT_ID" -- bash -c "
    apt-get update -qq && apt-get install -y -qq curl git > /dev/null
    curl -fsSL https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/setup.sh | bash
"

# ── Retrieve container IP ────────────────────────────────────────────
CONTAINER_IP=$(pct exec "$CT_ID" -- hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Media Downloader — Installation Complete          ║${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
printf  "${GREEN}║   Container ID : %-43s ║${NC}\n" "$CT_ID"
printf  "${GREEN}║   Access URL   : %-43s ║${NC}\n" "http://$CONTAINER_IP:$APP_PORT"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
log "To open a shell in the container:  pct enter $CT_ID"
log "To check service status:           pct exec $CT_ID -- systemctl status media-downloader"
