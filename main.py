import io
import os
import re
import tempfile
import shutil

from flask import Flask, request, jsonify, send_file, render_template, after_this_request
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
# CORS fully open: Android APK makes cross-origin requests to this server.
# supports_credentials is intentionally omitted — it is incompatible with a
# wildcard origin and is not needed here.
CORS(app, origins="*")


# ─────────────────────────────── helpers ───────────────────────────────

def fmt_size(byte_count):
    """Return a human-readable file-size string like '~42 MB'."""
    if not byte_count:
        return "~? MB"
    mb = byte_count / (1024 * 1024)
    if mb >= 1000:
        return f"~{mb / 1024:.1f} GB"
    return f"~{mb:.0f} MB"


def fmt_duration(seconds):
    """Return duration as M:SS or H:MM:SS."""
    if not seconds:
        return "0:00"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def best_size(formats, height_min=None, height_max=None, audio_only=False):
    """Scan yt-dlp format list and return a byte-count estimate."""
    candidates = []
    for f in formats:
        if audio_only:
            if f.get("vcodec", "none") not in (None, "none", ""):
                continue
            if f.get("acodec", "none") in (None, "none", ""):
                continue
        else:
            if f.get("vcodec", "none") in (None, "none", ""):
                continue
            h = f.get("height") or 0
            if height_min and h < height_min:
                continue
            if height_max and h > height_max:
                continue
        sz = f.get("filesize") or f.get("filesize_approx")
        if sz:
            candidates.append(sz)
    return max(candidates) if candidates else None


# ─────────────────────────────── routes ────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info")
def get_info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    ydl_opts = {
        "cookiefile": "cookies.txt",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        # Strip the verbose yt-dlp prefix
        if "ERROR:" in msg:
            msg = msg.split("ERROR:")[-1].strip()
        return jsonify({"error": msg}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    formats = info.get("formats", [])

    # Size estimates
    sz_best  = best_size(formats, height_min=1080) or best_size(formats)
    sz_audio = best_size(formats, audio_only=True)
    sz_fast  = best_size(formats, height_min=480, height_max=720) or best_size(formats, height_max=720)

    return jsonify({
        "title":        info.get("title", "Unknown Title"),
        "channel":      info.get("uploader") or info.get("channel", "Unknown Channel"),
        "duration":     info.get("duration", 0),
        "duration_str": fmt_duration(info.get("duration", 0)),
        "thumbnail":    info.get("thumbnail", ""),
        "sizes": {
            "best":  fmt_size(sz_best),
            "audio": fmt_size(sz_audio),
            "fast":  fmt_size(sz_fast),
        },
    })


@app.route("/api/download")
def download():
    url  = request.args.get("url", "").strip()
    fmt  = request.args.get("format", "best")   # best | audio | fast

    if not url:
        return jsonify({"error": "URL is required"}), 400

    tmpdir = tempfile.mkdtemp(prefix="anydown_")

    if fmt == "audio":
        format_spec = "bestaudio[ext=m4a]/bestaudio/best"
        postprocessors = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }]
    elif fmt == "fast":
        format_spec = (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=720]+bestaudio"
            "/best[height<=720]/best"
        )
        postprocessors = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
    else:   # best
        format_spec = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo+bestaudio/best"
        )
        postprocessors = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]

    ydl_opts = {
        "cookiefile": "cookies.txt",
        "format": format_spec,
        "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = str(e)
        if "ERROR:" in msg:
            msg = msg.split("ERROR:")[-1].strip()
        return jsonify({"error": msg}), 422
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500

    # Find the output file (there should be exactly one)
    files = os.listdir(tmpdir)
    if not files:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": "Download failed — output file not found"}), 500

    filepath = os.path.join(tmpdir, files[0])
    ext = os.path.splitext(files[0])[1].lstrip(".").lower()

    # Build a safe download filename
    title     = info.get("title", "download")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", title)[:100].strip()
    dl_name   = f"{safe_name}.{ext}"

    mimetype = "audio/mpeg" if ext == "mp3" else "video/mp4"

    # Read the entire file into memory, then immediately delete the temp dir.
    # This avoids the race condition where a background cleanup thread deletes
    # the file before Flask finishes streaming it to a slow client.
    try:
        with open(filepath, "rb") as fh:
            file_bytes = io.BytesIO(fh.read())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    file_bytes.seek(0)
    return send_file(
        file_bytes,
        mimetype=mimetype,
        as_attachment=True,
        download_name=dl_name,
    )


# ───────────────────────────── entry point ─────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
            "best":  fmt_size(sz_best),
            "audio": fmt_size(sz_audio),
            "fast":  fmt_size(sz_fast),
        },
    })


@app.route("/api/download")
def download():
    url  = request.args.get("url", "").strip()
    fmt  = request.args.get("format", "best")   # best | audio | fast

    if not url:
        return jsonify({"error": "URL is required"}), 400

    tmpdir = tempfile.mkdtemp(prefix="anydown_")

    if fmt == "audio":
        format_spec = "bestaudio[ext=m4a]/bestaudio/best"
        postprocessors = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }]
    elif fmt == "fast":
        format_spec = (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=720]+bestaudio"
            "/best[height<=720]/best"
        )
        postprocessors = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
    else:   # best
        format_spec = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo+bestaudio/best"
        )
        postprocessors = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]

    ydl_opts = {
        "format": format_spec,
        "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = str(e)
        if "ERROR:" in msg:
            msg = msg.split("ERROR:")[-1].strip()
        return jsonify({"error": msg}), 422
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500

    # Find the output file (there should be exactly one)
    files = os.listdir(tmpdir)
    if not files:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": "Download failed — output file not found"}), 500

    filepath = os.path.join(tmpdir, files[0])
    ext = os.path.splitext(files[0])[1].lstrip(".").lower()

    # Build a safe download filename
    title     = info.get("title", "download")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", title)[:100].strip()
    dl_name   = f"{safe_name}.{ext}"

    mimetype = "audio/mpeg" if ext == "mp3" else "video/mp4"

    # Read the entire file into memory, then immediately delete the temp dir.
    # This avoids the race condition where a background cleanup thread deletes
    # the file before Flask finishes streaming it to a slow client.
    try:
        with open(filepath, "rb") as fh:
            file_bytes = io.BytesIO(fh.read())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    file_bytes.seek(0)
    return send_file(
        file_bytes,
        mimetype=mimetype,
        as_attachment=True,
        download_name=dl_name,
    )


# ───────────────────────────── entry point ─────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
