"""
Media Downloader — Flask backend
Streams YouTube and Spotify downloads directly to the browser (no disk writes).
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
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(24).hex())

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

VERSION = "2.0.0"

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
        url,
    ]
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
    url = unquote((request.args.get("url") or "").strip())
    fmt = (request.args.get("format") or "720p").strip()

    if not url or not _YT_URL_RE.search(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400

    allowed_formats = {"360p", "480p", "720p", "1080p", "1440p", "2160p", "mp3", "flac"}
    if fmt not in allowed_formats:
        return jsonify({"error": "Invalid format"}), 400

    if fmt == "mp3":
        yt_format = "bestaudio/best"
        postprocess = [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
        ]
        mime = "audio/mpeg"
        ext = "mp3"
    elif fmt == "flac":
        yt_format = "bestaudio/best"
        postprocess = [
            "--extract-audio",
            "--audio-format", "flac",
            "--audio-quality", "0",
        ]
        mime = "audio/flac"
        ext = "flac"
    else:
        height = fmt.rstrip("p")
        yt_format = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        )
        postprocess = ["--merge-output-format", "mp4"]
        mime = "video/mp4"
        ext = "mp4"

    # Resolve filename via yt-dlp --print
    try:
        title_result = subprocess.run(
            ["yt-dlp", "--print", "%(title)s", "--no-playlist", url],
            capture_output=True, text=True, timeout=15,
        )
        raw_title = title_result.stdout.strip() or "download"
    except Exception:  # noqa: BLE001
        raw_title = "download"

    safe_title = _sanitize_filename(raw_title)
    filename = f"{safe_title}.{ext}"

    cmd = [
        "yt-dlp",
        "-f", yt_format,
        "--no-playlist",
        "--no-warnings",
        "-o", "-",          # write to stdout
    ] + postprocess + [url]

    logger.info("YT download: fmt=%s url=%s", fmt, url)

    def generate():
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        except GeneratorExit:
            if proc and proc.poll() is None:
                proc.kill()
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream error (YT): %s", exc)
        finally:
            if proc:
                proc.stdout.close()
                proc.wait()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(generate()),
        mimetype=mime,
        headers=headers,
    )


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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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
        subprocess.run(cmd, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Download timed out"}), 504

    try:
        files = [f for f in os.listdir(tmp_dir) if f.endswith(f".{fmt}")]
    except OSError:
        files = []

    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Track download failed"}), 500

    fpath = os.path.join(tmp_dir, files[0])
    filename = _sanitize_filename(files[0])

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
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Download timed out"}), 504

    if proc.returncode != 0:
        logger.warning("spotdl stderr: %s", proc.stderr.decode(errors="replace"))

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
    app.run(host="0.0.0.0", port=8080, debug=False)
