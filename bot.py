import os
import re
import json
import time
import math
import glob
import base64
import unicodedata
import subprocess
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

MODE = os.environ.get("MODE", "download")
URL = os.environ.get("VIDEO_URL", "")
CHAT_ID = os.environ["CHAT_ID"]
FORMAT = os.environ.get("FORMAT", "720")

STATUS_MESSAGE_ID = os.environ.get("STATUS_MESSAGE_ID") or None
RANGE_START = os.environ.get("RANGE_START") or None
RANGE_END = os.environ.get("RANGE_END") or None
LIST_ID = os.environ.get("LIST_ID") or None
RAW_CALLBACK_DATA = os.environ.get("RAW_CALLBACK_DATA") or None
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


def edit_message(message_id, text, reply_markup=None):
    if not message_id:
        return
    payload = {"chat_id": CHAT_ID, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{API}/editMessageText", json=payload)


def retry_keyboard():
    if not RAW_CALLBACK_DATA:
        return None
    return {"inline_keyboard": [[{"text": "🔄 دوباره امتحان کن", "callback_data": RAW_CALLBACK_DATA}]]}


def setup_cookies():
    cookies = {}
    for platform, env_name, filename in [
        ("youtube", "YTDLP_COOKIES_B64", "cookies_youtube.txt"),
        ("instagram", "IG_COOKIES_B64", "cookies_instagram.txt"),
        ("twitter", "TWITTER_COOKIES_B64", "cookies_twitter.txt"),
    ]:
        b64 = os.environ.get(env_name)
        if not b64:
            print(f"[{platform}] {env_name} not set — running without cookies")
            cookies[platform] = None
            continue
        with open(filename, "wb") as f:
            f.write(base64.b64decode(b64))
        size = os.path.getsize(filename)
        with open(filename, "r", errors="ignore") as f:
            first_line = f.readline().strip()
        print(f"[{platform}] cookies file: {size} bytes, first line: {first_line!r}")
        cookies[platform] = filename if size > 0 else None
    return cookies


def platform_of(url):
    if "instagram.com" in url:
        return "instagram"
    if "twitter.com" in url or "x.com" in url:
        return "twitter"
    return "youtube"


def client_args(cookies, url):
    platform = platform_of(url)
    cookies_file = cookies.get(platform)
    if platform in ("instagram", "twitter"):
        args = ["--cookies", cookies_file] if cookies_file else []
    elif cookies_file:
        args = ["--cookies", cookies_file, "--extractor-args", "youtube:player_client=web,mweb,tv"]
    else:
        args = ["--extractor-args", "youtube:player_client=android,ios,tv"]
    print(f"[{platform}] using cookies={bool(cookies_file)} args={args}")
    return args


def is_playlist_url(url):
    return "playlist?list=" in url or ("list=" in url and "watch?v=" not in url)


def build_ref(url, video_id):
    """Builds the short token embedded in callback_data, from which the
    original URL can be reconstructed later (see worker.js)."""
    platform = platform_of(url)
    if platform == "instagram":
        m = re.search(r"instagram\.com/(p|reel|reels|tv)/([\w-]+)", url)
        if m:
            return f"IG:{m.group(1)}:{m.group(2)}"
        return f"IG:p:{video_id}"
    if platform == "twitter":
        return f"TW:{video_id}"
    return video_id  # youtube — unprefixed, unchanged


def list_formats(url, cookies):
    if is_playlist_url(url):
        list_playlist_formats(url, cookies)
        return

    cmd = ["yt-dlp", "-J", "--no-warnings", "--no-playlist"] + client_args(cookies, url) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stderr[-3000:])
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] or result.stdout[-800:])

    info = json.loads(result.stdout)
    video_id = info.get("id")
    ref = build_ref(url, video_id)
    title = info.get("title", "ویدیو")
    thumbnail = info.get("thumbnail")

    heights = sorted({f.get("height") for f in info.get("formats", []) if f.get("height")}, reverse=True)
    max_h = heights[0] if heights else None
    tiers = [h for h in [1080, 720, 480, 360, 240] if max_h and h <= max_h]
    if not tiers and max_h:
        tiers = [max_h]

    buttons = [[{"text": f"{h}p", "callback_data": f"{ref}|{h}"}] for h in tiers]

    has_audio = any(f.get("vcodec") == "none" for f in info.get("formats", []))
    if has_audio:
        buttons.append([{"text": "فقط صدا 🎵", "callback_data": f"{ref}|audio"}])

    if not buttons:
        formats = info.get("formats", [])
        if formats:
            # e.g. an Instagram photo post, or a single-format post with
            # no height metadata — offer a plain download button
            buttons = [[{"text": "دانلود 📥", "callback_data": f"{ref}|best"}]]
        else:
            send_message("این پست هیچ ویدیو یا فایل قابل‌دانلودی نداره (شاید فقط متن/عکسه، یا محتوای اصلی توی یه پست دیگه‌ست که این پست فقط بهش اشاره کرده).")
            return

    caption = f"«{title}»\nکیفیت مورد نظر رو انتخاب کن:"
    reply_markup = {"inline_keyboard": buttons}

    if thumbnail:
        send_photo(thumbnail, caption[:1024], reply_markup)
    else:
        send_message(caption, reply_markup)


