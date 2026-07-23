name: Telegram YouTube Downloader

on:
  repository_dispatch:
    types: [yt_download]
  workflow_dispatch:
    inputs:
      url:
        description: "YouTube URL"
        required: true
      chat_id:
        description: "Telegram chat id"
        required: true

permissions:
  contents: write

jobs:
  download:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -U -r requirements.txt

      - name: Run bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          YTDLP_COOKIES_B64: ${{ secrets.YTDLP_COOKIES_B64 }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VIDEO_URL: ${{ github.event.client_payload.url || github.event.inputs.url }}
          CHAT_ID: ${{ github.event.client_payload.chat_id || github.event.inputs.chat_id }}
        run: python bot.py
