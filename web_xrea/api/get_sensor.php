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

$range = $_GET['range'] ?? ''; // '1h', '3h', '6h', '24h', '7d', 'all'
$defaultLimit = 6000; // default covers >24h (approx 4320 events for 3 devices)
if ($range === '7d' || $range === 'all') {
    $defaultLimit = 40000; // 7 days = approx 30240 events for 3 devices
}
$beforeId = isset($_GET['before_id']) ? (int)$_GET['before_id'] : 0;
$beforeTimestamp = $_GET['before_timestamp'] ?? '';

$limit = isset($_GET['limit']) ? min(50000, max(1, (int)$_GET['limit'])) : $defaultLimit;
$deviceId = $_GET['device_id'] ?? '';
$eventType = $_GET['event_type'] ?? '';

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

// Auto-paging support (fetching events older than a specific ID or timestamp)
if ($beforeId > 0) {
    $whereClauses[] = "id < " . $beforeId;
} elseif (!empty($beforeTimestamp)) {
    $tsEsc = SQLite3::escapeString($beforeTimestamp);
    $whereClauses[] = "(timestamp < '{$tsEsc}' OR received_at < '{$tsEsc}')";
} elseif (!empty($range) && $range !== 'all') {
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
               temperature_c, humidity_pct, pressure_hpa, co2_ppm, raw_value, note, timestamp, received_at
        FROM events
        {$whereSql}
        ORDER BY id DESC
        LIMIT {$limit};";

// Determine downsampling interval (in seconds) for long ranges
$sampleIntervalSec = 0;
if (isset($_GET['step'])) {
    $sampleIntervalSec = max(0, (int)$_GET['step']);
} elseif ($range === '7d') {
    $sampleIntervalSec = 300; // 5分間隔に間引き (7日間で約2500点/デバイス -> 爆速描画)
} elseif ($range === 'all') {
    $sampleIntervalSec = 900; // 15分間隔に間引き
}

$results = $db->query($sql);
$events = [];
$lastSampleTimeByDevice = [];

while ($row = $results->fetchArray(SQLITE3_ASSOC)) {
    $isImportantEvent = in_array($row['event_type'], ['meal_finished', 'refill', 'weight_measured']);
    $dev = $row['device_id'] ?? 'default';
    $t = strtotime($row['timestamp'] ?? $row['received_at'] ?? 'now');

    if ($sampleIntervalSec > 0 && !$isImportantEvent && isset($lastSampleTimeByDevice[$dev])) {
        // Skip routine points within sample interval
        if (abs($lastSampleTimeByDevice[$dev] - $t) < $sampleIntervalSec) {
            continue;
        }
    }
    $lastSampleTimeByDevice[$dev] = $t;

    if ($row['co2_ppm'] !== null) {
        $row['co2_ppm'] = (float)$row['co2_ppm'];
    }
    if ($row['temperature_c'] !== null) {
        $row['temperature_c'] = (float)$row['temperature_c'];
    }
    if ($row['humidity_pct'] !== null) {
        $row['humidity_pct'] = (float)$row['humidity_pct'];
    }
    if ($row['pressure_hpa'] !== null) {
        $row['pressure_hpa'] = (float)$row['pressure_hpa'];
    }
    // Add backward-compatible fields for sample compatibility
    $row['weight_hx711'] = $row['weight_g'];
    $row['temperature']  = $row['temperature_c'];
    $row['humidity']     = $row['humidity_pct'];
    $row['pressure']     = $row['pressure_hpa'];
    $row['raw_hx711']    = $row['raw_value'];
    $events[] = $row;
}

// Target date for meal summary (defaults to today in JST)
$targetDate = !empty($_GET['date']) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $_GET['date']) ? $_GET['date'] : date('Y-m-d');
$todayDate  = date('Y-m-d');

