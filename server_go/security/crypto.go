package security

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"log"
)

const (
	AlgorithmName = "x25519-aes256gcm"
	hkdfSalt      = "cat-home-logging-v1"
	hkdfInfo      = "aes-256-gcm-key"
)

// CryptoManager manages server-side asymmetric key pair and payload decryption.
type CryptoManager struct {
	privateKey *ecdh.PrivateKey
	publicKey  *ecdh.PublicKey
	pubKeyB64  string
}

// NewCryptoManager generates a new ephemeral X25519 key pair on server start.
func NewCryptoManager() (*CryptoManager, error) {
	curve := ecdh.X25519()
	privKey, err := curve.GenerateKey(rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("failed to generate X25519 key: %w", err)
	}

	pubKey := privKey.PublicKey()
	pubKeyBytes := pubKey.Bytes()
	pubKeyB64 := base64.StdEncoding.EncodeToString(pubKeyBytes)

	log.Printf("[Security] 🔑 Ephemeral X25519 Key Pair initialized (Pubkey: %s...)", pubKeyB64[:16])

	return &CryptoManager{
		privateKey: privKey,
		publicKey:  pubKey,
		pubKeyB64:  pubKeyB64,
	}, nil
}

// GetPublicKeyBase64 returns the server's public key encoded in Base64.
func (cm *CryptoManager) GetPublicKeyBase64() string {
	return cm.pubKeyB64
}

// DecryptPayload decrypts a client-encrypted payload using X25519 ECDH + HKDF + AES-256-GCM.
func (cm *CryptoManager) DecryptPayload(clientPubKeyB64, nonceB64, ciphertextB64 string) ([]byte, error) {
	// 1. Decode client public key
	clientPubKeyBytes, err := base64.StdEncoding.DecodeString(clientPubKeyB64)
	if err != nil {
		return nil, fmt.Errorf("invalid client public key base64: %w", err)
	}

	clientPubKey, err := ecdh.X25519().NewPublicKey(clientPubKeyBytes)
	if err != nil {
		return nil, fmt.Errorf("invalid client X25519 public key: %w", err)
	}

	// 2. Compute ECDH shared secret
	sharedSecret, err := cm.privateKey.ECDH(clientPubKey)
	if err != nil {
		return nil, fmt.Errorf("ECDH key agreement failed: %w", err)
	}

	// 3. Derive 32-byte AES-256 key via HKDF-SHA256
	aesKey, err := deriveHKDF(sharedSecret, []byte(hkdfSalt), []byte(hkdfInfo), 32)
	if err != nil {
		return nil, fmt.Errorf("HKDF key derivation failed: %w", err)
	}

	// 4. Decode nonce & ciphertext
	nonce, err := base64.StdEncoding.DecodeString(nonceB64)
	if err != nil {
		return nil, fmt.Errorf("invalid nonce base64: %w", err)
	}

	ciphertext, err := base64.StdEncoding.DecodeString(ciphertextB64)
	if err != nil {
		return nil, fmt.Errorf("invalid ciphertext base64: %w", err)
	}

	// 5. Decrypt with AES-256-GCM
	block, err := aes.NewCipher(aesKey)
	if err != nil {
		return nil, fmt.Errorf("failed to create AES cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("failed to create GCM: %w", err)
	}

	if len(nonce) != gcm.NonceSize() {
		return nil, fmt.Errorf("invalid nonce size: got %d, expected %d", len(nonce), gcm.NonceSize())
	}

	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("AES-GCM decryption failed (authentication failed): %w", err)
	}

	return plaintext, nil
}

// deriveHKDF implements RFC 5869 HKDF-Extract and HKDF-Expand using standard library.
func deriveHKDF(secret, salt, info []byte, keyLen int) ([]byte, error) {
	if len(salt) == 0 {
		salt = make([]byte, sha256.Size)
	}

	// Step 1: HKDF-Extract: PRK = HMAC-Hash(salt, secret)
	extractor := hmac.New(sha256.New, salt)
	extractor.Write(secret)
	prk := extractor.Sum(nil)

	// Step 2: HKDF-Expand
	var out []byte
	var prev []byte
	expander := hmac.New(sha256.New, prk)
	for i := 1; len(out) < keyLen; i++ {
		expander.Reset()
		expander.Write(prev)
		expander.Write(info)
		expander.Write([]byte{byte(i)})
		prev = expander.Sum(nil)
		out = append(out, prev...)
	}

	return out[:keyLen], nil
}
