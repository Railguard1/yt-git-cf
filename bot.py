import os
import json
import time
import base64
import subprocess
import requests

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


def setup_cookies():
    b64 = os.environ.get("YTDLP_COOKIES_B64")
    if not b64:
        return None
    with open("cookies.txt", "wb") as f:
        f.write(base64.b64decode(b64))
    return "cookies.txt"


def client_args(cookies_file):
    if cookies_file:
        return ["--cookies", cookies_file, "--extractor-args", "youtube:player_client=web,mweb,tv"]
    return ["--extractor-args", "youtube:player_client=android,ios,tv"]


def list_formats(url, cookies_file):
    cmd = ["yt-dlp", "-J", "--no-warnings", "--no-playlist"] + client_args(cookies_file) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout[-2000:])
    print(result.stderr[-2000:])
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    info = json.loads(result.stdout)
    video_id = info.get("id")
    title = info.get("title", "ویدیو")

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

    send_message(f"«{title}»\nکیفیت مورد نظر رو انتخاب کن:", {"inline_keyboard": buttons})


def build_selector(fmt):
    if fmt == "audio":
        return "bestaudio/best"
    return f"bestvideo[height<={fmt}]+bestaudio/best[height<={fmt}]/best[height<={fmt}]"


def download_video(url, cookies_file, fmt):
    out_tmpl = "download.%(ext)s"
    cmd = ["yt-dlp", "-f", build_selector(fmt), "--no-playlist", "-o", out_tmpl]
    if fmt != "audio":
        cmd += ["--merge-output-format", "mp4"]
    cmd += client_args(cookies_file)
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout[-2000:])
    print(result.stderr[-2000:])
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    for f in os.listdir("."):
        if f.startswith("download."):
            return f
    raise FileNotFoundError("downloaded file not found")


def upload_to_release(file_path, tag):
    subprocess.run(
        ["gh", "release", "create", tag, file_path, "--title", tag, "--notes", "auto upload"],
        check=True,
    )
    filename = os.path.basename(file_path)
    return f"https://github.com/{REPO}/releases/download/{tag}/{filename}"


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
