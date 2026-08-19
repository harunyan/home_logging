<?php
/**
 * Cat Home Logging - XREA Ingest API (api/db_write.php)
 * Receives encrypted or plaintext event payloads from WinSV / Raspberry Pi,
 * decrypts them on the fly, and persists into SQLite.
 */

header('Content-Type: application/json; charset=UTF-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['status' => 'error', 'message' => 'Method not allowed']);
    exit;
}

require_once __DIR__ . '/config.php';

$rawBody = file_get_contents('php://input');
if (empty($rawBody)) {
    http_response_code(400);
    echo json_encode(['status' => 'error', 'message' => 'Empty request body']);
    exit;
}

// Decrypt if payload is encrypted
$eventsData = decrypt_payload($rawBody);
if ($eventsData === null) {
    http_response_code(400);
    echo json_encode(['status' => 'error', 'message' => 'Failed to parse or decrypt payload']);
    exit;
}

// Normalize to array of events
$events = isset($eventsData[0]) && is_array($eventsData[0]) ? $eventsData : [$eventsData];

$db = get_db_connection();
$stmt = $db->prepare("INSERT INTO events (
    device_id, device_type, event_type, weight_g, delta_g,
    temperature_c, humidity_pct, pressure_hpa, raw_value, note, timestamp, received_at
) VALUES (
    :device_id, :device_type, :event_type, :weight_g, :delta_g,
    :temperature_c, :humidity_pct, :pressure_hpa, :raw_value, :note, :timestamp, :received_at
)");

$savedCount = 0;
$nowStr = date('Y-m-d H:i:s');

$db->exec('BEGIN TRANSACTION;');

foreach ($events as $ev) {
    if (!isset($ev['device_id']) || empty($ev['device_id'])) {
        continue;
    }

    $deviceType = $ev['device_type'] ?? 'feeder';
    $eventType  = $ev['event_type'] ?? 'food_level';
    $weightG    = isset($ev['weight_g']) ? (float)$ev['weight_g'] : null;

    // Weight range validation
    if ($weightG !== null) {
        if (($deviceType === 'feeder' || $eventType === 'food_level' || $eventType === 'meal_finished' || $eventType === 'refill') && ($weightG < 0 || $weightG > 1000)) {
            continue; // Skip invalid feeder weight (1kg load cell)
        }
        if (($deviceType === 'scale' || $eventType === 'weight_measured') && ($weightG < 0 || $weightG > 25000)) {
            continue; // Skip invalid scale weight
        }
    }

    // Environmental range sanity checks
    $tempC = isset($ev['temperature_c']) ? (float)$ev['temperature_c'] : null;
    if ($tempC !== null && ($tempC < -20.0 || $tempC > 60.0)) {
        $tempC = null;
    }

    $humPct = isset($ev['humidity_pct']) ? (float)$ev['humidity_pct'] : null;
    if ($humPct !== null && ($humPct < 0.0 || $humPct > 100.0)) {
        $humPct = null;
    }

    $pressHpa = isset($ev['pressure_hpa']) ? (float)$ev['pressure_hpa'] : null;
    if ($pressHpa !== null && ($pressHpa < 800.0 || $pressHpa > 1200.0)) {
        $pressHpa = null;
    }

    $stmt->bindValue(':device_id', $ev['device_id'], SQLITE3_TEXT);
    $stmt->bindValue(':device_type', $deviceType, SQLITE3_TEXT);
    $stmt->bindValue(':event_type', $eventType, SQLITE3_TEXT);
    $stmt->bindValue(':weight_g', $weightG, SQLITE3_FLOAT);
    $stmt->bindValue(':delta_g', isset($ev['delta_g']) ? (float)$ev['delta_g'] : null, SQLITE3_FLOAT);
    $stmt->bindValue(':temperature_c', $tempC, SQLITE3_FLOAT);
    $stmt->bindValue(':humidity_pct', $humPct, SQLITE3_FLOAT);
    $stmt->bindValue(':pressure_hpa', $pressHpa, SQLITE3_FLOAT);
    $stmt->bindValue(':raw_value', isset($ev['raw_value']) ? (int)$ev['raw_value'] : null, SQLITE3_INTEGER);
    $stmt->bindValue(':note', $ev['note'] ?? '', SQLITE3_TEXT);
    $stmt->bindValue(':timestamp', $ev['timestamp'] ?? $nowStr, SQLITE3_TEXT);
    $stmt->bindValue(':received_at', $nowStr, SQLITE3_TEXT);

    $stmt->execute();
    $savedCount++;
}

$db->exec('COMMIT;');

http_response_code(201);
echo json_encode([
    'status' => 'success',
    'saved'  => $savedCount,
    'time'   => $nowStr
]);
