# Deployment to Oracle VM (manual SSH)

Target: Oracle Cloud Always Free ARM VM (Ubuntu), user `ubuntu`, project at `/opt/news-signal`.
The service runs the Phase 6 loop in shadow mode; the evaluation clock only counts
days collected by this service (see EVALUATION_PLAN.md).

## 1. Sync the bundle from Windows

From the project root (`D:\ox alpha test`) in PowerShell:

```powershell
tar -czf news-signal-bundle.tgz `
  news_signal scripts config models deploy `
  requirements-live.txt .env.example EVALUATION_PLAN.md `
  data/raw/calendar.csv data/raw/profiles.json
scp news-signal-bundle.tgz ubuntu@YOUR_VM_IP:/tmp/
```

`models/` must contain: `champion_xgb_4class.json`, `calibration.pkl`,
`alert_thresholds.json`, `severity_regressor.json`.
Do NOT sync `.env` itself through the tarball if you prefer typing secrets on the VM.
Do NOT sync `data/live/` - the VM keeps its own signal database.

## 2. On the VM

```bash
sudo mkdir -p /opt/news-signal
sudo chown ubuntu:ubuntu /opt/news-signal
tar -xzf /tmp/news-signal-bundle.tgz -C /opt/news-signal
cd /opt/news-signal

cp .env.example .env
nano .env            # fill FINNHUB_API_KEY, ALPACA_API_KEY_ID/SECRET (same keys as local)
chmod 600 .env

bash deploy/install_on_vm.sh
```

The installer creates a venv, installs `requirements-live.txt`, installs and starts
the systemd unit (`deploy/news-signal.service`). Torch CPU wheels support aarch64.

## 3. Verify it is alive

```bash
systemctl status news-signal
journalctl -u news-signal -n 50 --no-pager     # expect market-hours cycles or 'market closed'
sqlite3 /opt/news-signal/data/live/signals.db \
  'SELECT status,COUNT(*) FROM signals GROUP BY status;'
ls -la /opt/news-signal/data/live/
```

First cycle warms caches: pulls ~75 days of minute bars for all 24 tickers plus SPY
daily history (a few minutes of Alpaca calls at free-tier pacing). Subsequent cycles
are light (news poll + incremental bar refresh).

## 4. Operating notes

- Logs: `journalctl -u news-signal -f` (PYTHONUNBUFFERED=1 is set).
- Restart policy: `Restart=always`, 30s backoff; survives reboots via `enable --now`.
- Updates: re-sync changed files, then `sudo systemctl restart news-signal`.
  ANY model/threshold/config change resets the evaluation clock per plan Section 7.
- Weekly review: copy `data/live/signals.db` to your machine and run
  `python scripts/shadow_status.py --db path/to/signals.db`; append output to
  `outputs/shadow_reviews/`.
- Telegram push later: set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID in `.env` AND set
  `live.notify_enabled: true` in config.yaml; stays log-only until you flip both.
- Firewall: no inbound ports required; outbound HTTPS only.

## 5. Timezone/clock

VM should run UTC with chrony/systemd-timesync active (Ubuntu default). All pipeline
logic converts to America/New_York internally; nothing depends on VM local timezone.
