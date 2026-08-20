<?php
/**
 * Cat Home Logging - XREA Data Query API (api/get_sensor.php)
 * Provides sensor events and summary stats for Web Dashboard graphs.
 */

header('Content-Type: application/json; charset=UTF-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

require_once __DIR__ . '/config.php';

$db = get_db_connection();

$limit = isset($_GET['limit']) ? min(3000, max(1, (int)$_GET['limit'])) : 1500;
$deviceId = $_GET['device_id'] ?? '';
$eventType = $_GET['event_type'] ?? '';
$range = $_GET['range'] ?? ''; // '1h', '3h', '6h', '24h', '7d', 'all'

// Auto-cleanup or manual cleanup of past anomalies if requested
if (isset($_GET['cleanup_anomalies']) && $_GET['cleanup_anomalies'] === '1') {
    $db->exec("DELETE FROM events WHERE weight_g < 0 OR weight_g > 25000 OR ((device_type = 'feeder' OR event_type = 'food_level') AND weight_g > 1000);");
}

$whereClauses = [];
if (!empty($deviceId)) {
    $whereClauses[] = "device_id = '" . SQLite3::escapeString($deviceId) . "'";
}
if (!empty($eventType)) {
    $whereClauses[] = "event_type = '" . SQLite3::escapeString($eventType) . "'";
}

// Ignore physical glitch anomalies in timeline queries (Feeder: 0-1000g, Scale: 0-25000g)
$whereClauses[] = "(weight_g IS NULL OR (weight_g >= 0 AND weight_g <= 25000 AND NOT ((device_type = 'feeder' OR event_type = 'food_level') AND weight_g > 1000)))";

if (!empty($range) && $range !== 'all') {
    $seconds = 0;
    switch ($range) {
        case '1h':  $seconds = 3600; break;
        case '3h':  $seconds = 3 * 3600; break;
        case '6h':  $seconds = 6 * 3600; break;
        case '24h': $seconds = 24 * 3600; break;
        case '7d':  $seconds = 7 * 86400; break;
    }
    if ($seconds > 0) {
        $now = time();
        $cutoffUtcIso = gmdate('Y-m-d\TH:i:s', $now - $seconds);
        $cutoffUtcStr = gmdate('Y-m-d H:i:s', $now - $seconds);
        $cutoffJstStr = date('Y-m-d H:i:s', $now - $seconds);
        
        $whereClauses[] = "(timestamp >= '" . SQLite3::escapeString($cutoffUtcIso) . "' OR timestamp >= '" . SQLite3::escapeString($cutoffUtcStr) . "' OR timestamp >= '" . SQLite3::escapeString($cutoffJstStr) . "' OR received_at >= '" . SQLite3::escapeString($cutoffJstStr) . "')";
    }
}

$whereSql = empty($whereClauses) ? '' : 'WHERE ' . implode(' AND ', $whereClauses);

// Fetch latest events
$sql = "SELECT id, device_id, device_type, event_type, weight_g, delta_g,
               temperature_c, humidity_pct, pressure_hpa, raw_value, note, timestamp, received_at
        FROM events
        {$whereSql}
        ORDER BY id DESC
        LIMIT {$limit};";

$results = $db->query($sql);
$events = [];

while ($row = $results->fetchArray(SQLITE3_ASSOC)) {
    // Add backward-compatible fields for sample compatibility
    $row['weight_hx711'] = $row['weight_g'];
    $row['temperature']  = $row['temperature_c'];
    $row['humidity']     = $row['humidity_pct'];
    $row['pressure']     = $row['pressure_hpa'];
    $row['raw_hx711']    = $row['raw_value'];
    $events[] = $row;
}

// Calculate summary stats for today (with anomaly filtering)
$todayStart = date('Y-m-d 00:00:00');
$todaySql = "SELECT COUNT(*) as total_events,
                    MAX(CASE WHEN device_type = 'feeder' AND weight_g >= 0 AND weight_g <= 1000 THEN weight_g END) as max_food,
                    MIN(CASE WHEN device_type = 'feeder' AND weight_g >= 0 AND weight_g <= 1000 THEN weight_g END) as min_food,
                    MAX(CASE WHEN temperature_c BETWEEN -20 AND 60 THEN temperature_c END) as max_temp,
                    MIN(CASE WHEN temperature_c BETWEEN -20 AND 60 THEN temperature_c END) as min_temp,
                    MAX(CASE WHEN humidity_pct BETWEEN 0 AND 100 THEN humidity_pct END) as max_hum,
                    MIN(CASE WHEN humidity_pct BETWEEN 0 AND 100 THEN humidity_pct END) as min_hum
             FROM events WHERE timestamp >= '{$todayStart}' OR received_at >= '{$todayStart}';";

$summaryRow = $db->querySingle($todaySql, true);

// Intelligent meal session debouncing (group meal events within 3 minutes into 1 meal session)
$mealsSql = "SELECT timestamp, received_at, weight_g, delta_g FROM events WHERE event_type = 'meal_finished' AND (timestamp >= '{$todayStart}' OR received_at >= '{$todayStart}') ORDER BY id ASC;";
$mealsRes = $db->query($mealsSql);
$mealSessionCount = 0;
$totalEatenG = 0;
$lastMealTime = 0;

while ($m = $mealsRes->fetchArray(SQLITE3_ASSOC)) {
    $ts = strtotime($m['timestamp'] ?? $m['received_at']);
    if ($lastMealTime === 0 || ($ts - $lastMealTime > 180)) { // 3 minutes debounce window
        $mealSessionCount++;
    }
    if (isset($m['delta_g']) && $m['delta_g'] < 0 && $m['delta_g'] >= -500) {
        $totalEatenG += -$m['delta_g'];
    }
    $lastMealTime = $ts;
}

// Latest status (safeguarded against glitches)
$latestFeeder = $db->querySingle("SELECT weight_g, timestamp FROM events WHERE (device_type = 'feeder' OR event_type = 'food_level') AND weight_g >= 0 AND weight_g <= 1000 ORDER BY id DESC LIMIT 1;", true);
$latestScale  = $db->querySingle("SELECT weight_g, timestamp FROM events WHERE device_type = 'scale' AND weight_g >= 100 AND weight_g <= 20000 ORDER BY id DESC LIMIT 1;", true);
$latestEnv    = $db->querySingle("SELECT temperature_c, humidity_pct, pressure_hpa, timestamp FROM events WHERE temperature_c IS NOT NULL AND temperature_c BETWEEN -20 AND 60 ORDER BY id DESC LIMIT 1;", true);

$response = [
    'status' => 'success',
    'total_returned' => count($events),
    'summary' => [
        'latest_food_weight_g' => $latestFeeder['weight_g'] ?? null,
        'latest_food_time'     => $latestFeeder['timestamp'] ?? null,
        'latest_cat_weight_g'  => $latestScale['weight_g'] ?? null,
        'latest_weight_time'   => $latestScale['timestamp'] ?? null,
        'latest_temp_c'        => $latestEnv['temperature_c'] ?? null,
        'latest_humidity_pct'  => $latestEnv['humidity_pct'] ?? null,
        'latest_pressure_hpa'  => $latestEnv['pressure_hpa'] ?? null,
        'latest_env_time'      => $latestEnv['timestamp'] ?? null,
        'today_meals_count'    => $mealSessionCount,
        'today_food_eaten_g'   => round($totalEatenG, 1),
        'total_events_today'   => (int)($summaryRow['total_events'] ?? 0),
        'today_temp_range'     => [
            'min' => $summaryRow['min_temp'] ?? null,
            'max' => $summaryRow['max_temp'] ?? null
        ],
        'today_hum_range'      => [
            'min' => $summaryRow['min_hum'] ?? null,
            'max' => $summaryRow['max_hum'] ?? null
        ]
    ],
    'events' => $events
];

echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