function calcDailyMealStats($db, $tDate) {
    $start = "{$tDate} 00:00:00";
    $end   = "{$tDate} 23:59:59";
    $escStart = SQLite3::escapeString($start);
    $escEnd   = SQLite3::escapeString($end);

    $whereTime = "((timestamp >= '{$escStart}' AND timestamp <= '{$escEnd}') OR (received_at >= '{$escStart}' AND received_at <= '{$escEnd}'))";

    // 1. Check explicit meal_finished events
    $mealsSql = "SELECT id, timestamp, received_at, weight_g, delta_g, note FROM events WHERE event_type = 'meal_finished' AND {$whereTime} ORDER BY id ASC;";
    $mealsRes = $db->query($mealsSql);
    $mealSessionCount = 0;
    $totalEatenG = 0;
    $lastMealTime = 0;
    $mealSessions = [];

    while ($m = $mealsRes->fetchArray(SQLITE3_ASSOC)) {
        $ts = strtotime($m['timestamp'] ?? $m['received_at']);
        $eaten = (isset($m['delta_g']) && $m['delta_g'] < 0 && $m['delta_g'] >= -500) ? round(-$m['delta_g'], 1) : 0;
        if ($lastMealTime === 0 || ($ts - $lastMealTime > 180)) { // 3 min debounce
            $mealSessionCount++;
            $mealSessions[] = [
                'time'      => date('H:i', $ts),
                'timestamp' => $m['timestamp'] ?? $m['received_at'],
                'eaten_g'   => $eaten,
                'weight_g'  => $m['weight_g'] !== null ? (float)$m['weight_g'] : null
            ];
        } else {
            if (!empty($mealSessions)) {
                $lastIdx = count($mealSessions) - 1;
                $mealSessions[$lastIdx]['eaten_g'] = round($mealSessions[$lastIdx]['eaten_g'] + $eaten, 1);
            }
        }
        $totalEatenG += $eaten;
        $lastMealTime = $ts;
    }

    // 2. If no explicit meal_finished events, analyze food_level continuous changes
    if ($mealSessionCount === 0) {
        $timelineSql = "SELECT id, weight_g, timestamp, received_at FROM events WHERE (device_type = 'feeder' OR event_type = 'food_level') AND weight_g >= 0 AND weight_g <= 1000 AND {$whereTime} ORDER BY id ASC;";
        $tRes = $db->query($timelineSql);
        $prevWeight = null;
        $prevTime = 0;

        while ($r = $tRes->fetchArray(SQLITE3_ASSOC)) {
            $w = (float)$r['weight_g'];
            $ts = strtotime($r['timestamp'] ?? $r['received_at']);
            
            if ($prevWeight !== null) {
                $delta = $w - $prevWeight;
                if ($delta <= -1.8 && $delta >= -35.0) {
                    $eaten = round(-$delta, 1);
                    if ($prevTime === 0 || ($ts - $prevTime > 180)) {
                        $mealSessionCount++;
                        $mealSessions[] = [
                            'time'      => date('H:i', $ts),
                            'timestamp' => $r['timestamp'] ?? $r['received_at'],
                            'eaten_g'   => $eaten,
                            'weight_g'  => $w
                        ];
                    } else {
                        if (!empty($mealSessions)) {
                            $lastIdx = count($mealSessions) - 1;
                            $mealSessions[$lastIdx]['eaten_g'] = round($mealSessions[$lastIdx]['eaten_g'] + $eaten, 1);
                        }
                    }
                    $totalEatenG += $eaten;
                    $prevTime = $ts;
                    $prevWeight = $w;
                } elseif ($delta >= 15.0 || abs($delta) < 0.8) {
                    $prevWeight = $w;
                }
            } else {
                $prevWeight = $w;
            }
        }
    }

    return [
        'date'          => $tDate,
        'meals_count'   => $mealSessionCount,
        'food_eaten_g'  => round($totalEatenG, 1),
        'meal_sessions' => $mealSessions
    ];
}

// Calculate meal stats for the requested date
$targetMealStats = calcDailyMealStats($db, $targetDate);

// Find the earliest event date in database to avoid showing empty tiles before system start
$oldestRow = $db->querySingle("SELECT MIN(timestamp) as min_ts, MIN(received_at) as min_rec FROM events WHERE timestamp IS NOT NULL OR received_at IS NOT NULL;", true);
$oldestDateStr = date('Y-m-d');
if ($oldestRow) {
    $minTs = !empty($oldestRow['min_ts']) ? $oldestRow['min_ts'] : ($oldestRow['min_rec'] ?? null);
    if ($minTs) {
        $oldestDateStr = date('Y-m-d', strtotime($minTs));
    }
}

