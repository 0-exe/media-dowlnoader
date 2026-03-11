# Media Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](Dockerfile)

> **YouTube + Spotify downloader** — dark‑themed web app that streams files to your browser. Files are downloaded to temporary server-side storage and automatically deleted after the transfer completes.

---

## ✨ Features

| Feature | Details |
|---------|---------|
| **YouTube** | Paste URL → preview card → choose 360p / 480p / 720p / 1080p / 1440p / 2160p (4K) or MP3 / FLAC → stream to browser |
| **Spotify** | Paste track/album/playlist URL → preview card → choose MP3 or FLAC → stream MP3/FLAC or ZIP (playlists) |
| **Temp storage** | Downloads are saved to temporary server-side files (with metadata & thumbnail embedded), streamed to browser, then deleted |
| **Dark UI** | Custom CSS with glassmorphism, responsive layout, animated progress bars, toast notifications |
| **Lightweight** | Runs on 1 CPU / 512 MB RAM (Proxmox LXC or any small VPS) |
| **Rate limited** | Built-in per-IP rate limiting to prevent abuse |

---

## 💻 Local Demo (Website UI Only)

You can run the web interface locally to preview the UI **without** installing `yt-dlp` or `spotdl`. Fetch/Download actions will return errors, but the full UI is visible.

### Prerequisites

- Python 3.10+
- Git

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/0-exe/media-dowlnoader.git
cd media-dowlnoader

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install only the web-server dependencies (skip yt-dlp / spotdl)
pip install Flask==3.1.3 Flask-Limiter==4.1.1 Werkzeug==3.1.6 \
            zipstream-new==1.1.8 requests==2.32.5

# 4. Start the server
python app.py
```

Open **http://localhost:8080** in your browser. You will see the full dark-themed UI with the YouTube and Spotify tabs. Clicking *Fetch* or *Download* without the backend tools installed will surface an error toast, which is expected.

> **Tip:** To enable actual downloads, install the full dependencies as described in the [Manual Install](#-manual-install) section.

---

## 🐳 Docker

```bash
# Build
docker build -t media-downloader .

# Run
docker run -d \
  --name media-downloader \
  -p 8080:8080 \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  media-downloader

# Or with Docker Compose (see below)
```

### Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  media-downloader:
    build: .
    ports:
      - "8080:8080"
    environment:
      - SECRET_KEY=change-me-to-a-random-string
    restart: unless-stopped
```

Then run:

```bash
docker compose up -d
```

---

## 🚀 Proxmox LXC Install

### Before You Run

Open `install.sh` (or pass environment variables) and confirm these defaults match your Proxmox setup:

| Variable | Default | What to change |
|----------|---------|----------------|
| `CT_BRIDGE` | `vmbr0` | Your Proxmox network bridge (run `ip link` on the host to list bridges) |
| `CT_STORAGE` | `local-lvm` | Storage pool for the container rootfs (`pvesm status` lists available pools) |
| `CT_TEMPLATE_STORAGE` | `local` | Where LXC templates are stored |
| `CT_RAM` | `512` MB | Increase to `1024` if you plan heavy playlist downloads |
| `CT_DISK` | `4` GB | Increase if you want more scratch space (files are streamed and then deleted, so 4 GB is normally fine) |

### Run the installer

Execute this **on the Proxmox host** shell (not inside any container):

```bash
bash -c "$(wget -qO- https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/install.sh)"
```

The script will:
1. Find the next free CT ID (≥ 200)
2. Download a Debian 12 LXC template if not already present
3. Create an unprivileged container (1 CPU, 512 MB RAM, 4 GB disk, DHCP, nesting enabled)
4. Run `setup.sh` inside the container — installs all dependencies and creates a `systemd` service
5. Print the container ID and access URL: `http://<CONTAINER_IP>:8080`

### After the installer finishes

**1. Open the web UI**

Navigate to the URL printed at the end of the script in any browser:
```
http://<CONTAINER_IP>:8080
```

If you don't know the IP, run this on the Proxmox host:
```bash
pct exec <CTID> -- hostname -I
```

**2. (Optional) Set a persistent secret key**

By default a random `SECRET_KEY` is generated at startup, which means browser sessions are lost when the service restarts. To fix this, open a shell in the container and set it permanently:

```bash
# Open a shell inside the container
pct enter <CTID>

# Edit the systemd service to add the secret key
systemctl edit media-downloader
```

Add the following under `[Service]`:
```ini
[Service]
Environment="SECRET_KEY=replace-with-a-long-random-string"
```

Then reload and restart:
```bash
systemctl daemon-reload && systemctl restart media-downloader
exit
```

**3. Check the service is running**

