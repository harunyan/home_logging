package main

import (
	"context"
	"embed"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"home_logging_server/handlers"
	"home_logging_server/relay"
	"home_logging_server/security"
	"home_logging_server/storage"
)

//go:embed static/*
var staticFS embed.FS

func main() {
	port := flag.String("port", "8080", "HTTP server port")
	dataFile := flag.String("data", "data/events.jsonl", "Path to jsonl storage file")
	relayURL := flag.String("relay-url", "https://veris.jp/home_logging/api/db_write.php", "Cloud relay endpoint (set to empty to disable)")
	flag.Parse()

	log.Println("==================================================")
	log.Println("🐾 Cat Home Logging Signal Receiver (WinSV Go)")
	log.Println("==================================================")

	// Initialize persistent storage
	store, err := storage.NewStorage(*dataFile)
	if err != nil {
		log.Fatalf("Fatal: Failed to initialize storage: %v", err)
	}

	// Initialize crypto manager (Password-free ephemeral X25519 + AES-256-GCM)
	cryptoMgr, err := security.NewCryptoManager()
	if err != nil {
		log.Fatalf("Fatal: Failed to initialize crypto manager: %v", err)
	}

	// Initialize cloud relayer (Encrypted AES-256-GCM relay to XREA)
	relayer := relay.NewRelayer(*relayURL)

	h := handlers.NewHandler(store, cryptoMgr, relayer)
	mux := http.NewServeMux()

	// API Endpoints
	mux.HandleFunc("/health", h.HandleHealth)
	mux.HandleFunc("/api/v1/pubkey", h.HandlePublicKey)
	mux.HandleFunc("/api/v1/events", h.HandleEvents)
	mux.HandleFunc("/api/v1/devices", h.HandleDevices)
	mux.HandleFunc("/api/v1/summary", h.HandleSummary)

	// Static UI Dashboard (embedded)
	staticContent, err := fs.Sub(staticFS, "static")
	if err != nil {
		log.Fatalf("Fatal: Failed to mount embedded static files: %v", err)
	}
	mux.Handle("/", http.FileServer(http.FS(staticContent)))

	addr := fmt.Sprintf("0.0.0.0:%s", *port)
	server := &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Print local IPs for easy configuration
	printLocalIPs(*port)

	// Server start in goroutine
	go func() {
		log.Printf("🚀 Server listening on all network interfaces (%s)", addr)
		log.Printf("📁 Storage file: %s", *dataFile)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Graceful shutdown handling
	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)
	<-stopChan

	log.Println("Shutting down server gracefully...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		log.Printf("Server shutdown forced: %v", err)
	}
	log.Println("Server stopped. Bye!")
}

// printLocalIPs prints network URLs available on this machine.
func printLocalIPs(port string) {
	log.Printf("🌐 Local Dashboard: http://localhost:%s", port)
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return
	}
	for _, addr := range addrs {
		if ipnet, ok := addr.(*net.IPNet); ok && !ipnet.IP.IsLoopback() {
			if ipnet.IP.To4() != nil {
				log.Printf("📡 LAN Dashboard / API: http://%s:%s", ipnet.IP.String(), port)
			}
		}
	}
}

