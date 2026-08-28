package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"home_logging_server/models"
	"home_logging_server/relay"
	"home_logging_server/security"
	"home_logging_server/storage"
)

type Handler struct {
	storage *storage.Storage
	crypto  *security.CryptoManager
	relayer *relay.Relayer
}

func NewHandler(s *storage.Storage, c *security.CryptoManager, r *relay.Relayer) *Handler {
	return &Handler{storage: s, crypto: c, relayer: r}
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

// HandlePublicKey returns the server's ephemeral public key for client encryption.
func (h *Handler) HandlePublicKey(w http.ResponseWriter, r *http.Request) {
	enableCORS(w)
	if r.Method == http.MethodOptions {
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	resp := models.PublicKeyResponse{
		Status:    "ok",
		Algorithm: security.AlgorithmName,
		PublicKey: h.crypto.GetPublicKeyBase64(),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
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

	rawJSONBytes := body

	// 1. Check if incoming payload is encrypted (EncryptedPayload structure)
	if !strings.HasPrefix(trimmed, "[") && strings.Contains(trimmed, `"encrypted":true`) || strings.Contains(trimmed, `"encrypted": true`) {
		var encPayload models.EncryptedPayload
		if err := json.Unmarshal(body, &encPayload); err == nil && encPayload.Encrypted {
			decrypted, err := h.crypto.DecryptPayload(encPayload.ClientPubKey, encPayload.Nonce, encPayload.Ciphertext)
			if err != nil {
				log.Printf("[Security] ❌ Decryption failed from %s: %v", r.RemoteAddr, err)
				http.Error(w, fmt.Sprintf(`{"error":"decryption failed: %v"}`, err), http.StatusBadRequest)
				return
			}
			log.Printf("[Security] 🔒 Received encrypted payload (%d bytes) from %s -> Decrypted (%d bytes)",
				len(body), r.RemoteAddr, len(decrypted))
			rawJSONBytes = decrypted
			trimmed = strings.TrimSpace(string(rawJSONBytes))
		}
	}

	// 2. Parse decrypted/plaintext events (both single object and array supported)
	var eventsToSave []models.LogEvent
	if strings.HasPrefix(trimmed, "[") {
		if err := json.Unmarshal(rawJSONBytes, &eventsToSave); err != nil {
			http.Error(w, `{"error":"invalid JSON array format"}`, http.StatusBadRequest)
			return
		}
	} else {
		var singleEvent models.LogEvent
		if err := json.Unmarshal(rawJSONBytes, &singleEvent); err != nil {
			http.Error(w, `{"error":"invalid JSON object format"}`, http.StatusBadRequest)
			return
		}
		eventsToSave = append(eventsToSave, singleEvent)
	}

	savedCount := 0
	var validEvents []models.LogEvent
	for _, ev := range eventsToSave {
		if ev.DeviceID == "" {
			continue // Skip invalid events without device_id
		}
		if !validateEvent(&ev) {
			log.Printf("[Validation] ⚠️ Anomaly detected from %s (%s, %.2fg) - Skipped", ev.DeviceID, ev.EventType, ev.WeightG)
			continue
		}
		if err := h.storage.SaveEvent(ev); err != nil {
			log.Printf("[Error] Failed to save event from %s: %v", ev.DeviceID, err)
			continue
		}
		savedCount++
		validEvents = append(validEvents, ev)
		log.Printf("[Event] Device: %s | Type: %s | Weight: %.2fg | Event: %s",
			ev.DeviceID, ev.DeviceType, ev.WeightG, ev.EventType)
	}

	// Trigger asynchronous encrypted cloud relay to XREA if configured
	if len(validEvents) > 0 && h.relayer != nil {
		h.relayer.EnqueueEvent(validEvents)
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "success",
		"saved":  savedCount,
	})
}

// validateEvent sanitizes sensor fields and rejects extreme physical outliers.
func validateEvent(ev *models.LogEvent) bool {
	// 1. Weight validation
	if ev.DeviceType == "feeder" || ev.EventType == "meal_finished" || ev.EventType == "refill" || ev.EventType == "food_level" {
		if ev.WeightG < 0.0 || ev.WeightG > 1000.0 {
			return false // Reject negative or >1kg (1kg load cell capacity) food readings
		}
	} else if ev.DeviceType == "scale" || ev.EventType == "weight_measured" {
		if ev.WeightG < 0.0 || ev.WeightG > 25000.0 {
			return false // Reject negative or >25kg cat scale readings
		}
	}

	// 2. Environmental sanity checks (clear invalid fields instead of dropping whole event)
	if ev.TemperatureC != nil && (*ev.TemperatureC < -20.0 || *ev.TemperatureC > 60.0) {
		ev.TemperatureC = nil
	}
	if ev.HumidityPct != nil && (*ev.HumidityPct < 0.0 || *ev.HumidityPct > 100.0) {
		ev.HumidityPct = nil
	}
	if ev.PressureHpa != nil && (*ev.PressureHpa < 800.0 || *ev.PressureHpa > 1200.0) {
		ev.PressureHpa = nil
	}

	return true
}

func (h *Handler) handleGetEvents(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()

	limit := 50
	if lStr := query.Get("limit"); lStr != "" {
		if parsed, err := strconv.Atoi(lStr); err == nil {
			limit = parsed
		}
	}

	var beforeTime *time.Time
	if btStr := query.Get("before_timestamp"); btStr != "" {
		if parsed, err := time.Parse(time.RFC3339, btStr); err == nil {
			beforeTime = &parsed
		}
	}

	filter := storage.QueryFilter{
		DeviceID:   query.Get("device_id"),
		EventType:  query.Get("event_type"),
		Limit:      limit,
		BeforeID:   query.Get("before_id"),
		BeforeTime: beforeTime,
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