def list_playlist_formats(url, cookies):
    cmd = ["yt-dlp", "-J", "--flat-playlist", "--no-warnings"] + client_args(cookies, url) + [url]
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

    display_count = min(count, 60)
    lines = [f"{i}. {e.get('title') or e.get('id')}" for i, e in enumerate(entries[:display_count], 1)]
    listing = "\n".join(lines)
    if count > display_count:
        listing += f"\n... و {count - display_count} مورد دیگر"

    send_message(f"«{title}» — {count} ویدیو:\n\n{listing}")
    send_message(
        f"از قسمت چند تا چند رو می‌خوای دانلود کنم؟ (مثلاً 1-10)\n"
        f"روی همین پیام ریپلای کن و بازه رو بنویس.\n\n"
        f"list_id:{list_id} total:{count}",
        {"force_reply": True},
    )


def playlist_range_quality(list_id, start, end):
    tiers = [1080, 720, 480, 360]
    buttons = [[{"text": f"{h}p", "callback_data": f"L:{list_id}:{start}:{end}|{h}"}] for h in tiers]
    buttons.append([{"text": "فقط صدا 🎵", "callback_data": f"L:{list_id}:{start}:{end}|audio"}])
    send_message(f"قسمت‌های {start} تا {end} — کیفیت رو انتخاب کن:", {"inline_keyboard": buttons})


def build_selector(fmt):
    if fmt == "audio":
        return "bestaudio/best"
    if fmt == "best":
        return "best"
    return f"bv*[height<={fmt}]+ba/b[height<={fmt}]"


def ascii_safe_name(filename):
    """Strip the filename down to plain ASCII letters/digits so it never
    trips up gh's upload syntax or GitHub's own asset-name rewriting."""
    name, ext = os.path.splitext(filename)
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_.")
    if not name:
        name = "video"
    if not name[0].isalnum():
        name = f"v_{name}"
    return f"{name}{ext}"


def download_video(url, cookies, fmt):
    """Downloads the video and returns (safe_filename, display_title)."""
    before = set(os.listdir("."))
    cmd = ["yt-dlp", "-f", build_selector(fmt), "--no-playlist", "-o", "%(title)s.%(ext)s"]
    if fmt not in ("audio", "best"):
        cmd += ["--merge-output-format", "mp4"]
    cmd += client_args(cookies, url)
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

    original_name = new_files[0]
    title = os.path.splitext(original_name)[0]
    safe_name = ascii_safe_name(original_name)
    if safe_name != original_name:
        os.rename(original_name, safe_name)
    return safe_name, title


