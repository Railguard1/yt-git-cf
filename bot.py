import os
import time
import base64
import subprocess
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

URL = os.environ["VIDEO_URL"]
CHAT_ID = os.environ["CHAT_ID"]


def send_message(text):
    requests.post(f"{API}/sendMessage", json={"chat_id": CHAT_ID, "text": text})


def setup_cookies():
    b64 = os.environ.get("YTDLP_COOKIES_B64")
    if not b64:
        return None
    with open("cookies.txt", "wb") as f:
        f.write(base64.b64decode(b64))
    return "cookies.txt"


def download_video(url, cookies_file):
    out_tmpl = "download.%(ext)s"
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[filesize<1800M]+bestaudio/best[filesize<1800M]/best",
        "--merge-output-format", "mp4",
        "--extractor-args", "youtube:player_client=android,ios",
        "--no-playlist",
        "-o", out_tmpl,
        url,
    ]
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
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
    try:
        file_path = download_video(URL, cookies_file)
        tag = f"vid-{int(time.time())}"
        link = upload_to_release(file_path, tag)
        send_message(f"دانلود شد ✅\n{link}")
        os.remove(file_path)
    except Exception as e:
        send_message(f"خطا در دانلود: {e}")


if __name__ == "__main__":
    main()
