#!/bin/bash
# =============================================================================
# RAMP Watchdog Installation Script — Run on production server as root
# =============================================================================
set -euo pipefail

echo "=== RAMP Watchdog & Backup Installation ==="

# 1. Create directories
echo "Creating directories..."
mkdir -p /opt/ramp
mkdir -p /opt/ramp/backups
mkdir -p /var/lib/ramp-watchdog
mkdir -p /var/log

# 2. Copy scripts
echo "Installing scripts..."
cp /app/watchdog/ramp_watchdog.sh /opt/ramp/ramp_watchdog.sh
cp /app/watchdog/pg_backup.sh /opt/ramp/pg_backup.sh
chmod +x /opt/ramp/ramp_watchdog.sh
chmod +x /opt/ramp/pg_backup.sh

# 3. Create env file for Telegram (if not exists)
if [ ! -f /opt/ramp/watchdog.env ]; then
    echo "Creating watchdog.env template..."
    cat > /opt/ramp/watchdog.env << 'EOF'
# Telegram Bot Token (create via @BotFather)
TG_BOT_TOKEN=""
# Telegram Chat ID (your personal or group chat)
TG_CHAT_ID=""
EOF
    echo "  → Edit /opt/ramp/watchdog.env with your Telegram credentials"
fi

# 4. Install systemd units
echo "Installing systemd units..."
cp /app/watchdog/systemd/ramp-watchdog.service /etc/systemd/system/
cp /app/watchdog/systemd/ramp-watchdog.timer /etc/systemd/system/
cp /app/watchdog/systemd/ramp-backup.service /etc/systemd/system/
cp /app/watchdog/systemd/ramp-backup.timer /etc/systemd/system/

# 5. Reload and enable
echo "Enabling timers..."
systemctl daemon-reload
systemctl enable --now ramp-watchdog.timer
systemctl enable --now ramp-backup.timer

# 6. Verify
echo ""
echo "=== Status ==="
echo "Watchdog timer:"
systemctl status ramp-watchdog.timer --no-pager || true
echo ""
echo "Backup timer:"
systemctl status ramp-backup.timer --no-pager || true
echo ""

# 7. Run initial check
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
echo "  2. Test: systemctl start ramp-watchdog.service"
echo "  3. View logs: journalctl -u ramp-watchdog.service"
echo "  4. Backup test: systemctl start ramp-backup.service"
echo "  5. View backup log: cat /var/log/ramp-backup.log"
