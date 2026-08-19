#!/bin/bash
# ==============================================================================
# install.sh - Wi-Fi自動復旧 & 省電力OFF 一括インストーラ
# ==============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "❌ このスクリプトは管理者権限 (sudo) で実行してください。"
  echo "実行例: sudo ./install.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=================================================="
echo "🐾 Raspberry Pi Wi-Fi 安定化 & 自動復旧 インストール"
echo "=================================================="

# 1. スクリプトの配置
echo "📁 1/4 スクリプトを /usr/local/bin にコピー中..."
cp "$SCRIPT_DIR/wifi_auto_reconnect.sh" /usr/local/bin/
cp "$SCRIPT_DIR/wifi_safe_reset.sh" /usr/local/bin/
chmod +x /usr/local/bin/wifi_auto_reconnect.sh
chmod +x /usr/local/bin/wifi_safe_reset.sh

# 2. Wi-Fi省電力モードを恒久的に無効化
echo "⚡ 2/4 Wi-Fi 省電力モードを無効化 (Power Management OFF)..."
if command -v iwconfig >/dev/null 2>&1; then
    /sbin/iwconfig wlan0 power off 2>/dev/null || true
fi

# NetworkManager 用の省電力OFF設定
if [ -d "/etc/NetworkManager/conf.d" ]; then
    cat << 'EOF' > /etc/NetworkManager/conf.d/disable-wifi-powersave.conf
[connection]
wifi.powersave = 2
EOF
    echo "  -> NetworkManager 設定追加 (/etc/NetworkManager/conf.d/disable-wifi-powersave.conf)"
fi

# 3. systemd Timer の登録
echo "⏱️ 3/4 systemd Watchdog タイマーを登録 (2分間隔)..."
cp "$SCRIPT_DIR/wifi_watchdog.service" /etc/systemd/system/
cp "$SCRIPT_DIR/wifi_watchdog.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wifi_watchdog.timer

# 4. 完了確認
echo "=================================================="
echo "✅ セットアップが完了しました！"
echo "=================================================="
echo "・Wi-Fi常時監視タイマー: 有効 (2分おきに自動チェック)"
echo "・安全リセットコマンド  : sudo wifi_safe_reset.sh"
echo "・ログ確認コマンド      : journalctl -u wifi_watchdog.service"
echo "                       cat /var/log/wifi_watchdog.log"
echo "=================================================="
