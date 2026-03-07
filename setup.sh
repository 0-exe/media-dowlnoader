#!/usr/bin/env bash
# setup.sh — In-container setup for Media Downloader
# Called by install.sh inside the LXC container, or run manually.
set -euo pipefail

APP_DIR="/opt/media-downloader"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="media-downloader"
APP_PORT=8080

log() { echo -e "\033[1;34m[setup]\033[0m $*"; }
ok()  { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
err() { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; exit 1; }

# ── 1. System dependencies ───────────────────────────────────────────
log "Updating package lists…"
apt-get update -qq

log "Installing system packages…"
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    ffmpeg git curl wget \
    > /dev/null

ok "System packages installed."

# ── 2. Clone / update repo ───────────────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
    log "Updating existing repo at $APP_DIR…"
    git -C "$APP_DIR" pull --ff-only
else
    log "Cloning repo to $APP_DIR…"
    git clone https://github.com/0-exe/media-dowlnoader.git "$APP_DIR"
fi
ok "Repository ready."

# ── 3. Python virtual environment ───────────────────────────────────
log "Setting up Python virtual environment…"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
ok "Python dependencies installed."

# ── 4. Install yt-dlp (latest binary) ───────────────────────────────
log "Installing/updating yt-dlp…"
curl -fsSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp
chmod +x /usr/local/bin/yt-dlp
ok "yt-dlp installed: $(yt-dlp --version)"

# ── 5. Install spotdl ────────────────────────────────────────────────
log "Installing/updating spotdl…"
"$VENV_DIR/bin/pip" install spotdl -q
ok "spotdl installed."

# ── 6. systemd service ───────────────────────────────────────────────
log "Creating systemd service ($SERVICE_NAME)…"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Media Downloader Web App
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$VENV_DIR/bin/python $APP_DIR/app.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Ensure www-data can read the app directory
chown -R www-data:www-data "$APP_DIR" 2>/dev/null || true

systemctl daemon-reload
systemctl enable  "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
ok "Service '$SERVICE_NAME' enabled and started."

# ── 7. Done ──────────────────────────────────────────────────────────
CONTAINER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "\033[1;32m╔══════════════════════════════════════════════╗\033[0m"
echo -e "\033[1;32m║   Media Downloader is running!               ║\033[0m"
echo -e "\033[1;32m║                                              ║\033[0m"
echo -e "\033[1;32m║   Access URL: http://$CONTAINER_IP:$APP_PORT    ║\033[0m"
echo -e "\033[1;32m╚══════════════════════════════════════════════╝\033[0m"
