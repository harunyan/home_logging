#!/bin/bash
# ==============================================================================
# wifi_safe_reset.sh - SSH経由でも安全にWi-Fiを再起動・復帰させるスクリプト
# ==============================================================================
# 【重要】SSH接続中に Wi-Fi をリセットすると、途中でSSHが切れて down のまま
# 孤立する恐れがあります。このスクリプトは nohup / subshell により、
# SSHが切断されてもバックグラウンドで確実に「down → 待機 → up → 再接続」を完遂します。
# ==============================================================================

LOG_FILE="/tmp/wifi_reset.log"

echo "=================================================="
echo "🔄 Wi-Fi 安全リセットシーケンスを開始します..."
echo "※ SSH接続が一瞬切断される場合がありますが、自動で再接続されます。"
echo "=================================================="

# バックグラウンドサブシェルで実行（親プロセス/SSHが切れても最後まで完遂）
(
    exec > "$LOG_FILE" 2>&1
    echo "[$(date)] --- Wi-Fi Safe Reset Started ---"

    # 1. Wi-Fi省電力モードをOFF
    if command -v iwconfig >/dev/null 2>&1; then
        echo "[$(date)] Disabling Power Management..."
        /sbin/iwconfig wlan0 power off 2>/dev/null || true
    fi

    # 2. NetworkManager (Bookworm以降) の場合
    if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
        echo "[$(date)] Resetting via NetworkManager (nmcli)..."
        nmcli radio wifi off
        sleep 3
        nmcli radio wifi on
        sleep 5
        # 既知の接続があれば再接続
        nmcli device connect wlan0 2>/dev/null || true

    # 3. 従来環境 (dhcpcd / wpa_supplicant) の場合
    else
        echo "[$(date)] Resetting via ip link & wpa_cli..."
        ip link set wlan0 down
        sleep 3
        ip link set wlan0 up
        sleep 2
        wpa_cli -i wlan0 reassociate 2>/dev/null || true
        wpa_cli -i wlan0 reconfigure 2>/dev/null || true
    fi

    sleep 5
    echo "[$(date)] --- Wi-Fi Safe Reset Completed ---"
    ip addr show wlan0
) &

echo "✅ バックグラウンドで復帰処理を投入しました（ログ: $LOG_FILE）"
echo "約10秒後に Wi-Fi / SSH への再接続をお試しください。"
