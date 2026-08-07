import os
import json
import time
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

STATS_FILE = "stats.jsonl"
WEEK_SECONDS = 7 * 24 * 60 * 60
KEEP_SECONDS = 30 * 24 * 60 * 60  # prune anything older than 30 days


def send_message(text):
    requests.post(f"{API}/sendMessage", json={"chat_id": ADMIN_CHAT_ID, "text": text})


def main():
    if not os.path.exists(STATS_FILE):
        send_message("گزارش هفتگی: هیچ دانلودی این هفته ثبت نشده (فایل آمار هنوز وجود نداره).")
        return

    entries = []
    with open(STATS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    now = time.time()
    week_entries = [e for e in entries if now - e.get("ts", 0) <= WEEK_SECONDS]

    if not week_entries:
        send_message("گزارش هفتگی: این هفته هیچ دانلودی ثبت نشده.")
    else:
        total_count = len(week_entries)
        total_size = sum(e.get("size_mb", 0) for e in week_entries)

        by_platform = {}
        for e in week_entries:
            p = e.get("platform", "نامشخص")
            by_platform[p] = by_platform.get(p, 0) + 1

        platform_lines = "\n".join(f"  - {p}: {c}" for p, c in sorted(by_platform.items(), key=lambda x: -x[1]))
        size_gb = total_size / 1024

        lines = week_entries[-10:]
        recent = "\n".join(f"  • {e.get('title', '?')}" for e in reversed(lines))

        text = (
            f"📊 گزارش هفتگی\n\n"
            f"تعداد دانلود: {total_count}\n"
            f"حجم کل: {size_gb:.2f} گیگابایت\n\n"
            f"بر اساس پلتفرم:\n{platform_lines}\n\n"
            f"آخرین موارد:\n{recent}"
        )
        send_message(text)

    # prune anything older than KEEP_SECONDS so the log file doesn't grow forever
    kept = [e for e in entries if now - e.get("ts", 0) <= KEEP_SECONDS]
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        for e in kept:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
