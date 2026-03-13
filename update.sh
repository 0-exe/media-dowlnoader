#!/usr/bin/env bash
# update.sh — Update Media Downloader (app code, dependencies, yt-dlp, spotdl)
# Run inside the LXC container shell, or via: update
set -euo pipefail

APP_DIR="/opt/media-downloader"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="media-downloader"

log() { echo -e "\033[1;34m[update]\033[0m $*"; }
ok()  { echo -e "\033[1;32m[  ok  ]\033[0m $*"; }
err() { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[[ -d "$APP_DIR/.git" ]] || err "App directory $APP_DIR not found. Is Media Downloader installed?"

# ── 1. Update application code ───────────────────────────────────────
log "Pulling latest code…"
git -C "$APP_DIR" pull --ff-only
ok "Code updated."

# ── 2. Update Python dependencies ────────────────────────────────────
log "Updating Python dependencies…"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
ok "Python dependencies updated."

# ── 3. Update yt-dlp ─────────────────────────────────────────────────
log "Updating yt-dlp…"
curl -fsSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp
chmod +x /usr/local/bin/yt-dlp
ok "yt-dlp updated: $(yt-dlp --version)"

# ── 4. Update spotdl ─────────────────────────────────────────────────
log "Updating spotdl…"
"$VENV_DIR/bin/pip" install --upgrade spotdl -q
ok "spotdl updated."

# ── 5. Restart the service ───────────────────────────────────────────
log "Restarting $SERVICE_NAME service…"
systemctl restart "$SERVICE_NAME"
ok "Service restarted."

echo ""
echo -e "\033[1;32m✔ Media Downloader has been updated successfully!\033[0m"
