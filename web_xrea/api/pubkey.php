<?php
/**
 * Cat Home Logging - XREA Public Key API (api/pubkey.php)
 * Returns XREA server public key for password-free encryption.
 */

header('Content-Type: application/json; charset=UTF-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

require_once __DIR__ . '/config.php';

$keyPair = get_or_create_server_keypair();

echo json_encode([
    'status'     => 'ok',
    'service'    => 'cat-home-logging-xrea',
    'algorithm'  => 'aes-256-gcm-hkdf',
    'public_key' => $keyPair ? base64_encode($keyPair['public']) : null,
    'time'       => date('Y-m-d H:i:s')
], JSON_PRETTY_PRINT);
