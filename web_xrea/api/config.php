<?php
/**
 * Cat Home Logging - XREA Configuration & Security Helper
 * Handles automatic key management and AES-256-GCM decryption on XREA PHP server.
 */

define('DATA_DIR', __DIR__ . '/../data');
define('DB_FILE', DATA_DIR . '/home_logging.db');
define('KEY_FILE', DATA_DIR . '/xrea_private.key');
define('PUBKEY_FILE', DATA_DIR . '/xrea_public.key');

// Ensure data directory exists with proper permissions
if (!is_dir(DATA_DIR)) {
    @mkdir(DATA_DIR, 0755, true);
}

/**
 * Initializes SQLite database tables.
 */
function get_db_connection() {
    static $db = null;
    if ($db === null) {
        $db = new SQLite3(DB_FILE);
        $db->busyTimeout(5000);
        $db->exec("PRAGMA journal_mode = WAL;");
        $db->exec("CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            device_type TEXT NOT NULL,
            event_type TEXT NOT NULL,
            weight_g REAL,
            delta_g REAL,
            temperature_c REAL,
            humidity_pct REAL,
            pressure_hpa REAL,
            raw_value INTEGER,
            note TEXT,
            timestamp TEXT NOT NULL,
            received_at TEXT NOT NULL
        );");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id);");
    }
    return $db;
}

/**
 * Ensures X25519 / RSA key pair exists on XREA server for password-free zero-config encryption.
 */
function get_or_create_server_keypair() {
    if (file_exists(KEY_FILE) && file_exists(PUBKEY_FILE)) {
        return [
            'private' => file_get_contents(KEY_FILE),
            'public'  => file_get_contents(PUBKEY_FILE),
        ];
    }

    // Generate OpenSSL EC/X25519 or RSA 2048 key pair
    $config = [
        "private_key_bits" => 2048,
        "private_key_type" => OPENSSL_KEYTYPE_RSA,
    ];
    $res = openssl_pkey_new($config);
    if (!$res) {
        return null;
    }

    openssl_pkey_export($res, $privKey);
    $details = openssl_pkey_get_details($res);
    $pubKey = $details['key'];

    @file_put_contents(KEY_FILE, $privKey);
    @file_put_contents(PUBKEY_FILE, $pubKey);
    @chmod(KEY_FILE, 0600);

    return [
        'private' => $privKey,
        'public'  => $pubKey,
    ];
}

/**
 * Decrypts incoming AES-256-GCM / Hybrid payload from WinSV / Raspberry Pi.
 */
function decrypt_payload($payload_json) {
    $data = json_decode($payload_json, true);
    if (!$data) {
        return null;
    }

    // Plaintext payload (fallback)
    if (!isset($data['encrypted']) || $data['encrypted'] !== true) {
        return $data;
    }

    // AES-256-GCM Payload
    $ciphertext = base64_decode($data['ciphertext']);
    $nonce = base64_decode($data['nonce']);
    $algorithm = $data['algorithm'] ?? 'aes-256-gcm';

    // 1. If encrypted with hybrid RSA/X25519 session key
    if (isset($data['enc_key'])) {
        $keys = get_or_create_server_keypair();
        if (!$keys) return null;
        
        $encKey = base64_decode($data['enc_key']);
        $privKeyResource = openssl_pkey_get_private($keys['private']);
        if (!openssl_private_decrypt($encKey, $aesKey, $privKeyResource, OPENSSL_PKCS1_OAEP_PADDING)) {
            return null;
        }
    } else {
        // Shared HKDF derived key for cat-home-logging-v1
        $salt = "cat-home-logging-v1";
        $info = "aes-256-gcm-key";
        $aesKey = hash_hkdf('sha256', 'cat-logging-relay-default-seed', 32, $info, $salt);
    }

    // Split ciphertext and GCM authentication tag (last 16 bytes)
    $tagLen = 16;
    if (strlen($ciphertext) <= $tagLen) {
        return null;
    }
    $actualCiphertext = substr($ciphertext, 0, -$tagLen);
    $tag = substr($ciphertext, -$tagLen);

    $decrypted = openssl_decrypt(
        $actualCiphertext,
        'aes-256-gcm',
        $aesKey,
        OPENSSL_RAW_DATA,
        $nonce,
        $tag
    );

    if ($decrypted === false) {
        return null;
    }

    return json_decode($decrypted, true);
}
