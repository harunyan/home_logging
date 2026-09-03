package storage

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"home_logging_server/models"
)

// Storage handles persistent storage and querying of logging events.
type Storage struct {
	mu           sync.RWMutex
	filePath     string
	memoryCache  []models.LogEvent
	deviceMap    map[string]*models.DeviceStatus
	maxMemoryLog int
}

// NewStorage initializes storage with the specified file path.
func NewStorage(filePath string) (*Storage, error) {
	dir := filepath.Dir(filePath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create storage dir: %w", err)
	}

	s := &Storage{
		filePath:     filePath,
		memoryCache:  make([]models.LogEvent, 0),
		deviceMap:    make(map[string]*models.DeviceStatus),
		maxMemoryLog: 5000, // Keep latest 5000 in memory for fast lookup
	}

	if err := s.loadExistingData(); err != nil {
		log.Printf("[Storage] Warning loading existing data: %v", err)
	}

	return s, nil
}

// loadExistingData reads existing JSONL file into memory.
func (s *Storage) loadExistingData() error {
	file, err := os.Open(s.filePath)
	if os.IsNotExist(err) {
		return nil // New file, no existing data
	}
	if err != nil {
		return err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	var loaded []models.LogEvent

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var ev models.LogEvent
		if err := json.Unmarshal([]byte(line), &ev); err == nil {
			loaded = append(loaded, ev)
		}
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	// Populate devices and cache
	for _, ev := range loaded {
		s.updateDeviceStatusUnlocked(ev)
	}

	if len(loaded) > s.maxMemoryLog {
		s.memoryCache = loaded[len(loaded)-s.maxMemoryLog:]
	} else {
		s.memoryCache = loaded
	}

	log.Printf("[Storage] Loaded %d events from %s. Active devices: %d", len(loaded), s.filePath, len(s.deviceMap))
	return scanner.Err()
}

// SaveEvent persists an event and updates the cache.
func (s *Storage) SaveEvent(ev models.LogEvent) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if ev.ID == "" {
		ev.ID = fmt.Sprintf("%d-%s", time.Now().UnixNano(), ev.DeviceID)
	}
	if ev.Timestamp.IsZero() {
		ev.Timestamp = time.Now()
	}
	ev.ReceivedAt = time.Now()

	// Append to JSONL file
	file, err := os.OpenFile(s.filePath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return fmt.Errorf("failed to open storage file: %w", err)
	}
	defer file.Close()

	data, err := json.Marshal(ev)
	if err != nil {
		return fmt.Errorf("failed to marshal event: %w", err)
	}

	if _, err := file.Write(append(data, '\n')); err != nil {
		return fmt.Errorf("failed to write to storage file: %w", err)
	}

	// Update memory cache
	s.memoryCache = append(s.memoryCache, ev)
	if len(s.memoryCache) > s.maxMemoryLog {
		s.memoryCache = s.memoryCache[len(s.memoryCache)-s.maxMemoryLog:]
	}

	// Update device map
	s.updateDeviceStatusUnlocked(ev)

	return nil
}

func (s *Storage) updateDeviceStatusUnlocked(ev models.LogEvent) {
	status, exists := s.deviceMap[ev.DeviceID]
	if !exists {
		status = &models.DeviceStatus{
			DeviceID:   ev.DeviceID,
			DeviceType: ev.DeviceType,
		}
		s.deviceMap[ev.DeviceID] = status
	}

	status.LastSeen = ev.Timestamp
	if ev.WeightG > 0 {
		status.LastWeightG = ev.WeightG
	}
	if ev.TemperatureC != nil {
		status.LastTempC = ev.TemperatureC
	}
	if ev.HumidityPct != nil {
		status.LastHumidity = ev.HumidityPct
	}
	status.LastEventType = ev.EventType
	status.TotalEvents++
	if ev.DeviceType != "" {
		status.DeviceType = ev.DeviceType
	}
}

// QueryFilter parameters for querying events
// QueryFilter parameters for querying events
type QueryFilter struct {
	DeviceID   string
	EventType  string
	Limit      int
	BeforeID   string
	BeforeTime *time.Time
}

