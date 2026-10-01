#!/usr/bin/env bash
# Repo update ke baad VPS pe: bash deploy/update.sh  (token /etc/tgbot.env me rehta hai)
set -euo pipefail
cd "$(dirname "$0")/.."
git pull origin ccr-19003435-b41522
cp bot.py post.txt config.json /opt/tgbot/
systemctl restart tgbot
sleep 2
journalctl -u tgbot -n 10 --no-pager
