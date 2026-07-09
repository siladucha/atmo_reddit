#!/bin/bash
# =============================================================================
# RAMP Watchdog & Telegram Bot Installation Script — Run on production server as root
# =============================================================================
set -euo pipefail

echo "=== RAMP Watchdog & Backup & Telegram Bot Installation ==="

# 1. Create directories
echo "Creating directories..."
mkdir -p /opt/ramp
mkdir -p /opt/ramp/backups
mkdir -p /var/lib/ramp-watchdog
mkdir -p /var/lib/ramp-watchdog/component_state
mkdir -p /var/log

# 2. Copy scripts
echo "Installing scripts..."
cp /app/watchdog/ramp_watchdog.sh /opt/ramp/ramp_watchdog.sh
cp /app/watchdog/pg_backup.sh /opt/ramp/pg_backup.sh
cp /app/watchdog/telegram_bot.py /opt/ramp/telegram_bot.py
chmod +x /opt/ramp/ramp_watchdog.sh
chmod +x /opt/ramp/pg_backup.sh
chmod +x /opt/ramp/telegram_bot.py

# 3. Create env file for Telegram (if not exists)
if [ ! -f /opt/ramp/watchdog.env ]; then
    echo "Creating watchdog.env template..."
    cat > /opt/ramp/watchdog.env << 'EOF'
# Telegram Bot Token (create via @BotFather)
TG_BOT_TOKEN=""
# Telegram Chat ID (your personal or group chat — receives alerts + can send commands)
TG_CHAT_ID=""
# Additional authorized chat IDs (comma-separated, for /commands access)
TG_ALLOWED_IDS=""
EOF
    echo "  → Edit /opt/ramp/watchdog.env with your Telegram credentials"
fi

# 4. Install Python deps for telegram bot (if not present)
echo "Checking Python dependencies for Telegram bot..."
python3 -c "import httpx" 2>/dev/null || pip3 install httpx --quiet
echo "  → httpx: OK"

# 5. Install systemd units
echo "Installing systemd units..."
cp /app/watchdog/systemd/ramp-watchdog.service /etc/systemd/system/
cp /app/watchdog/systemd/ramp-watchdog.timer /etc/systemd/system/
cp /app/watchdog/systemd/ramp-backup.service /etc/systemd/system/
cp /app/watchdog/systemd/ramp-backup.timer /etc/systemd/system/
cp /app/watchdog/systemd/ramp-telegram-bot.service /etc/systemd/system/

# 6. Reload and enable
echo "Enabling timers + services..."
systemctl daemon-reload
systemctl enable --now ramp-watchdog.timer
systemctl enable --now ramp-backup.timer

# Enable telegram bot only if token is configured
if grep -q 'TG_BOT_TOKEN=""' /opt/ramp/watchdog.env 2>/dev/null; then
    echo "  ⚠️  Telegram bot NOT started (TG_BOT_TOKEN empty — configure first)"
else
    systemctl enable --now ramp-telegram-bot.service
    echo "  ✅ Telegram bot started"
fi

# 7. Verify
echo ""
echo "=== Status ==="
echo "Watchdog timer:"
systemctl status ramp-watchdog.timer --no-pager || true
echo ""
echo "Backup timer:"
systemctl status ramp-backup.timer --no-pager || true
echo ""
echo "Telegram bot:"
systemctl status ramp-telegram-bot.service --no-pager 2>/dev/null || echo "(not running — configure token first)"
echo ""

# 8. Run initial check
echo "=== Running initial watchdog check ==="
/opt/ramp/ramp_watchdog.sh || true
echo ""
echo "Log output:"
tail -5 /var/log/ramp-watchdog.log 2>/dev/null || echo "(no log yet)"
echo ""

echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/ramp/watchdog.env with Telegram bot token + chat ID"
echo "  2. Start bot: systemctl enable --now ramp-telegram-bot.service"
echo "  3. Test in Telegram: /status"
echo "  4. Test watchdog: systemctl start ramp-watchdog.service"
echo "  5. View logs: journalctl -u ramp-telegram-bot.service"
echo "  6. Backup test: systemctl start ramp-backup.service"
