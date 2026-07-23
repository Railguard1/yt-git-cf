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

STATUS_MESSAGE_ID = os.environ.get("STATUS_MESSAGE_ID") or None
MAX_PLAYLIST_ITEMS = 20


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
        send_message(caption, reply_markup)


def setup_cookies():
    b64 = os.environ.get("YTDLP_COOKIES_B64")
    if not b64:
        print("YTDLP_COOKIES_B64 secret is empty or not set")
        return None
    with open("cookies.txt", "wb") as f:
        f.write(base64.b64decode(b64))
    size = os.path.getsize("cookies.txt")
    if size == 0:
        return None
    return "cookies.txt"


def client_args(cookies_file):
    if cookies_file:
        return ["--cookies", cookies_file, "--extractor-args", "youtube:player_client=web,mweb,tv"]
    return ["--extractor-args", "youtube:player_client=android,ios,tv"]


def is_playlist_url(url):
    return "playlist?list=" in url or ("list=" in url and "watch?v=" not in url)


def list_formats(url, cookies_file):
    if is_playlist_url(url):
        list_playlist_formats(url, cookies_file)
        return

    cmd = ["yt-dlp", "-J", "--no-warnings", "--no-playlist"] + client_args(cookies_file) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stderr[-3000:])
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


def list_playlist_formats(url, cookies_file):
    cmd = ["yt-dlp", "-J", "--flat-playlist", "--no-warnings"] + client_args(cookies_file) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stderr[-3000:])
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    info = json.loads(result.stdout)
    entries = [e for e in info.get("entries", []) if e.get("id")]
    title = info.get("title", "پلی‌لیست")
    count = len(entries)

    match = re.search(r"[?&]list=([\w-]+)", url)
    list_id = match.group(1) if match else info.get("id")

    if count == 0 or not list_id:
        send_message("هیچ ویدیویی در این پلی‌لیست پیدا نشد.")
        return

    note = f" (فقط {MAX_PLAYLIST_ITEMS} تای اول دانلود می‌شه)" if count > MAX_PLAYLIST_ITEMS else ""
    tiers = [1080, 720, 480, 360]
    buttons = [[{"text": f"{h}p", "callback_data": f"L:{list_id}|{h}"}] for h in tiers]
    buttons.append([{"text": "فقط صدا 🎵", "callback_data": f"L:{list_id}|audio"}])

    send_message(
        f"«{title}»\n{count} ویدیو در این پلی‌لیست پیدا شد{note}.\n"
        f"یک کیفیت انتخاب کن، برای همه ویدیوها همون اعمال می‌شه:",
        {"inline_keyboard": buttons},
    )


def build_selector(fmt):
    if fmt == "audio":
        return "bestaudio/best"
    return f"bv*[height<={fmt}]+ba/b[height<={fmt}]"


def sanitize_for_url(filename):
    return filename.replace(" ", "_")


def download_video(url, cookies_file, fmt):
    before = set(os.listdir("."))
    cmd = ["yt-dlp", "-f", build_selector(fmt), "--no-playlist", "-o", "%(title)s.%(ext)s"]
    if fmt != "audio":
        cmd += ["--merge-output-format", "mp4"]
    cmd += client_args(cookies_file)
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout[-1500:])
    print(result.stderr[-1500:])
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    after = set(os.listdir("."))
    new_files = [
        f for f in (after - before)
        if not f.endswith((".part", ".ytdl", ".tmp")) and f != "cookies.txt"
    ]
    if not new_files:
        raise FileNotFoundError("downloaded file not found")

    file_path = new_files[0]
    clean_path = sanitize_for_url(file_path)
    if clean_path != file_path:
        os.rename(file_path, clean_path)
    return clean_path


def upload_to_release(file_path, tag):
    create = subprocess.run(
        ["gh", "release", "create", tag, file_path, "--title", tag, "--notes", "auto upload"],
        capture_output=True, text=True,
    )
    print("gh release create stdout:", create.stdout)
    print("gh release create stderr:", create.stderr)
    if create.returncode != 0:
        raise RuntimeError(f"gh release create failed: {create.stderr[-500:]}")

    for _ in range(5):
        view = subprocess.run(
            ["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[0].browser_download_url"],
            capture_output=True, text=True,
        )
        link = view.stdout.strip()
        if link and link != "null":
            return link
        time.sleep(2)

    return f"https://github.com/{REPO}/releases/download/{tag}/{quote(file_path)}"


def edit_message(message_id, text):
    if not message_id:
        return
    requests.post(f"{API}/editMessageText", json={
        "chat_id": CHAT_ID, "message_id": message_id, "text": text,
    })


def download_and_send(url, cookies_file, fmt, status_message_id=None, label=None):
    file_path = download_video(url, cookies_file, fmt)
    tag = f"vid-{int(time.time())}-{os.getpid()}"
    link = upload_to_release(file_path, tag)
    edit_message(status_message_id, f"{label + ' ' if label else ''}دانلود تمام شد ✅")
    send_message(link)
    os.remove(file_path)


def download_playlist(url, cookies_file, fmt, status_message_id=None):
    cmd = ["yt-dlp", "-J", "--flat-playlist", "--no-warnings"] + client_args(cookies_file) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        edit_message(status_message_id, f"خطا در خواندن پلی‌لیست: {result.stderr[-500:]}")
        return

    info = json.loads(result.stdout)
    entries = [e for e in info.get("entries", []) if e.get("id")]
    total = len(entries)
    if total == 0:
        edit_message(status_message_id, "هیچ ویدیویی در این پلی‌لیست پیدا نشد.")
        return

    if total > MAX_PLAYLIST_ITEMS:
        entries = entries[:MAX_PLAYLIST_ITEMS]

    done = 0
    for i, e in enumerate(entries, 1):
        edit_message(status_message_id, f"در حال دانلود ({i}/{len(entries)})... ⏳")
        video_url = f"https://www.youtube.com/watch?v={e['id']}"
        try:
            file_path = download_video(video_url, cookies_file, fmt)
            tag = f"vid-{int(time.time())}-{i}"
            link = upload_to_release(file_path, tag)
            send_message(f"✅ ({i}/{len(entries)}) {link}")
            os.remove(file_path)
            done += 1
        except Exception as ex:
            send_message(f"❌ ({i}/{len(entries)}) خطا: {ex}")

    edit_message(status_message_id, f"پایان پلی‌لیست: {done} از {len(entries)} ویدیو با موفقیت دانلود شد. ✅")


def main():
    cookies_file = setup_cookies()

    if MODE == "list":
        try:
            list_formats(URL, cookies_file)
        except Exception as e:
            send_message(f"خطا در دریافت لیست فرمت‌ها: {e}")
        return

    if is_playlist_url(URL):
        download_playlist(URL, cookies_file, FORMAT, STATUS_MESSAGE_ID)
        return

    try:
        download_and_send(URL, cookies_file, FORMAT, status_message_id=STATUS_MESSAGE_ID)
    except Exception as e:
        edit_message(STATUS_MESSAGE_ID, f"خطا در دانلود: {e}")
        if not STATUS_MESSAGE_ID:
            send_message(f"خطا در دانلود: {e}")


if __name__ == "__main__":
    main()
