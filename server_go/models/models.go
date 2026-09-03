package models

import "time"

// LogEvent represents a measurement or event sent from Raspberry Pi devices.
type LogEvent struct {
	ID           string    `json:"id"`                      // Unique identifier (auto-generated if empty)
	DeviceID     string    `json:"device_id"`               // e.g., "cat-scale-01", "feeder-bowl-01", "raspi-env-01"
	DeviceType   string    `json:"device_type"`             // "scale", "feeder", "env_sensor", "sensor"
	EventType    string    `json:"event_type"`              // "weight_measured", "meal_finished", "refill", "env_measured", "periodic_ping"
	WeightG      float64   `json:"weight_g,omitempty"`      // Measured weight in grams
	DeltaG       *float64  `json:"delta_g,omitempty"`       // Difference (e.g. food eaten amount: -15.5g)
	TemperatureC *float64  `json:"temperature_c,omitempty"` // Room temperature in °C (M5Stack ENV IV SHT40)
	HumidityPct  *float64  `json:"humidity_pct,omitempty"`  // Relative humidity in % (M5Stack ENV IV SHT40)
	PressureHpa  *float64  `json:"pressure_hpa,omitempty"`  // Air pressure in hPa (M5Stack ENV IV BMP280)
	CO2Ppm       *float64  `json:"co2_ppm,omitempty"`       // CO2 concentration in ppm (SCD40/SCD41/SCD30)
	RawValue     *int64    `json:"raw_value,omitempty"`     // Raw ADC reading from HX711 (optional for debug)
	BatteryLevel *float64  `json:"battery_level,omitempty"` // Battery % (optional)
	Note         string    `json:"note,omitempty"`          // Optional note or tags (e.g., "Cat: Tama")
	Timestamp    time.Time `json:"timestamp"`               // Event occurrence time on device
	ReceivedAt   time.Time `json:"received_at"`             // Time received by WinSV server
}

// EncryptedPayload represents an incoming encrypted event packet from client.
type EncryptedPayload struct {
	Encrypted    bool   `json:"encrypted"`
	Algorithm    string `json:"algorithm"`
	ClientPubKey string `json:"client_pubkey"`
	Nonce        string `json:"nonce"`
	Ciphertext   string `json:"ciphertext"`
}

// PublicKeyResponse represents the server's public key response.
type PublicKeyResponse struct {
	Status    string `json:"status"`
	Algorithm string `json:"algorithm"`
	PublicKey string `json:"public_key"`
}

// DeviceStatus tracks the latest known status of a device.
type DeviceStatus struct {
	DeviceID      string    `json:"device_id"`
	DeviceType    string    `json:"device_type"`
	LastSeen      time.Time `json:"last_seen"`
	LastWeightG   float64   `json:"last_weight_g"`
	LastTempC     *float64  `json:"last_temp_c,omitempty"`
	LastHumidity  *float64  `json:"last_humidity,omitempty"`
	LastEventType string    `json:"last_event_type"`
	TotalEvents   int64     `json:"total_events"`
	IsOnline      bool      `json:"is_online"` // true if seen within last 10 minutes
}

// MealSession represents a single eating event session
type MealSession struct {
	Time      string    `json:"time"`
	Timestamp time.Time `json:"timestamp"`
	EatenG    float64   `json:"eaten_g"`
	WeightG   float64   `json:"weight_g"`
}

// DailyMealTile represents an individual day tile for grid view
type DailyMealTile struct {
	Date         string        `json:"date"`
	DisplayDate  string        `json:"display_date"`
	DayOfWeek    string        `json:"day_of_week"`
	MealsCount   int           `json:"meals_count"`
	FoodEatenG   float64       `json:"food_eaten_g"`
	MealSessions []MealSession `json:"meal_sessions,omitempty"`
	IsToday      bool          `json:"is_today"`
	IsSelected   bool          `json:"is_selected"`
}

// SummaryStats provides aggregate insights (e.g., today's feeding, weight, and environment).
type SummaryStats struct {
	TargetDate         string          `json:"target_date"`
	TotalEventsToday   int             `json:"total_events_today"`
	TodayMealsCount    int             `json:"today_meals_count"`
	TodayFoodEatenG    float64         `json:"today_food_eaten_g"`
	MealSessions       []MealSession   `json:"meal_sessions,omitempty"`
	DailyMealsTiles    []DailyMealTile `json:"daily_meals_tiles,omitempty"`
	LatestFoodWeightG  float64         `json:"latest_food_weight_g"`
	LatestFoodTime     time.Time       `json:"latest_food_time,omitempty"`
	LatestCatWeightG   float64         `json:"latest_cat_weight_g"`
	LatestWeightTime   time.Time       `json:"latest_weight_time,omitempty"`
	LatestTempC        *float64        `json:"latest_temp_c,omitempty"`
	LatestHumidityPct  *float64        `json:"latest_humidity_pct,omitempty"`
	LatestPressureHpa  *float64        `json:"latest_pressure_hpa,omitempty"`
	LatestCo2Ppm       *float64        `json:"latest_co2_ppm,omitempty"`
	LatestCo2Time      time.Time       `json:"latest_co2_time,omitempty"`
	LatestEnvTime      time.Time       `json:"latest_env_time,omitempty"`
	LatestEnvs         []EnvReading    `json:"latest_envs,omitempty"`
	ActiveDevicesCount int             `json:"active_devices_count"`
}

// EnvReading represents a snapshot of temperature, humidity, and pressure for a specific device.
type EnvReading struct {
	DeviceID     string    `json:"device_id"`
	TemperatureC *float64  `json:"temperature_c,omitempty"`
	HumidityPct  *float64  `json:"humidity_pct,omitempty"`
	PressureHpa  *float64  `json:"pressure_hpa,omitempty"`
	CO2Ppm       *float64  `json:"co2_ppm,omitempty"`
	Timestamp    time.Time `json:"timestamp"`
	Note         string    `json:"note,omitempty"`
}

