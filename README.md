# Media Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)

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

## 🚀 One-Line Proxmox Install

Run this on the **Proxmox host**:

```bash
bash -c "$(wget -qO- https://raw.githubusercontent.com/0-exe/media-dowlnoader/main/install.sh)"
```

This will:
1. Find the next free CT ID (≥ 200)
2. Download a Debian 12 LXC template if not already present
3. Create a container (1 CPU, 512 MB RAM, 4 GB disk)
4. Run `setup.sh` inside the container (installs all deps + systemd service)
5. Print the access URL: `http://<CONTAINER_IP>:8080`

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

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/youtube/info` | Fetch YouTube video metadata. Body: `{"url": "..."}` |
| `GET` | `/api/youtube/download` | Stream YouTube download. Params: `url`, `format` (360p/480p/720p/1080p/1440p/2160p/mp3/flac) |
| `POST` | `/api/spotify/info` | Fetch Spotify metadata. Body: `{"url": "..."}` |
| `GET` | `/api/spotify/download` | Stream Spotify track or collection. Params: `url`, `format` (mp3/flac) |

### Example — YouTube info

```bash
curl -s -X POST http://localhost:8080/api/youtube/info \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' | jq .
```

---

## 🗂 Project Structure

```
media-dowlnoader/
├── install.sh          # Proxmox LXC one-liner (run on host)
├── setup.sh            # In-container setup (installs deps + systemd)
├── requirements.txt    # Python dependencies
├── app.py              # Flask backend
├── static/
│   ├── css/style.css
│   ├── js/app.js
│   └── img/logo.svg
├── templates/
│   └── index.html
└── LICENSE
```

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| `yt-dlp` returns errors | Run `yt-dlp -U` to update to the latest version |
| Spotify 401 / auth errors | `spotdl` may need a Spotify developer token — see [spotdl docs](https://spotdl.readthedocs.io/) |
| Container has no internet | Check `CT_BRIDGE` in `install.sh` matches your Proxmox bridge |
| Port 8080 already in use | Edit `APP_PORT` in `install.sh` / `setup.sh` and `app.py` |
| Service won't start | `pct exec <CTID> -- journalctl -u media-downloader -n 50` |

---

## 📜 License

[MIT](LICENSE) ©2026 0-exe
