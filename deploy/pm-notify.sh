#!/bin/sh
# pm-notify TEXT      send TEXT to the owner's Telegram chat
# pm-notify --failed  send the tail of the last pm-deploy run (pm-deploy-failed.service)
#
# A personal bot and chat, not the group bot of .claude/telegram-bot/. Without
# TG_TOKEN/TG_CHAT_ID it only prints, so the journal still has the text.
# Installed as a copy in /usr/local/bin, like pm-deploy.
set -u

if [ -z "${TG_TOKEN:-}" ] && [ -r /etc/pm-deploy.env ]; then
  . /etc/pm-deploy.env
fi

if [ "${1:-}" = --failed ]; then
  text="PM: автодеплой упал
$(journalctl -u pm-deploy.service -n 8 --no-pager -o cat)"
else
  text=${1:?usage: pm-notify TEXT | pm-notify --failed}
fi

echo "$text"
if [ -z "${TG_TOKEN:-}" ] || [ -z "${TG_CHAT_ID:-}" ]; then
  exit 0
fi
curl -fsS --max-time 10 -o /dev/null \
  "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT_ID}" \
  --data-urlencode "text=${text}"
