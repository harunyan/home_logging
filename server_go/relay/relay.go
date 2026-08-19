package relay

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"home_logging_server/models"
	"home_logging_server/security"
)

// Relayer handles asynchronous encrypted event relaying to cloud endpoints (e.g. XREA).
type Relayer struct {
	mu         sync.Mutex
	relayURL   string
	httpClient *http.Client
	queue      []models.LogEvent
	isRelaying bool
}

// NewRelayer creates a new cloud relayer instance.
func NewRelayer(relayURL string) *Relayer {
	r := &Relayer{
		relayURL: relayURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		queue: make([]models.LogEvent, 0),
	}

	if relayURL != "" {
		log.Printf("[Relay] ☁️ Cloud relay enabled -> %s (Encrypted: AES-256-GCM)", relayURL)
	}

	return r
}

// EnqueueEvent queues events and triggers background relay to cloud.
func (r *Relayer) EnqueueEvent(events []models.LogEvent) {
	if r.relayURL == "" || len(events) == 0 {
		return
	}

	r.mu.Lock()
	r.queue = append(r.queue, events...)
	shouldStart := !r.isRelaying
	if shouldStart {
		r.isRelaying = true
	}
	r.mu.Unlock()

	if shouldStart {
		go r.processQueue()
	}
}

func (r *Relayer) processQueue() {
	for {
		r.mu.Lock()
		if len(r.queue) == 0 {
			r.isRelaying = false
			r.mu.Unlock()
			return
		}
		// Grab current batch
		batch := make([]models.LogEvent, len(r.queue))
		copy(batch, r.queue)
		r.mu.Unlock()

		err := r.sendBatch(batch)
		r.mu.Lock()
		if err == nil {
			// Remove successfully sent items
			if len(r.queue) >= len(batch) {
				r.queue = r.queue[len(batch):]
			} else {
				r.queue = r.queue[:0]
			}
			r.mu.Unlock()
		} else {
			log.Printf("[Relay] ⚠️ Cloud relay failed (%v), retrying in 15s...", err)
			r.mu.Unlock()
			time.Sleep(15 * time.Second)
		}
	}
}

func (r *Relayer) sendBatch(events []models.LogEvent) error {
	rawJSON, err := json.Marshal(events)
	if err != nil {
		return fmt.Errorf("failed to marshal events: %w", err)
	}

	// Encrypt payload with AES-256-GCM
	nonceB64, cipherB64, err := security.EncryptPayloadAES256GCM(rawJSON)
	if err != nil {
		return fmt.Errorf("encryption failed: %w", err)
	}

	envelope := models.EncryptedPayload{
		Encrypted:  true,
		Algorithm:  "aes-256-gcm",
		Nonce:      nonceB64,
		Ciphertext: cipherB64,
	}

	bodyBytes, err := json.Marshal(envelope)
	if err != nil {
		return fmt.Errorf("failed to marshal envelope: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, r.relayURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "WinSV-Cloud-Relayer")

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("server responded with status %d", resp.StatusCode)
	}

	log.Printf("[Relay] ☁️ Successfully relayed %d event(s) to XREA (HTTP %d, Encrypted AES-256-GCM)", len(events), resp.StatusCode)
	return nil
}