// Calculate meal tiles only from today back to the earliest recorded date (up to 30 days)
$maxHistoryDays = isset($_GET['meal_days']) ? min(60, max(1, (int)$_GET['meal_days'])) : 30;
$dailyMealsTiles = [];
$dayNames = ['日', '月', '火', '水', '木', '金', '土'];

for ($i = 0; $i < $maxHistoryDays; $i++) {
    $timeSec = strtotime("-{$i} days");
    $dStr = date('Y-m-d', $timeSec);
    
    // Do not generate tiles for dates before the system was launched
    if ($dStr < $oldestDateStr) {
        break;
    }

    $wIndex = (int)date('w', $timeSec);
    $wName = $dayNames[$wIndex];
    
    $stats = ($dStr === $targetDate) ? $targetMealStats : calcDailyMealStats($db, $dStr);
    $dailyMealsTiles[] = [
        'date'          => $dStr,
        'display_date'  => date('m/d', $timeSec) . " ({$wName})",
        'day_of_week'   => $wName,
        'meals_count'   => $stats['meals_count'],
        'food_eaten_g'  => $stats['food_eaten_g'],
        'meal_sessions' => $stats['meal_sessions'],
        'is_today'      => ($dStr === $todayDate),
        'is_selected'   => ($dStr === $targetDate)
    ];
}

// Calculate summary stats for today (with anomaly filtering)
$todayStart = "{$todayDate} 00:00:00";
$todaySql = "SELECT COUNT(*) as total_events,
                    MAX(CASE WHEN device_type = 'feeder' AND weight_g >= 0 AND weight_g <= 1000 THEN weight_g END) as max_food,
                    MIN(CASE WHEN device_type = 'feeder' AND weight_g >= 0 AND weight_g <= 1000 THEN weight_g END) as min_food,
                    MAX(CASE WHEN temperature_c BETWEEN -20 AND 60 THEN temperature_c END) as max_temp,
                    MIN(CASE WHEN temperature_c BETWEEN -20 AND 60 THEN temperature_c END) as min_temp,
                    MAX(CASE WHEN humidity_pct BETWEEN 0 AND 100 THEN humidity_pct END) as max_hum,
                    MIN(CASE WHEN humidity_pct BETWEEN 0 AND 100 THEN humidity_pct END) as min_hum
             FROM events WHERE timestamp >= '{$todayStart}' OR received_at >= '{$todayStart}';";

$summaryRow = $db->querySingle($todaySql, true);

// Query latest environment for each distinct device (e.g. raspi4-feeder-01, raspizero-bedroom-01, etc.)
$distinctDevicesSql = "SELECT DISTINCT device_id FROM events WHERE temperature_c IS NOT NULL AND temperature_c BETWEEN -20 AND 60;";
$devRes = $db->query($distinctDevicesSql);
$latestEnvs = [];

while ($d = $devRes->fetchArray(SQLITE3_ASSOC)) {
    $devId = $d['device_id'];
    $escDevId = SQLite3::escapeString($devId);
    $row = $db->querySingle("SELECT device_id, temperature_c, humidity_pct, pressure_hpa, co2_ppm, timestamp, note FROM events WHERE device_id = '{$escDevId}' AND temperature_c IS NOT NULL AND temperature_c BETWEEN -20 AND 60 ORDER BY id DESC LIMIT 1;", true);
    if ($row) {
        $latestEnvs[] = [
            'device_id'       => $row['device_id'],
            'temperature_c'   => $row['temperature_c'] !== null ? (float)$row['temperature_c'] : null,
            'humidity_pct'    => $row['humidity_pct'] !== null ? (float)$row['humidity_pct'] : null,
            'pressure_hpa'    => $row['pressure_hpa'] !== null ? (float)$row['pressure_hpa'] : null,
            'co2_ppm'         => isset($row['co2_ppm']) && $row['co2_ppm'] !== null ? (float)$row['co2_ppm'] : null,
            'timestamp'       => $row['timestamp'],
            'note'            => $row['note'] ?? ''
        ];
    }
}

// Global latest status (safeguarded against glitches)
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
        'target_date'          => $targetDate,
        'today_meals_count'    => $targetMealStats['meals_count'],
        'today_food_eaten_g'   => $targetMealStats['food_eaten_g'],
        'meal_sessions'        => $targetMealStats['meal_sessions'],
        'daily_meals_tiles'    => $dailyMealsTiles,
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
