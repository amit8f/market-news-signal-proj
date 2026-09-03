#!/usr/bin/env bash
# Run ON the Oracle VM after the project bundle has been extracted to /opt/news-signal
set -euo pipefail

APP_DIR=/opt/news-signal
SERVICE_NAME=news-signal

if [[ $EUID -eq 0 ]]; then echo "run as regular user with sudo rights (ubuntu), not root"; exit 1; fi

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: $APP_DIR/.env missing - copy .env.example and fill keys first"; exit 1
fi
chmod 600 .env

"$PY" 2>/dev/null || true
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip wheel
./.venv/bin/pip install -r requirements-live.txt

mkdir -p data/live data/raw/bars outputs/shadow_reviews

sudo cp deploy/news-signal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

sleep 5
systemctl --no-pager status "$SERVICE_NAME" || true
echo
echo "follow logs:      journalctl -u $SERVICE_NAME -f"
echo "recent logs:      journalctl -u $SERVICE_NAME -n 100 --no-pager"
echo "signal counts:    sqlite3 $APP_DIR/data/live/signals.db 'SELECT status,COUNT(*) FROM signals GROUP BY status;'"