// QueryEvents returns events matching criteria in reverse chronological order.
func (s *Storage) QueryEvents(filter QueryFilter) []models.LogEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var result []models.LogEvent
	limit := filter.Limit
	if limit <= 0 {
		limit = 100
	}
	if limit > 50000 {
		limit = 50000
	}

	// Traverse backwards (newest first)
	for i := len(s.memoryCache) - 1; i >= 0; i-- {
		ev := s.memoryCache[i]

		if filter.BeforeTime != nil && !ev.Timestamp.Before(*filter.BeforeTime) {
			continue
		}
		if filter.DeviceID != "" && ev.DeviceID != filter.DeviceID {
			continue
		}
		if filter.EventType != "" && ev.EventType != filter.EventType {
			continue
		}

		result = append(result, ev)
		if len(result) >= limit {
			break
		}
	}

	return result
}

// GetDeviceStatuses returns current list of known devices.
func (s *Storage) GetDeviceStatuses() []models.DeviceStatus {
	s.mu.RLock()
	defer s.mu.RUnlock()

	now := time.Now()
	devices := make([]models.DeviceStatus, 0, len(s.deviceMap))

	for _, d := range s.deviceMap {
		statusCopy := *d
		// Online if updated in the last 10 minutes
		statusCopy.IsOnline = now.Sub(d.LastSeen) < 10*time.Minute
		devices = append(devices, statusCopy)
	}

	sort.Slice(devices, func(i, j int) bool {
		return devices[i].DeviceID < devices[j].DeviceID
	})

	return devices
}

