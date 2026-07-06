# ANYDOWN

A YouTube video downloader with a Neo-Brutalist UI — download full video (MP4), audio only (MP3), or a fast 720p version using yt-dlp on the backend.

## Run & Operate

- `python main.py` — run the Flask server on port 8000 (managed by the "ANYDOWN Flask Server" workflow)
- The app is served at the root `/` in the Replit preview pane

## Stack

- **Backend**: Python 3.11 + Flask 3 + yt-dlp + ffmpeg
- **Frontend**: Vanilla HTML/JS/CSS (Neo-Brutalist dark theme, Space Grotesk + JetBrains Mono)
- **Mobile wrapper**: Capacitor 6 (Android APK via GitHub Actions)
- **CORS**: Fully open (`origins="*"`) — intentional, required for the Android APK

## Project Structure

```
main.py                         ← Flask server (entry point)
templates/index.html            ← Frontend served by Flask at /
requirements.txt                ← Python dependencies
www/index.html                  ← Static copy for Capacitor webDir
package.json                    ← Capacitor npm dependencies
capacitor.config.json           ← Capacitor Android configuration
.github/workflows/build.yml     ← GitHub Actions: builds & uploads debug APK
```

## API Endpoints

| Endpoint | Method | Params | Returns |
|---|---|---|---|
| `/api/info` | GET | `url` | `{title, channel, duration, duration_str, thumbnail, sizes:{best,audio,fast}}` |
| `/api/download` | GET | `url`, `format` (best\|audio\|fast) | Binary file stream (MP4 or MP3) |

## Download Formats

| Format key | Quality | Container | Notes |
|---|---|---|---|
| `best` | Up to 4K | MP4 | bestvideo+bestaudio merged |
| `audio` | 320 kbps | MP3 | bestaudio extracted via ffmpeg |
| `fast` | 720p | MP4 | smaller, faster to download |

## Android APK (Capacitor)

**Local setup:**
```bash
npm install
npm run build:www          # copies templates/index.html → www/
npm run cap:add:android    # first time only
npm run cap:sync           # syncs www/ into the Android project
```

**Configure the server URL** — the Android app needs to know where the Flask backend lives. Two ways:
1. Set `server.url` in `capacitor.config.json` to your deployed server URL
2. Edit `window.ANYDOWN_SERVER_URL` in `www/index.html`

**GitHub Actions** — push to `main` to trigger an automatic APK build:
- Add a repository secret `ANYDOWN_SERVER_URL` with your deployed server URL (optional — without it the APK is built but the backend URL defaults to the device origin)
- The finished `app-debug.apk` is uploaded as a workflow artifact and available to download from the Actions tab

## User Preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- `ffmpeg` must be installed for audio extraction and video merging (installed as a Nix system dependency)
- File size estimates in `/api/info` come from yt-dlp's `filesize`/`filesize_approx` fields — they can be `~? MB` when YouTube doesn't report sizes
- Downloaded files are read into memory before sending to avoid streaming/cleanup race conditions; very large files (>500 MB) may strain memory
- `npm ci` will fail if run without a `package-lock.json` — the CI workflow uses `npm install` instead
