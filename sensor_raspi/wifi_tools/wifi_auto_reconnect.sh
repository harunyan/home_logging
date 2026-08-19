#!/bin/bash
# ==============================================================================
# wifi_auto_reconnect.sh - Wi-Fi死活監視 & 自動復旧デーモン/スクリプト
# ==============================================================================
# ルーター (Gateway) への疎通を確認し、切断されていれば自動でWi-Fiを再接続します。
# SSH接続ができない状態でも、Raspberry Pi内部で自律的に復旧を行います。
# ==============================================================================

LOG_FILE="/var/log/wifi_watchdog.log"
MAX_LOG_LINES=1000

# 疎通確認対象 (デフォルトゲートウェイを自動取得、取得できなければ 192.168.1.1)
TARGET_IP=$(ip route | grep default | awk '{print $3}' | head -n 1)
if [ -z "$TARGET_IP" ]; then
    TARGET_IP="192.168.1.1"
fi

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ログ肥大化防止
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
    tail -n 200 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

# 1. pingによる疎通確認 (3回試行, タイムアウト2秒)
if ping -c 3 -W 2 "$TARGET_IP" > /dev/null 2>&1; then
    # 正常疎通中
    exit 0
fi

# 2. 外部DNS (8.8.8.8) にも一応確認
if ping -c 2 -W 2 8.8.8.8 > /dev/null 2>&1; then
    exit 0
fi

log_msg "⚠️ Wi-Fi 切断を検知しました (Target: $TARGET_IP に応答なし)。復旧処理を開始します..."

# 3. Wi-Fi省電力モードを強制OFF (再切断防止)
if command -v iwconfig >/dev/null 2>&1; then
    /sbin/iwconfig wlan0 power off 2>/dev/null || true
fi

# 4. NetworkManager (Bookworm以降) での復旧
if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
    log_msg "🔄 [NetworkManager] Wi-Fi ラジオを再起動中..."
    nmcli radio wifi off
    sleep 3
    nmcli radio wifi on
    sleep 5
    nmcli device connect wlan0 2>/dev/null || true

# 5. 従来環境 (dhcpcd / wpa_supplicant) での復旧
else
    log_msg "🔄 [Legacy] wlan0 インターフェースを再起動中..."
    ip link set wlan0 down
    sleep 3
    ip link set wlan0 up
    sleep 3
    wpa_cli -i wlan0 reassociate 2>/dev/null || true
    wpa_cli -i wlan0 reconfigure 2>/dev/null || true
fi

sleep 5

# 6. 復旧確認
if ping -c 2 -W 2 "$TARGET_IP" > /dev/null 2>&1; then
    log_msg "✅ Wi-Fi の自己復旧に成功しました！"
else
    log_msg "❌ 単純再起動で復旧せず。ネットワークサービス全体の再起動を試行します..."
    if systemctl is-active --quiet NetworkManager; then
        systemctl restart NetworkManager
    else
        systemctl restart dhcpcd 2>/dev/null || systemctl restart networking 2>/dev/null || true
    fi
fi
