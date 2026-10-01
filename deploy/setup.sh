#!/usr/bin/env bash
# Pehli baar, VPS pe root se: BOT_TOKEN=xxx bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BOT_TOKEN:?BOT_TOKEN=xxx bash deploy/setup.sh ke saath chalao}"
dnf install -y python3 python3-pip git
mkdir -p /opt/tgbot
cp bot.py post.txt config.json /opt/tgbot/
python3 -m venv /opt/tgbot/venv
/opt/tgbot/venv/bin/pip install -r requirements.txt
umask 077
printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN" > /etc/tgbot.env
cp deploy/tgbot.service /etc/systemd/system/tgbot.service
systemctl daemon-reload
systemctl enable tgbot
systemctl restart tgbot
sleep 2
systemctl status tgbot --no-pager
journalctl -u tgbot -n 10 --no-pager