def download_video_with_retry(url, cookies, fmt, retries=2, delay=5):
    last_err = None
    for attempt in range(retries):
        try:
            return download_video(url, cookies, fmt)
        except Exception as e:
            last_err = e
            print(f"download attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_err


def upload_to_release(file_path, tag):
    create = subprocess.run(
        ["gh", "release", "create", tag, file_path, "--title", tag, "--notes", "auto upload"],
        capture_output=True, text=True,
    )
    print("gh release create stdout:", create.stdout)
    print("gh release create stderr:", create.stderr)
    if create.returncode != 0:
        raise RuntimeError(f"gh release create failed: {create.stderr[-500:]}")

    # file_path is guaranteed ASCII-safe (see ascii_safe_name), so GitHub
    # will never rename it and we can build the link directly — no need
    # to round-trip through `gh release view`.
    return f"https://github.com/{REPO}/releases/download/{tag}/{file_path}"


GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024  # 2GiB (GitHub's hard limit)
TARGET_PART_SIZE = 1800 * 1024 * 1024  # leave some margin under the limit


def get_duration(file_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", file_path],
        capture_output=True, text=True,
    )
    print(f"ffprobe stdout={result.stdout!r} stderr={result.stderr!r} returncode={result.returncode}")
    duration = result.stdout.strip()
    if result.returncode != 0 or not duration:
        raise RuntimeError(f"ffprobe failed to read duration: {result.stderr[-500:] or 'no output'}")
    return float(duration)


def split_video(file_path):
    """Splits file_path into roughly equal parts (no re-encoding, just a
    stream copy) sized to fit under GitHub's asset limit, and returns the
    list of part file paths."""
    size = os.path.getsize(file_path)
    duration = get_duration(file_path)
    num_parts = max(2, -(-size // TARGET_PART_SIZE))  # ceil division
    part_duration = duration / num_parts

    base, ext = os.path.splitext(file_path)
    pattern = f"{base}_part%02d{ext}"
    cmd = [
        "ffmpeg", "-y", "-i", file_path, "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(int(part_duration) + 1),
        "-reset_timestamps", "1", pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stderr[-1500:])
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg split failed: {result.stderr[-500:]}")

    prefix = f"{os.path.basename(base)}_part"
    parts = sorted(f for f in os.listdir(os.path.dirname(file_path) or ".") if f.startswith(prefix) and f.endswith(ext))
    dirpath = os.path.dirname(file_path)
    return [os.path.join(dirpath, p) if dirpath else p for p in parts]


def split_and_upload(file_path, tag_prefix):
    parts = split_video(file_path)
    links = []
    for i, part in enumerate(parts, 1):
        tag = f"{tag_prefix}-p{i}"
        links.append(upload_to_release(part, tag))
        os.remove(part)
    return links


def log_stat(title, url, size_mb):
    try:
        entry = {
            "ts": int(time.time()),
            "title": title,
            "platform": platform_of(url),
            "size_mb": round(size_mb, 1),
        }
        with open("stats.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"failed to log stat: {e}")


def fetch_and_upload(url, cookies, fmt):
    """Downloads + uploads a single video at the requested quality
    (unchanged). If the resulting file is too big for GitHub's 2GB asset
    limit, splits it into parts (no quality loss, just a stream copy) and
    uploads each part instead. Returns (title, links, note)."""
    file_path, title = download_video_with_retry(url, cookies, fmt)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    tag = f"vid-{int(time.time())}-{os.getpid()}"

    try:
        link = upload_to_release(file_path, tag)
        os.remove(file_path)
        log_stat(title, url, size_mb)
        return title, [link], ""
    except Exception as e:
        if "must be less than" not in str(e):
            os.remove(file_path)
            raise
        print(f"file too large for a single asset, splitting: {e}")

    try:
        links = split_and_upload(file_path, tag)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
    log_stat(title, url, size_mb)
    note = f" (فایل به {len(links)} پارت تقسیم شد چون حجمش بیشتر از سقف ۲ گیگ گیت‌هاب بود)"
    return title, links, note


def format_links(title, links):
    if len(links) == 1:
        return f"{title}\n{links[0]}"
    parts_text = "\n".join(f"پارت {i}: {l}" for i, l in enumerate(links, 1))
    return f"{title}\n{parts_text}"


def download_and_send(url, cookies, fmt, status_message_id=None, label=None):
    title, links, note = fetch_and_upload(url, cookies, fmt)
    edit_message(status_message_id, f"{label + ' ' if label else ''}دانلود تمام شد ✅{note}")
    send_message(format_links(title, links))


def download_playlist(url, cookies, fmt, status_message_id=None, range_start=None, range_end=None):
    cmd = ["yt-dlp", "-J", "--flat-playlist", "--no-warnings"] + client_args(cookies, url) + [url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        edit_message(status_message_id, f"خطا در خواندن پلی‌لیست: {result.stderr[-500:]}")
        return

    info = json.loads(result.stdout)
    entries = [e for e in info.get("entries", []) if e.get("id")]
    if not entries:
        edit_message(status_message_id, "هیچ ویدیویی در این پلی‌لیست پیدا نشد.")
        return

    if range_start and range_end:
        try:
            s, e_ = int(range_start), int(range_end)
            entries = entries[max(s - 1, 0):e_]
        except ValueError:
            pass

    truncated = len(entries) > MAX_PLAYLIST_ITEMS
    if truncated:
        entries = entries[:MAX_PLAYLIST_ITEMS]

    done = 0
    for i, e in enumerate(entries, 1):
        edit_message(status_message_id, f"در حال دانلود ({i}/{len(entries)})... ⏳")
        video_url = f"https://www.youtube.com/watch?v={e['id']}"
        try:
            title, links, note = fetch_and_upload(video_url, cookies, fmt)
            send_message(f"✅ ({i}/{len(entries)}) {note}\n{format_links(title, links)}")
            done += 1
        except Exception as ex:
            item_retry = {"inline_keyboard": [[{"text": "🔄 دوباره امتحان کن", "callback_data": f"{e['id']}|{fmt}"}]]}
            send_message(f"❌ ({i}/{len(entries)}) خطا: {ex}", item_retry)
        time.sleep(3)

    edit_message(status_message_id, f"پایان: {done} از {len(entries)} ویدیو با موفقیت دانلود شد.{' (بازه محدود به ' + str(MAX_PLAYLIST_ITEMS) + ' ویدیو شد)' if truncated else ''} ✅")


def main():
    cookies = setup_cookies()

    if MODE == "list":
        try:
            list_formats(URL, cookies)
        except Exception as e:
            send_message(f"خطا در دریافت لیست فرمت‌ها: {e}")
        return

    if MODE == "playlist_range":
        playlist_range_quality(LIST_ID, RANGE_START, RANGE_END)
        return

    if is_playlist_url(URL):
        download_playlist(URL, cookies, FORMAT, STATUS_MESSAGE_ID, RANGE_START, RANGE_END)
        return

    try:
        download_and_send(URL, cookies, FORMAT, status_message_id=STATUS_MESSAGE_ID)
    except Exception as e:
        edit_message(STATUS_MESSAGE_ID, f"خطا در دانلود: {e}", retry_keyboard())
        if not STATUS_MESSAGE_ID:
            send_message(f"خطا در دانلود: {e}", retry_keyboard())


if __name__ == "__main__":
    main()
