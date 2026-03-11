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

Check these settings in `install.sh` and change any that don't match your Proxmox setup:

| Variable | Default | What to change |
|----------|---------|----------------|
| `CT_BRIDGE` | `vmbr0` | Your Proxmox network bridge. Run `ip link` on the node to list bridges |
| `CT_STORAGE` | `local-lvm` | Storage pool for the container disk. Run `pvesm status` to list available pools |
| `CT_TEMPLATE_STORAGE` | `local` | Where LXC templates are stored |
| `CT_RAM` | `512` MB | Increase to `1024` if you plan heavy playlist downloads |
| `CT_DISK` | `4` GB | Increase if you need more scratch space (files are streamed then deleted, so 4 GB is usually fine) |

### Run the Installer

Run this **on the Proxmox node shell** (not inside a container):

```bash
bash -c "$(wget -qO- https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/install.sh)"
```

The script will:
1. Find the next free CT ID (starting at 200)
2. Download a Debian 12 LXC template (if not already present)
3. Create an unprivileged container with nesting enabled (1 CPU, 512 MB RAM, 4 GB disk, DHCP)
4. Run `setup.sh` inside the container — installs all dependencies and creates a `systemd` service
5. Print the container ID and access URL: `http://<CONTAINER_IP>:8080`

### After the Installer Finishes

**1. Open the web UI**

Navigate to the URL printed at the end of the installer in any browser:
```
http://<CONTAINER_IP>:8080
```

If you don't see the IP, run this on the Proxmox node:
```bash
pct exec <CTID> -- hostname -I
```

---

**2. Enter the container shell**

For all configuration and management tasks below, first open a shell **inside the container**:

```bash
# Run on the Proxmox node to open a shell inside the LXC
pct enter <CTID>
```

You are now inside the container. All the commands in the sections below are run here.

---

**3. (Optional) Set a persistent secret key**

By default a random `SECRET_KEY` is generated at every startup, so browser sessions are lost when the service restarts. To set a permanent key, open a drop-in override editor:

```bash
# Inside the container shell:
systemctl edit media-downloader
```

The editor opens an empty override file. Enter the following (see [`docs/systemd-override.example.conf`](docs/systemd-override.example.conf) for all available options):

```ini
[Service]
Environment="SECRET_KEY=replace-with-a-long-random-string"
```

> **Tip:** Generate a secure value with `openssl rand -hex 32`.

Save and close the editor, then apply the change:

```bash
# Inside the container shell:
systemctl daemon-reload
systemctl restart media-downloader
```

---

**4. Check the service status**

```bash
# Inside the container shell:
systemctl status media-downloader

# Follow live logs:
journalctl -u media-downloader -f

# View the last 50 log lines:
journalctl -u media-downloader -n 50
```

---

**5. Update the application**

```bash
# Inside the container shell:
git -C /opt/media-downloader pull --ff-only
systemctl restart media-downloader
```

To also update `yt-dlp` and `spotdl`, re-run the full setup script:

```bash
# Inside the container shell:
curl -fsSL https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/setup.sh | bash
```

---

**6. Keep `yt-dlp` up to date**

YouTube changes frequently. If downloads suddenly stop working, update `yt-dlp`:

```bash
# Inside the container shell:
yt-dlp -U
```

---

**7. Manage the container** *(run on the Proxmox node)*

```bash
# Stop the container
pct stop <CTID>

# Start the container
pct start <CTID>

# Open a shell inside the container
pct enter <CTID>

# Restart just the app service without entering the container
pct exec <CTID> -- systemctl restart media-downloader
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
├── install.sh          # Proxmox LXC one-liner (run on the Proxmox node)
├── setup.sh            # In-container setup (installs deps + systemd)
├── docs/
│   └── systemd-override.example.conf   # Example systemd drop-in for env vars
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
| `yt-dlp` returns errors | Enter the container (`pct enter <CTID>`) and run `yt-dlp -U` to update |
| Spotify 401 / auth errors | `spotdl` may need a Spotify developer token — see [spotdl docs](https://spotdl.readthedocs.io/) |
| Container has no internet | Check `CT_BRIDGE` in `install.sh` matches your Proxmox bridge (`ip link` on the node) |
| Can't reach the UI | Make sure the container is running (`pct status <CTID>`) and confirm the IP with `pct exec <CTID> -- hostname -I` |
| Port 8080 already in use | Enter the container and set `APP_PORT` via `systemctl edit media-downloader` (see [`docs/systemd-override.example.conf`](docs/systemd-override.example.conf)) |
| Service won't start | Enter the container and run `journalctl -u media-downloader -n 50` |
| Sessions lost after restart | Enter the container and set a persistent `SECRET_KEY` via `systemctl edit media-downloader` (see [step 3](#3-optional-set-a-persistent-secret-key)) |
| SECRET_KEY warning in logs | Set the `SECRET_KEY` environment variable — see [`docs/systemd-override.example.conf`](docs/systemd-override.example.conf) |
| Wrong storage pool error | Change `CT_STORAGE` in `install.sh` to match your pool (`pvesm status` lists them) |

---

## 📜 License

[MIT](LICENSE) ©2026 0-exe
