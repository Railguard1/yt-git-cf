import os
import re
import json
import time
import base64
import subprocess
import requests
from urllib.parse import quote

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

MODE = os.environ.get("MODE", "download")
URL = os.environ["VIDEO_URL"]
CHAT_ID = os.environ["CHAT_ID"]
FORMAT = os.environ.get("FORMAT", "720")


def send_message(text, reply_markup=None):
    payload = {"chat_id": CHAT_ID, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{API}/sendMessage", json=payload)


def send_photo(photo_url, caption, reply_markup=None):
    payload = {"chat_id": CHAT_ID, "photo": photo_url, "caption": caption}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = requests.post(f"{API}/sendPhoto", json=payload)
    if not resp.ok:
        # fall back to a plain text message if the thumbnail fails to send
        send_message(caption, reply_markup)


def setup_cookies():
    b64 = os.environ.get("YTDLP_COOKIES_B64")
    if not b64:
        print("YTDLP_COOKIES_B64 secret is empty or not set")
        return None
    with open("cookies.txt", "wb") as f:
        f.write(base64.b64decode(b64))
    size = os.path.getsize("cookies.txt")
    with open("cookies.txt", "r", errors="ignore") as f:
        first_line = f.readline().strip()
    print(f"cookies.txt written: {size} bytes, first line: {first_line!r}")
    if size == 0:
        return None
    return "cookies.txt"


def client_args(cookies_file):
    if cookies_file:
        args = ["--cookies", cookies_file, "--extractor-args", "youtube:player_client=web,mweb,tv"]
    else:
        args = ["--extractor-args", "youtube:player_client=android,ios,tv"]
    print(f"client_args: {args}")
    return args


def list_formats(url, cookies_file):
    cmd = ["yt-dlp", "-v", "-J", "--no-warnings", "--no-playlist"] + client_args(cookies_file) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("---- STDERR (full) ----")
    print(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    info = json.loads(result.stdout)
    video_id = info.get("id")
    title = info.get("title", "ویدیو")
    thumbnail = info.get("thumbnail")

    heights = sorted({f.get("height") for f in info.get("formats", []) if f.get("height")}, reverse=True)
    max_h = heights[0] if heights else None
    tiers = [h for h in [1080, 720, 480, 360, 240] if max_h and h <= max_h]
    if not tiers and max_h:
        tiers = [max_h]

    buttons = [[{"text": f"{h}p", "callback_data": f"{video_id}|{h}"}] for h in tiers]

    has_audio = any(f.get("vcodec") == "none" for f in info.get("formats", []))
    if has_audio:
        buttons.append([{"text": "فقط صدا 🎵", "callback_data": f"{video_id}|audio"}])

    if not buttons:
        send_message("هیچ فرمت قابل دانلودی برای این ویدیو پیدا نشد.")
        return

    caption = f"«{title}»\nکیفیت مورد نظر رو انتخاب کن:"
    reply_markup = {"inline_keyboard": buttons}

    if thumbnail:
        send_photo(thumbnail, caption[:1024], reply_markup)
    else:
        send_message(caption, reply_markup)


def build_selector(fmt):
    if fmt == "audio":
        return "bestaudio/best"
    return f"bv*[height<={fmt}]+ba/b[height<={fmt}]"


def sanitize_for_url(filename):
    # keep the real filename for the local file / gh upload, just avoid
    # spaces so the constructed download link stays clean
    return filename.replace(" ", "_")


def download_video(url, cookies_file, fmt):
    before = set(os.listdir("."))
    cmd = ["yt-dlp", "-f", build_selector(fmt), "--no-playlist", "-o", "%(title)s.%(ext)s"]
    if fmt != "audio":
        cmd += ["--merge-output-format", "mp4"]
    cmd += client_args(cookies_file)
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout[-2000:])
    print(result.stderr[-2000:])
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    after = set(os.listdir("."))
    new_files = [
        f for f in (after - before)
        if not f.endswith((".part", ".ytdl", ".tmp")) and f != "cookies.txt"
    ]
    if not new_files:
        raise FileNotFoundError("downloaded file not found")
    return new_files[0]


def upload_to_release(file_path, tag):
    clean_name = sanitize_for_url(file_path)
    if clean_name != file_path:
        os.rename(file_path, clean_name)
        file_path = clean_name

    subprocess.run(
        ["gh", "release", "create", tag, file_path, "--title", tag, "--notes", "auto upload"],
        check=True,
    )
    return f"https://github.com/{REPO}/releases/download/{tag}/{quote(file_path)}"


def main():
    cookies_file = setup_cookies()

    if MODE == "list":
        try:
            list_formats(URL, cookies_file)
        except Exception as e:
            send_message(f"خطا در دریافت لیست فرمت‌ها: {e}")
        return

    try:
        file_path = download_video(URL, cookies_file, FORMAT)
        tag = f"vid-{int(time.time())}"
        link = upload_to_release(file_path, tag)
        send_message(f"دانلود شد ✅\n{link}")
        os.remove(file_path)
    except Exception as e:
        send_message(f"خطا در دانلود: {e}")


if __name__ == "__main__":
    main()
