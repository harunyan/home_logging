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
type QueryFilter struct {
	DeviceID  string
	EventType string
	Limit     int
}

// QueryEvents returns events matching criteria in reverse chronological order.
func (s *Storage) QueryEvents(filter QueryFilter) []models.LogEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var result []models.LogEvent
	limit := filter.Limit
	if limit <= 0 || limit > 1000 {
		limit = 100
	}

	// Traverse backwards (newest first)
	for i := len(s.memoryCache) - 1; i >= 0; i-- {
		ev := s.memoryCache[i]

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

// GetSummary calculates high-level statistics for today.
func (s *Storage) GetSummary() models.SummaryStats {
	s.mu.RLock()
	defer s.mu.RUnlock()

	now := time.Now()
	todayStart := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())

	var summary models.SummaryStats
	summary.ActiveDevicesCount = len(s.deviceMap)

	for _, ev := range s.memoryCache {
		if ev.Timestamp.After(todayStart) {
			summary.TotalEventsToday++

			if ev.EventType == "meal_finished" {
				summary.TodayMealsCount++
				if ev.DeltaG != nil && *ev.DeltaG < 0 {
					summary.TodayFoodEatenG += -(*ev.DeltaG)
				}
			}

			if (ev.DeviceType == "scale" || ev.EventType == "weight_measured") && ev.WeightG > 500 { // ignore empty scale
				if ev.Timestamp.After(summary.LatestWeightTime) {
					summary.LatestCatWeightG = ev.WeightG
					summary.LatestWeightTime = ev.Timestamp
				}
			}
		}

		// Track latest environment reading
		if ev.TemperatureC != nil || ev.HumidityPct != nil {
			if ev.Timestamp.After(summary.LatestEnvTime) {
				summary.LatestTempC = ev.TemperatureC
				summary.LatestHumidityPct = ev.HumidityPct
				summary.LatestPressureHpa = ev.PressureHpa
				summary.LatestEnvTime = ev.Timestamp
			}
		}
	}

	return summary
}
