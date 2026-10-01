#!/usr/bin/env bash
# VPS (AlmaLinux) pe root se chalao: bash setup.sh
set -euo pipefail
dnf install -y python3 python3-pip git
mkdir -p /opt/tgbot
cp bot.py /opt/tgbot/bot.py
python3 -m venv /opt/tgbot/venv
/opt/tgbot/venv/bin/pip install -r requirements.txt
if [ ! -f /etc/tgbot.env ]; then
  cp deploy/tgbot.env.example /etc/tgbot.env
  chmod 600 /etc/tgbot.env
  echo "/etc/tgbot.env edit karo (BOT_TOKEN, URLs), phir: systemctl restart tgbot"
fi
cp deploy/tgbot.service /etc/systemd/system/tgbot.service
systemctl daemon-reload
systemctl enable --now tgbot
systemctl status tgbot --no-pager
