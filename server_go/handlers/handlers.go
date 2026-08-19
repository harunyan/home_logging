package handlers

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"

	"home_logging_server/models"
	"home_logging_server/storage"
)

type Handler struct {
	storage *storage.Storage
}

func NewHandler(s *storage.Storage) *Handler {
	return &Handler{storage: s}
}

// enableCORS sets CORS headers for local/cross-origin requests.
func enableCORS(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
}

func (h *Handler) HandleHealth(w http.ResponseWriter, r *http.Request) {
	enableCORS(w)
	if r.Method == http.MethodOptions {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"ok","service":"cat-home-logging-winsv"}`))
}

// HandleEvents processes POST (receive signal) and GET (query logs).
func (h *Handler) HandleEvents(w http.ResponseWriter, r *http.Request) {
	enableCORS(w)
	if r.Method == http.MethodOptions {
		return
	}

	switch r.Method {
	case http.MethodPost:
		h.handlePostEvent(w, r)
	case http.MethodGet:
		h.handleGetEvents(w, r)
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func (h *Handler) handlePostEvent(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, `{"error":"failed to read request body"}`, http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	trimmed := strings.TrimSpace(string(body))
	if len(trimmed) == 0 {
		http.Error(w, `{"error":"empty body"}`, http.StatusBadRequest)
		return
	}

	// Support both single event object and array of events
	var eventsToSave []models.LogEvent
	if strings.HasPrefix(trimmed, "[") {
		if err := json.Unmarshal(body, &eventsToSave); err != nil {
			http.Error(w, `{"error":"invalid JSON array format"}`, http.StatusBadRequest)
			return
		}
	} else {
		var singleEvent models.LogEvent
		if err := json.Unmarshal(body, &singleEvent); err != nil {
			http.Error(w, `{"error":"invalid JSON object format"}`, http.StatusBadRequest)
			return
		}
		eventsToSave = append(eventsToSave, singleEvent)
	}

	savedCount := 0
	for _, ev := range eventsToSave {
		if ev.DeviceID == "" {
			continue // Skip invalid events without device_id
		}
		if err := h.storage.SaveEvent(ev); err != nil {
			log.Printf("[Error] Failed to save event from %s: %v", ev.DeviceID, err)
			continue
		}
		savedCount++
		log.Printf("[Event] Device: %s | Type: %s | Weight: %.2fg | Event: %s",
			ev.DeviceID, ev.DeviceType, ev.WeightG, ev.EventType)
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "success",
		"saved":  savedCount,
	})
}

func (h *Handler) handleGetEvents(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()

	limit := 50
	if lStr := query.Get("limit"); lStr != "" {
		if parsed, err := strconv.Atoi(lStr); err == nil {
			limit = parsed
		}
	}

	filter := storage.QueryFilter{
		DeviceID:  query.Get("device_id"),
		EventType: query.Get("event_type"),
		Limit:     limit,
	}

	events := h.storage.QueryEvents(filter)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"count":  len(events),
		"events": events,
	})
}

// HandleDevices returns current known devices and their status.
func (h *Handler) HandleDevices(w http.ResponseWriter, r *http.Request) {
	enableCORS(w)
	if r.Method == http.MethodOptions {
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	devices := h.storage.GetDeviceStatuses()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"devices": devices,
	})
}

// HandleSummary returns aggregate statistics for today.
func (h *Handler) HandleSummary(w http.ResponseWriter, r *http.Request) {
	enableCORS(w)
	if r.Method == http.MethodOptions {
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	summary := h.storage.GetSummary()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(summary)
}