// GetSummary calculates aggregate metrics for a specific date (defaults to today).
func (s *Storage) GetSummary(targetDateStr string) models.SummaryStats {
	s.mu.RLock()
	defer s.mu.RUnlock()

	now := time.Now()
	targetDate := now
	if targetDateStr != "" {
		if parsed, err := time.ParseInLocation("2006-01-02", targetDateStr, now.Location()); err == nil {
			targetDate = parsed
		}
	}

	dayStart := time.Date(targetDate.Year(), targetDate.Month(), targetDate.Day(), 0, 0, 0, 0, targetDate.Location())
	dayEnd := dayStart.Add(24 * time.Hour)

	var summary models.SummaryStats
	summary.TargetDate = dayStart.Format("2006-01-02")
	summary.ActiveDevicesCount = len(s.deviceMap)

	var lastMealTime time.Time
	var mealSessions []models.MealSession

	for _, ev := range s.memoryCache {
		// Filter events within the target day
		if (ev.Timestamp.Equal(dayStart) || ev.Timestamp.After(dayStart)) && ev.Timestamp.Before(dayEnd) {
			summary.TotalEventsToday++

			if ev.EventType == "meal_finished" {
				eaten := 0.0
				if ev.DeltaG != nil && *ev.DeltaG < 0 && *ev.DeltaG >= -500 {
					eaten = float64(int(-(*ev.DeltaG)*10+0.5)) / 10
				}

				if lastMealTime.IsZero() || ev.Timestamp.Sub(lastMealTime) > 3*time.Minute {
					summary.TodayMealsCount++
					mealSessions = append(mealSessions, models.MealSession{
						Time:      ev.Timestamp.Format("15:04"),
						Timestamp: ev.Timestamp,
						EatenG:    eaten,
						WeightG:   ev.WeightG,
					})
				} else {
					if len(mealSessions) > 0 {
						mealSessions[len(mealSessions)-1].EatenG = float64(int((mealSessions[len(mealSessions)-1].EatenG+eaten)*10+0.5)) / 10
					}
				}
				summary.TodayFoodEatenG += eaten
				lastMealTime = ev.Timestamp
			}
		}

		// Track latest values globally
		if (ev.EventType == "food_level" || ev.EventType == "meal_finished" || ev.EventType == "refill") || (ev.DeviceType == "feeder" && ev.EventType != "env_measured" && ev.WeightG > 0) {
			if ev.Timestamp.After(summary.LatestFoodTime) {
				summary.LatestFoodWeightG = ev.WeightG
				summary.LatestFoodTime = ev.Timestamp
			}
		}

		if ev.DeviceType == "scale" && ev.EventType == "weight_measured" && ev.WeightG >= 1000 {
			if ev.Timestamp.After(summary.LatestWeightTime) {
				summary.LatestCatWeightG = ev.WeightG
				summary.LatestWeightTime = ev.Timestamp
			}
		}

		if ev.TemperatureC != nil || ev.HumidityPct != nil {
			if ev.Timestamp.After(summary.LatestEnvTime) {
				summary.LatestTempC = ev.TemperatureC
				summary.LatestHumidityPct = ev.HumidityPct
				summary.LatestPressureHpa = ev.PressureHpa
				summary.LatestEnvTime = ev.Timestamp
			}
		}
	}

	// 2. If no explicit meal_finished events recorded, analyze continuous food_level drops
	if summary.TodayMealsCount == 0 {
		var prevWeight float64 = -1
		var prevTime time.Time

		for _, ev := range s.memoryCache {
			if (ev.Timestamp.Equal(dayStart) || ev.Timestamp.After(dayStart)) && ev.Timestamp.Before(dayEnd) && (ev.DeviceType == "feeder" || ev.EventType == "food_level") && ev.WeightG > 0 && ev.WeightG <= 1000 {
				if prevWeight >= 0 {
					delta := ev.WeightG - prevWeight
					if delta <= -1.8 && delta >= -35.0 {
						eaten := float64(int(-delta*10+0.5)) / 10
						if prevTime.IsZero() || ev.Timestamp.Sub(prevTime) > 3*time.Minute {
							summary.TodayMealsCount++
							mealSessions = append(mealSessions, models.MealSession{
								Time:      ev.Timestamp.Format("15:04"),
								Timestamp: ev.Timestamp,
								EatenG:    eaten,
								WeightG:   ev.WeightG,
							})
						} else {
							if len(mealSessions) > 0 {
								mealSessions[len(mealSessions)-1].EatenG = float64(int((mealSessions[len(mealSessions)-1].EatenG+eaten)*10+0.5)) / 10
							}
						}
						summary.TodayFoodEatenG += eaten
						prevTime = ev.Timestamp
						prevWeight = ev.WeightG
					} else if delta >= 15.0 || (delta > -0.8 && delta < 0.8) {
						prevWeight = ev.WeightG
					}
				} else {
					prevWeight = ev.WeightG
				}
			}
		}
	}

	summary.TodayFoodEatenG = float64(int(summary.TodayFoodEatenG*10+0.5)) / 10
	summary.MealSessions = mealSessions

	// 3. Generate past meal tiles back to the earliest recorded date
	dayNames := []string{"日", "月", "火", "水", "木", "金", "土"}
	todayStr := now.Format("2006-01-02")
	targetDayStr := dayStart.Format("2006-01-02")

	oldestDateStr := todayStr
	if len(s.memoryCache) > 0 {
		oldestDateStr = s.memoryCache[0].Timestamp.Format("2006-01-02")
	}

	for i := 0; i < 30; i++ {
		tileDate := now.AddDate(0, 0, -i)
		tileDateStart := time.Date(tileDate.Year(), tileDate.Month(), tileDate.Day(), 0, 0, 0, 0, tileDate.Location())
		tileDateEnd := tileDateStart.Add(24 * time.Hour)
		dStr := tileDateStart.Format("2006-01-02")

		if dStr < oldestDateStr {
			break
		}
		wName := dayNames[int(tileDateStart.Weekday())]

		if dStr == targetDayStr {
			summary.DailyMealsTiles = append(summary.DailyMealsTiles, models.DailyMealTile{
				Date:         dStr,
				DisplayDate:  tileDateStart.Format("01/02") + " (" + wName + ")",
				DayOfWeek:    wName,
				MealsCount:   summary.TodayMealsCount,
				FoodEatenG:   summary.TodayFoodEatenG,
				MealSessions: mealSessions,
				IsToday:      (dStr == todayStr),
				IsSelected:   true,
			})
		} else {
			// Compute for tileDate
			var tileMealsCount int
			var tileFoodEatenG float64
			var tileSessions []models.MealSession
			var tileLastMealTime time.Time

			for _, ev := range s.memoryCache {
				if (ev.Timestamp.Equal(tileDateStart) || ev.Timestamp.After(tileDateStart)) && ev.Timestamp.Before(tileDateEnd) {
					if ev.EventType == "meal_finished" {
						eaten := 0.0
						if ev.DeltaG != nil && *ev.DeltaG < 0 && *ev.DeltaG >= -500 {
							eaten = float64(int(-(*ev.DeltaG)*10+0.5)) / 10
						}

						if tileLastMealTime.IsZero() || ev.Timestamp.Sub(tileLastMealTime) > 3*time.Minute {
							tileMealsCount++
							tileSessions = append(tileSessions, models.MealSession{
								Time:      ev.Timestamp.Format("15:04"),
								Timestamp: ev.Timestamp,
								EatenG:    eaten,
								WeightG:   ev.WeightG,
							})
						} else if len(tileSessions) > 0 {
							tileSessions[len(tileSessions)-1].EatenG = float64(int((tileSessions[len(tileSessions)-1].EatenG+eaten)*10+0.5)) / 10
						}
						tileFoodEatenG += eaten
						tileLastMealTime = ev.Timestamp
					}
				}
			}

			if tileMealsCount == 0 {
				var prevW float64 = -1
				var prevT time.Time
				for _, ev := range s.memoryCache {
					if (ev.Timestamp.Equal(tileDateStart) || ev.Timestamp.After(tileDateStart)) && ev.Timestamp.Before(tileDateEnd) && (ev.DeviceType == "feeder" || ev.EventType == "food_level") && ev.WeightG > 0 && ev.WeightG <= 1000 {
						if prevW >= 0 {
							delta := ev.WeightG - prevW
							if delta <= -1.8 && delta >= -35.0 {
								eaten := float64(int(-delta*10+0.5)) / 10
								if prevT.IsZero() || ev.Timestamp.Sub(prevT) > 3*time.Minute {
									tileMealsCount++
									tileSessions = append(tileSessions, models.MealSession{
										Time:      ev.Timestamp.Format("15:04"),
										Timestamp: ev.Timestamp,
										EatenG:    eaten,
										WeightG:   ev.WeightG,
									})
								} else if len(tileSessions) > 0 {
									tileSessions[len(tileSessions)-1].EatenG = float64(int((tileSessions[len(tileSessions)-1].EatenG+eaten)*10+0.5)) / 10
								}
								tileFoodEatenG += eaten
								prevT = ev.Timestamp
								prevW = ev.WeightG
							} else if delta >= 15.0 || (delta > -0.8 && delta < 0.8) {
								prevW = ev.WeightG
							}
						} else {
							prevW = ev.WeightG
						}
					}
				}
			}

			summary.DailyMealsTiles = append(summary.DailyMealsTiles, models.DailyMealTile{
				Date:         dStr,
				DisplayDate:  tileDateStart.Format("01/02") + " (" + wName + ")",
				DayOfWeek:    wName,
				MealsCount:   tileMealsCount,
				FoodEatenG:   float64(int(tileFoodEatenG*10+0.5)) / 10,
				MealSessions: tileSessions,
				IsToday:      (dStr == todayStr),
				IsSelected:   false,
			})
		}
	}

	// 4. Collect latest environment reading for each distinct device and global latest CO2
	latestEnvMap := make(map[string]models.EnvReading)
	for _, ev := range s.memoryCache {
		if ev.TemperatureC != nil || ev.HumidityPct != nil {
			cur, exists := latestEnvMap[ev.DeviceID]
			if !exists || ev.Timestamp.After(cur.Timestamp) {
				latestEnvMap[ev.DeviceID] = models.EnvReading{
					DeviceID:     ev.DeviceID,
					TemperatureC: ev.TemperatureC,
					HumidityPct:  ev.HumidityPct,
					PressureHpa:  ev.PressureHpa,
					CO2Ppm:       ev.CO2Ppm,
					Timestamp:    ev.Timestamp,
					Note:         ev.Note,
				}
			}
		}
		if ev.CO2Ppm != nil && *ev.CO2Ppm >= 350 && *ev.CO2Ppm <= 10000 {
			if summary.LatestCo2Ppm == nil || ev.Timestamp.After(summary.LatestCo2Time) {
				summary.LatestCo2Ppm = ev.CO2Ppm
				summary.LatestCo2Time = ev.Timestamp
			}
		}
	}

	for _, reading := range latestEnvMap {
		summary.LatestEnvs = append(summary.LatestEnvs, reading)
	}

	sort.Slice(summary.LatestEnvs, func(i, j int) bool {
		return summary.LatestEnvs[i].DeviceID < summary.LatestEnvs[j].DeviceID
	})

	return summary
}