```bash
# From the Proxmox host:
pct exec <CTID> -- systemctl status media-downloader

# View live logs:
pct exec <CTID> -- journalctl -u media-downloader -f

# View the last 50 log lines:
pct exec <CTID> -- journalctl -u media-downloader -n 50
```

**4. Manage the container**

```bash
# Stop the container
pct stop <CTID>

# Start the container
pct start <CTID>

# Open an interactive shell inside the container
pct enter <CTID>

# Restart just the application service (container stays running)
pct exec <CTID> -- systemctl restart media-downloader
```

**5. Update the application**

To pull the latest code and restart the service:

```bash
pct exec <CTID> -- bash -c "
  git -C /opt/media-downloader pull --ff-only && \
  systemctl restart media-downloader
"
```

Or re-run the full `setup.sh` to also update `yt-dlp` and `spotdl`:

```bash
pct exec <CTID> -- bash -c \
  "curl -fsSL https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/setup.sh | bash"
```

**6. Keep `yt-dlp` up to date**

YouTube changes frequently. If downloads suddenly stop working, update `yt-dlp`:

```bash
pct exec <CTID> -- yt-dlp -U
```

---

## 🛠 Manual Install

```bash
# Prerequisites: Python 3.10+, ffmpeg, yt-dlp, spotdl
git clone https://github.com/0-exe/media-dowlnoader.git
cd media-dowlnoader
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py          # http://0.0.0.0:8080
```

Or use the setup script directly inside any Debian/Ubuntu machine:

```bash
curl -fsSL https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/setup.sh | sudo bash
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(random)* | Flask secret key. **Set this in production** — a random key is generated on startup if not provided, but sessions will not survive restarts. |
| `APP_PORT` | `8080` | Port the web server listens on. |

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/api/health` | Health check — returns `{"status":"ok","version":"..."}` |
| `POST` | `/api/youtube/info` | Fetch YouTube video metadata. Body: `{"url": "..."}` |
| `GET` | `/api/youtube/download` | Stream YouTube download. Params: `url`, `format` (360p/480p/720p/1080p/1440p/2160p/mp3/flac) |
| `POST` | `/api/spotify/info` | Fetch Spotify metadata. Body: `{"url": "..."}` |
| `GET` | `/api/spotify/download` | Stream Spotify track or collection. Params: `url`, `format` (mp3/flac) |

### Rate Limits

| Endpoint | Limit |
|----------|-------|
| `/api/youtube/info` | 30 requests / minute |
| `/api/youtube/download` | 10 requests / minute |
| `/api/spotify/info` | 20 requests / minute |
| `/api/spotify/download` | 5 requests / minute |
| All other endpoints | 200 / day, 50 / hour |

### Example — YouTube info

```bash
curl -s -X POST http://localhost:8080/api/youtube/info \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' | jq .
```

### Example — Health check

```bash
curl -s http://localhost:8080/api/health | jq .
# {"status": "ok", "version": "2.1.0"}
```

---

## 🗂 Project Structure

```
media-dowlnoader/
├── app.py              # Flask backend
├── Dockerfile          # Docker image definition
├── requirements.txt    # Python dependencies
├── install.sh          # Proxmox LXC one-liner (run on host)
├── setup.sh            # In-container setup (installs deps + systemd)
├── static/
│   ├── css/style.css   # Dark-themed responsive CSS
│   ├── js/app.js       # Frontend logic
│   └── img/logo.svg    # Application logo
├── templates/
│   └── index.html      # Single-page Jinja2 template
└── LICENSE
```

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| `yt-dlp` returns errors | Run `yt-dlp -U` (or `pct exec <CTID> -- yt-dlp -U`) to update to the latest version |
| Spotify 401 / auth errors | `spotdl` may need a Spotify developer token — see [spotdl docs](https://spotdl.readthedocs.io/) |
| Container has no internet | Check `CT_BRIDGE` in `install.sh` matches your Proxmox bridge (`ip link` on the host) |
| Can't reach the UI | Make sure the container is running (`pct status <CTID>`) and confirm the IP with `pct exec <CTID> -- hostname -I` |
| Port 8080 already in use | Set the `APP_PORT` environment variable to a different port |
| Service won't start | `pct exec <CTID> -- journalctl -u media-downloader -n 50` |
| Sessions lost after restart | Set a persistent `SECRET_KEY` via `systemctl edit media-downloader` (see [After the installer finishes](#after-the-installer-finishes)) |
| SECRET_KEY warning in logs | Set the `SECRET_KEY` environment variable for production deployments |
| Wrong storage pool error | Change `CT_STORAGE` in `install.sh` to match your pool (`pvesm status` lists them) |

---

## 📜 License

[MIT](LICENSE) ©2026 0-exe
