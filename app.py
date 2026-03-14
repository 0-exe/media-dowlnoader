"""
Media Downloader — Flask backend
=================================

Downloads YouTube and Spotify media to a temporary server-side file, then
streams the completed file to the browser (with ``Content-Length`` for
progress), and deletes the temp file once the transfer is done.

Architecture note
-----------------
Downloads are handled via a two-phase job system to stay compatible with
reverse proxies (e.g. Nginx Proxy Manager) that enforce short
``proxy_read_timeout`` values:

1. ``POST /api/youtube/start`` or ``POST /api/spotify/start`` — starts the
   download in a background thread and immediately returns a ``job_id``.
2. ``GET /api/jobs/<id>/status`` — the client polls this until the status
   becomes ``ready`` or ``error``.
3. ``GET /api/jobs/<id>/download`` — once ready, the browser navigates here
   directly so the file streams straight to disk without loading it into
   JavaScript memory.

Environment variables
---------------------
SECRET_KEY   : Flask secret key.  A random key is generated if not set
               (sessions will not survive restarts in that case).
APP_PORT     : Port to listen on (default ``8080``).

External tools required at runtime:
    * ``yt-dlp``  — YouTube downloads
    * ``spotdl``  — Spotify downloads
    * ``ffmpeg``  — media post-processing
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile as _zipfile
from urllib.parse import unquote

import requests
import zipstream
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("media-downloader")

app = Flask(__name__)

_secret = os.environ.get("SECRET_KEY")
if not _secret:
    _secret = os.urandom(24).hex()
    logger.warning(
        "SECRET_KEY is not set — using a random key. "
        "Sessions will not survive restarts. "
        "Set the SECRET_KEY environment variable for production use."
    )
app.config["SECRET_KEY"] = _secret

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

VERSION = "2.2.0"

# ---------------------------------------------------------------------------
# spotdl environment helper
# ---------------------------------------------------------------------------

def _spotdl_env() -> dict:
    """Return an environment for spotdl subprocesses with a writable HOME.

    spotdl creates config / cache directories under ``$HOME`` when it starts
    up.  When the app runs as a system user whose HOME is not writable (e.g.
    ``www-data`` → ``/var/www``), spotdl fails with *PermissionError*.
    We point HOME at a per-user temp directory so the subprocess can always
    write its config regardless of the deployment method.
    """
    env = os.environ.copy()
    spotdl_home = os.path.join(tempfile.gettempdir(), f"spotdl_home_{os.getuid()}")
    os.makedirs(spotdl_home, exist_ok=True)
    env["HOME"] = spotdl_home
    return env

# ---------------------------------------------------------------------------
# Background job management
# ---------------------------------------------------------------------------

# Each job entry:
#   {
#     "status":   "pending" | "ready" | "error",
#     "error":    str | None,
#     "tmp_dir":  str | None,   # directory to clean up
#     "fpath":    str | None,   # path to the final file
#     "filename": str | None,   # safe filename for Content-Disposition
#     "mime":     str | None,
#     "created":  float,        # time.time()
#   }
_jobs: dict = {}
_jobs_lock = threading.Lock()

# Maximum age of a finished/errored job before it is reaped (seconds).
_JOB_TTL = 3600  # 1 hour


def _make_job_id() -> str:
    return os.urandom(16).hex()


def _reap_old_jobs() -> None:
    """Remove jobs that are older than _JOB_TTL seconds."""
    cutoff = time.time() - _JOB_TTL
    with _jobs_lock:
        stale = [jid for jid, j in _jobs.items() if j["created"] < cutoff]
        for jid in stale:
            job = _jobs.pop(jid)
            if job.get("tmp_dir"):
                shutil.rmtree(job["tmp_dir"], ignore_errors=True)


def _set_job(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        _jobs[job_id].update(kwargs)


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YT_URL_RE = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?.*v=|shorts/|embed/)|youtu\.be/)"
    r"[\w\-]+"
)
_SP_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist)/[\w]+"
)

# Optional path to a Netscape-format cookies file for yt-dlp.
# Required for age-restricted content and 1080p+ on some YouTube videos.
_YT_COOKIE_FILE = os.environ.get("YT_COOKIE_FILE", "")


def _yt_common_opts() -> list:
    """Return extra yt-dlp options applied to every YouTube command.

    * ``--extractor-args youtube:player_client=all`` – instructs yt-dlp to
      probe every known YouTube player client (web, Android, iOS, TV …).
      Without this, YouTube's bot-detection often restricts the visible
      format list to a single 360p combined stream.
    * ``--cookies <path>`` – when *YT_COOKIE_FILE* is set and the file
      exists, pass it to yt-dlp so that age-restricted / member-only
      content and high-resolution streams (1080p+) are accessible.
    """
    opts = ["--extractor-args", "youtube:player_client=all"]
    if _YT_COOKIE_FILE and os.path.isfile(_YT_COOKIE_FILE):
        opts += ["--cookies", _YT_COOKIE_FILE]
    return opts


def _sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe in Content-Disposition filenames."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def _run_yt_dlp_info(url: str) -> dict:
    """Return metadata dict from yt-dlp for a given YouTube URL."""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
    ] + _yt_common_opts() + [url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "yt-dlp info failed")
    return json.loads(result.stdout)


def _cleanup_temp(path: str, delay: int = 120) -> None:
    """Delete a temp path after *delay* seconds (background thread)."""
    def _delete():
        time.sleep(delay)
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass
    threading.Thread(target=_delete, daemon=True).start()


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html", version=VERSION)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "version": VERSION})


# ---------------------------------------------------------------------------
# Routes — YouTube
# ---------------------------------------------------------------------------

@app.post("/api/youtube/info")
@limiter.limit("30 per minute")
def youtube_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing url"}), 400
    if not _YT_URL_RE.search(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    try:
        info = _run_yt_dlp_info(url)
    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp info timed out for %s", url)
        return jsonify({"error": "Request timed out"}), 504
    except ValueError as exc:
        logger.warning("yt-dlp info error: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected yt-dlp error: %s", exc)
        return jsonify({"error": "Failed to fetch video info"}), 500

    formats = []
    seen = set()
    for f in info.get("formats", []):
        height = f.get("height")
        vcodec = f.get("vcodec", "none")
        if vcodec != "none" and height and height not in seen:
            seen.add(height)
            formats.append({"label": f"{height}p", "value": f"{height}p"})
    # Sort descending and keep recognised heights only
    height_labels = {2160: "2160p (4K)", 1440: "1440p (2K)", 1080: "1080p", 720: "720p", 480: "480p", 360: "360p"}
    order = [2160, 1440, 1080, 720, 480, 360]
    formats = [
        {"label": height_labels[h], "value": f"{h}p", "group": "Video"}
        for h in order if h in seen
    ]
    formats.append({"label": "MP3 (Audio)", "value": "mp3", "group": "Audio"})
    formats.append({"label": "FLAC (Audio)", "value": "flac", "group": "Audio"})

    duration_s = info.get("duration", 0) or 0
    duration_fmt = f"{int(duration_s // 60)}:{int(duration_s % 60):02d}"

    return jsonify({
        "title": info.get("title", "Unknown"),
        "thumbnail": info.get("thumbnail", ""),
        "duration": duration_fmt,
        "uploader": info.get("uploader", ""),
        "formats": formats,
        "url": url,
    })


@app.get("/api/youtube/download")
@limiter.limit("10 per minute")
def youtube_download():
    """Legacy single-request download endpoint (kept for backward compatibility).

    New callers should use POST /api/youtube/start + GET /api/jobs/<id>/status
    + GET /api/jobs/<id>/download instead, which is proxy-friendly.
    """
    url = unquote((request.args.get("url") or "").strip())
    fmt = (request.args.get("format") or "720p").strip()

    if not url or not _YT_URL_RE.search(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400

    allowed_formats = {"360p", "480p", "720p", "1080p", "1440p", "2160p", "mp3", "flac"}
    if fmt not in allowed_formats:
        return jsonify({"error": "Invalid format"}), 400

    if fmt == "mp3":
        yt_format = "bestaudio[ext=m4a]/bestaudio/best"
        postprocess = [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-metadata",
            "--embed-thumbnail",
        ]
        mime = "audio/mpeg"
        ext = "mp3"
    elif fmt == "flac":
        yt_format = "bestaudio[ext=m4a]/bestaudio/best"
        postprocess = [
            "--extract-audio",
            "--audio-format", "flac",
            "--audio-quality", "0",
            "--embed-metadata",
            "--embed-thumbnail",
        ]
        mime = "audio/flac"
        ext = "flac"
    else:
        height = fmt.rstrip("p")
        yt_format = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        )
        postprocess = [
            "--merge-output-format", "mp4",
            "-S", "vcodec:h264,acodec:aac",
        ]
        mime = "video/mp4"
        ext = "mp4"

    # Resolve filename via yt-dlp --print
    try:
        title_result = subprocess.run(
            ["yt-dlp", "--print", "%(title)s", "--no-playlist"] + _yt_common_opts() + [url],
            capture_output=True, text=True, timeout=15,
        )
        raw_title = title_result.stdout.strip() or "download"
    except Exception:  # noqa: BLE001
        raw_title = "download"

    safe_title = _sanitize_filename(raw_title)
    filename = f"{safe_title}.{ext}"

    # Download to a temp file so that:
    #  • postprocessing (audio extract, mux) works reliably
    #  • we can set Content-Length, giving the browser an accurate progress bar
    #  • --concurrent-fragments speeds up segmented downloads significantly
    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")
    tmp_out = os.path.join(tmp_dir, f"download.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", yt_format,
        "--no-playlist",
        "--no-warnings",
        "--concurrent-fragments", "4",
        "-o", tmp_out,
    ] + _yt_common_opts() + postprocess + [url]

    logger.info("YT download: fmt=%s url=%s", fmt, url)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Download timed out"}), 504
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.error("yt-dlp error: %s", exc)
        return jsonify({"error": "Download failed"}), 500

    if proc.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.warning("yt-dlp stderr: %s", proc.stderr.decode(errors="replace"))
        return jsonify({"error": "Download failed"}), 500

    try:
        files = [
            f for f in os.listdir(tmp_dir)
            if os.path.isfile(os.path.join(tmp_dir, f)) and f.endswith(f".{ext}")
        ]
    except OSError:
        files = []

    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Download produced no output"}), 500

    fpath = os.path.join(tmp_dir, files[0])
    file_size = os.path.getsize(fpath)

    def generate():
        try:
            with open(fpath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream error (YT): %s", exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(file_size),
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(generate()),
        mimetype=mime,
        headers=headers,
    )


@app.post("/api/youtube/start")
@limiter.limit("10 per minute")
def youtube_start():
    """Start a YouTube download in a background thread.

    Returns a ``job_id`` immediately so the client is not blocked waiting for
    yt-dlp to finish.  The client should poll ``GET /api/jobs/<id>/status``
    and then navigate to ``GET /api/jobs/<id>/download`` when ready.
    """
    _reap_old_jobs()

    data = request.get_json(silent=True) or {}
    url = unquote((data.get("url") or "").strip())
    fmt = (data.get("format") or "720p").strip()

    if not url or not _YT_URL_RE.search(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400

    allowed_formats = {"360p", "480p", "720p", "1080p", "1440p", "2160p", "mp3", "flac"}
    if fmt not in allowed_formats:
        return jsonify({"error": "Invalid format"}), 400

    job_id = _make_job_id()
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "pending",
            "error": None,
            "tmp_dir": None,
            "fpath": None,
            "filename": None,
            "mime": None,
            "created": time.time(),
        }

    threading.Thread(
        target=_run_youtube_download,
        args=(job_id, url, fmt),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


def _run_youtube_download(job_id: str, url: str, fmt: str) -> None:
    """Background worker for YouTube downloads."""
    if fmt == "mp3":
        yt_format = "bestaudio[ext=m4a]/bestaudio/best"
        postprocess = [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-metadata",
            "--embed-thumbnail",
        ]
        mime = "audio/mpeg"
        ext = "mp3"
    elif fmt == "flac":
        yt_format = "bestaudio[ext=m4a]/bestaudio/best"
        postprocess = [
            "--extract-audio",
            "--audio-format", "flac",
            "--audio-quality", "0",
            "--embed-metadata",
            "--embed-thumbnail",
        ]
        mime = "audio/flac"
        ext = "flac"
    else:
        height = fmt.rstrip("p")
        yt_format = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        )
        postprocess = [
            "--merge-output-format", "mp4",
            "-S", "vcodec:h264,acodec:aac",
        ]
        mime = "video/mp4"
        ext = "mp4"

    # Resolve filename
    try:
        title_result = subprocess.run(
            ["yt-dlp", "--print", "%(title)s", "--no-playlist"] + _yt_common_opts() + [url],
            capture_output=True, text=True, timeout=15,
        )
        raw_title = title_result.stdout.strip() or "download"
    except Exception:  # noqa: BLE001
        raw_title = "download"

    safe_title = _sanitize_filename(raw_title)
    filename = f"{safe_title}.{ext}"

    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")
    _set_job(job_id, tmp_dir=tmp_dir)

    tmp_out = os.path.join(tmp_dir, "download.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", yt_format,
        "--no-playlist",
        "--no-warnings",
        "--concurrent-fragments", "4",
        "-o", tmp_out,
    ] + _yt_common_opts() + postprocess + [url]

    logger.info("YT job %s: fmt=%s url=%s", job_id, fmt, url)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _set_job(job_id, status="error", error="Download timed out", tmp_dir=None)
        return
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.error("yt-dlp job %s error: %s", job_id, exc)
        _set_job(job_id, status="error", error="Download failed", tmp_dir=None)
        return

    if proc.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.warning("yt-dlp job %s stderr: %s", job_id, proc.stderr.decode(errors="replace"))
        _set_job(job_id, status="error", error="Download failed", tmp_dir=None)
        return

    try:
        files = [
            f for f in os.listdir(tmp_dir)
            if os.path.isfile(os.path.join(tmp_dir, f)) and f.endswith(f".{ext}")
        ]
    except OSError:
        files = []

    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _set_job(job_id, status="error", error="Download produced no output", tmp_dir=None)
        return

    fpath = os.path.join(tmp_dir, files[0])
    _set_job(job_id, status="ready", fpath=fpath, filename=filename, mime=mime)
    logger.info("YT job %s ready: %s", job_id, filename)


# ---------------------------------------------------------------------------
# Routes — Spotify
# ---------------------------------------------------------------------------

def _spotify_type(url: str) -> str | None:
    m = re.search(r"open\.spotify\.com/(track|album|playlist)/", url)
    return m.group(1) if m else None


def _fetch_spotify_metadata(url: str) -> list:
    """Use spotdl save to retrieve basic track metadata and return a list of track dicts."""
    cmd = [
        "spotdl",
        "save",
        url,
        "--save-file", "/dev/stdout",
        "--no-cache",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_spotdl_env())
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "spotdl metadata failed")
    # spotdl save emits JSON lines
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise ValueError("No metadata returned by spotdl")
    tracks = [json.loads(line) for line in lines]
    return tracks


@app.post("/api/spotify/info")
@limiter.limit("20 per minute")
def spotify_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing url"}), 400
    if not _SP_URL_RE.match(url):
        return jsonify({"error": "Invalid Spotify URL"}), 400

    sp_type = _spotify_type(url)

    try:
        tracks = _fetch_spotify_metadata(url)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out"}), 504
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.error("spotdl metadata error: %s", exc)
        return jsonify({"error": "Failed to fetch Spotify metadata"}), 500

    if not tracks:
        return jsonify({"error": "No tracks found"}), 404

    first = tracks[0]
    return jsonify({
        "type": sp_type,
        "name": first.get("name", "Unknown"),
        "artist": ", ".join(first.get("artists", [])) if first.get("artists") else first.get("artist", ""),
        "album": first.get("album_name", first.get("album", "")),
        "thumbnail": first.get("cover_url", first.get("album_cover", "")),
        "track_count": len(tracks),
        "tracks": [
            {
                "name": t.get("name", ""),
                "artist": ", ".join(t.get("artists", [])) if t.get("artists") else t.get("artist", ""),
            }
            for t in tracks[:5]
        ],
        "url": url,
    })


@app.get("/api/spotify/download")
@limiter.limit("5 per minute")
def spotify_download():
    """Legacy single-request Spotify download endpoint (kept for backward compatibility).

    New callers should use POST /api/spotify/start instead.
    """
    url = unquote((request.args.get("url") or "").strip())
    if not url or not _SP_URL_RE.match(url):
        return jsonify({"error": "Invalid Spotify URL"}), 400

    fmt = (request.args.get("format") or "mp3").strip()
    if fmt not in ("mp3", "flac"):
        return jsonify({"error": "Invalid format"}), 400

    sp_type = _spotify_type(url)
    is_collection = sp_type in ("album", "playlist")

    logger.info("Spotify download: type=%s fmt=%s url=%s", sp_type, fmt, url)

    if is_collection:
        return _stream_spotify_zip(url, sp_type, fmt)
    else:
        return _stream_spotify_track(url, fmt)


@app.post("/api/spotify/start")
@limiter.limit("5 per minute")
def spotify_start():
    """Start a Spotify download in a background thread.

    Returns a ``job_id`` immediately so the client is not blocked waiting for
    spotdl to finish.  The client should poll ``GET /api/jobs/<id>/status``
    and then navigate to ``GET /api/jobs/<id>/download`` when ready.
    """
    _reap_old_jobs()

    data = request.get_json(silent=True) or {}
    url = unquote((data.get("url") or "").strip())
    if not url or not _SP_URL_RE.match(url):
        return jsonify({"error": "Invalid Spotify URL"}), 400

    fmt = (data.get("format") or "mp3").strip()
    if fmt not in ("mp3", "flac"):
        return jsonify({"error": "Invalid format"}), 400

    sp_type = _spotify_type(url)

    job_id = _make_job_id()
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "pending",
            "error": None,
            "tmp_dir": None,
            "fpath": None,
            "filename": None,
            "mime": None,
            "created": time.time(),
        }

    threading.Thread(
        target=_run_spotify_download,
        args=(job_id, url, sp_type, fmt),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


# ---------------------------------------------------------------------------
# Shared job endpoints
# ---------------------------------------------------------------------------

@app.get("/api/jobs/<job_id>/status")
@limiter.limit("120 per minute")
def job_status(job_id: str):
    """Return the current status of a background download job."""
    job = _get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"status": job["status"], "error": job.get("error")})


@app.get("/api/jobs/<job_id>/download")
def job_download(job_id: str):
    """Stream the completed file for a finished job, then delete the job."""
    job = _get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] == "error":
        return jsonify({"error": job.get("error") or "Download failed"}), 500
    if job["status"] != "ready":
        return jsonify({"error": "Download is not ready yet"}), 202

    fpath = job["fpath"]
    filename = job["filename"]
    mime = job["mime"]
    tmp_dir = job["tmp_dir"]

    if not fpath:
        # Should not happen — indicates a logic error
        return jsonify({"error": "Internal error: fpath missing"}), 500

    # Remove job entry so it can't be downloaded twice accidentally
    with _jobs_lock:
        _jobs.pop(job_id, None)

    file_size = os.path.getsize(fpath)

    def generate():
        try:
            with open(fpath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        except GeneratorExit:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream error (job %s): %s", job_id, exc)
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(file_size),
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-store",
    }
    return Response(
        stream_with_context(generate()),
        mimetype=mime,
        headers=headers,
    )


def _run_spotify_download(job_id: str, url: str, sp_type: str, fmt: str) -> None:
    """Background worker for Spotify downloads (track or collection)."""
    is_collection = sp_type in ("album", "playlist")
    mime = "audio/flac" if fmt == "flac" else "audio/mpeg"

    if is_collection:
        tmp_dir = tempfile.mkdtemp(prefix="spotdl_")
    else:
        tmp_dir = tempfile.mkdtemp(prefix="spotdl_track_")

    _set_job(job_id, tmp_dir=tmp_dir)

    cmd = [
        "spotdl",
        "download",
        url,
        "--output", os.path.join(tmp_dir, "{title}"),
        "--format", fmt,
        "--no-cache",
    ]

    logger.info("Spotify job %s: type=%s fmt=%s url=%s", job_id, sp_type, fmt, url)

    timeout = 600 if is_collection else 300
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, env=_spotdl_env())
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _set_job(job_id, status="error", error="Download timed out", tmp_dir=None)
        return

    if proc.returncode != 0:
        logger.warning("spotdl job %s stderr: %s", job_id, proc.stderr.decode(errors="replace"))
        if not is_collection:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _set_job(job_id, status="error", error="Track download failed", tmp_dir=None)
            return
        # For collections spotdl may still have partial results — check below.

    try:
        audio_files = [f for f in os.listdir(tmp_dir) if f.endswith(f".{fmt}")]
    except OSError:
        audio_files = []

    if not audio_files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _set_job(job_id, status="error", error="No tracks were downloaded", tmp_dir=None)
        return

    if is_collection:
        # Build a real ZIP file so we have a known Content-Length
        zip_name = f"{sp_type}_download.zip"
        zip_path = os.path.join(tmp_dir, zip_name)
        with _zipfile.ZipFile(zip_path, "w", _zipfile.ZIP_DEFLATED) as zf:
            for fname in audio_files:
                zf.write(os.path.join(tmp_dir, fname), arcname=fname)
        _set_job(job_id, status="ready", fpath=zip_path, filename=zip_name, mime="application/zip")
        logger.info("Spotify job %s ready (ZIP): %s", job_id, zip_name)
    else:
        fpath = os.path.join(tmp_dir, audio_files[0])
        filename = _sanitize_filename(audio_files[0])
        _set_job(job_id, status="ready", fpath=fpath, filename=filename, mime=mime)
        logger.info("Spotify job %s ready: %s", job_id, filename)


def _stream_spotify_track(url: str, fmt: str = "mp3") -> Response:
    """Download a single Spotify track to a temp file and stream it to the browser."""
    mime = "audio/flac" if fmt == "flac" else "audio/mpeg"

    tmp_dir = tempfile.mkdtemp(prefix="spotdl_track_")
    cmd = [
        "spotdl",
        "download",
        url,
        "--output", os.path.join(tmp_dir, "{title}"),
        "--format", fmt,
        "--no-cache",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300, env=_spotdl_env())
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Download timed out"}), 504

    if proc.returncode != 0:
        logger.warning("spotdl track stderr: %s", proc.stderr.decode(errors="replace"))
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Track download failed"}), 500

    try:
        files = [f for f in os.listdir(tmp_dir) if f.endswith(f".{fmt}")]
    except OSError:
        files = []

    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Track download failed"}), 500

    fpath = os.path.join(tmp_dir, files[0])
    filename = _sanitize_filename(files[0])
    file_size = os.path.getsize(fpath)

    def generate():
        try:
            with open(fpath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        except GeneratorExit:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream error (Spotify track): %s", exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(file_size),
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(generate()),
        mimetype=mime,
        headers=headers,
    )


def _stream_spotify_zip(url: str, sp_type: str, fmt: str = "mp3") -> Response:
    """Download a Spotify album/playlist and stream it as a ZIP to the browser."""
    tmp_dir = tempfile.mkdtemp(prefix="spotdl_")

    cmd = [
        "spotdl",
        "download",
        url,
        "--output", os.path.join(tmp_dir, "{title}"),
        "--format", fmt,
        "--no-cache",
    ]

    # Run spotdl synchronously (collection may take a while)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,
            env=_spotdl_env(),
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Download timed out"}), 504

    if proc.returncode != 0:
        logger.warning("spotdl stderr: %s", proc.stderr.decode(errors="replace"))
        # spotdl may still have downloaded *some* tracks for collections,
        # so we only abort when zero files were produced (checked below).

    # Stream the resulting files as a ZIP
    zs = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_DEFLATED)
    files_added = 0
    for fname in os.listdir(tmp_dir):
        if fname.endswith(f".{fmt}"):
            fpath = os.path.join(tmp_dir, fname)
            zs.write(fpath, arcname=fname)
            files_added += 1

    if files_added == 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "No tracks were downloaded"}), 500

    zip_name = f"{sp_type}_download.zip"

    def generate():
        try:
            yield from zs
        finally:
            # Clean up temp dir after streaming completes or is aborted
            shutil.rmtree(tmp_dir, ignore_errors=True)

    headers = {
        "Content-Disposition": f'attachment; filename="{zip_name}"',
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(generate()),
        mimetype="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(HTTPException)
def http_exception(e):
    return jsonify({"error": e.description}), e.code


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Rate limit exceeded. Please slow down."}), 429


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
