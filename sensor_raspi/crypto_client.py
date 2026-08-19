#!/usr/bin/env python3
"""
Zero-configuration client-side encryption module for Raspberry Pi.
Uses ephemeral X25519 ECDH + HKDF-SHA256 + AES-256-GCM to securely encrypt payloads.
No passwords or certificates required.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple, Union

try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


HKDF_SALT = b"cat-home-logging-v1"
HKDF_INFO = b"aes-256-gcm-key"


class CryptoClient:
    """Handles automatic public key retrieval from WinSV and ephemeral AES-256-GCM encryption."""

    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        self.pubkey_endpoint = f"{self.server_url}/api/v1/pubkey"
        self._server_pubkey_raw: Optional[bytes] = None
        self._has_crypto = HAS_CRYPTOGRAPHY

        if not self._has_crypto:
            try:
                print("[Security] Warning: python-cryptography library not found.")
                print("           To enable encryption: sudo apt install -y python3-cryptography")
            except Exception:
                pass

    @property
    def is_available(self) -> bool:
        return self._has_crypto

    def fetch_server_public_key(self) -> bool:
        """Fetches the server's ephemeral public key from /api/v1/pubkey."""
        if not self._has_crypto:
            return False

        try:
            req = urllib.request.Request(
                self.pubkey_endpoint,
                headers={"User-Agent": "Raspi-CryptoClient"},
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    pub_b64 = data.get("public_key")
                    if pub_b64:
                        self._server_pubkey_raw = base64.b64decode(pub_b64)
                        return True
        except Exception as e:
            # Server might be offline or endpoint not yet available
            pass
        return False

    def encrypt_data(self, payload_obj: Union[Dict[str, Any], list]) -> Union[Dict[str, Any], list]:
        """
        Encrypts payload using ephemeral X25519 ECDH + AES-256-GCM.
        Returns encrypted envelope dict, or original payload if encryption unavailable.
        """
        if not self._has_crypto:
            return payload_obj

        # Ensure server public key is cached
        if not self._server_pubkey_raw:
            if not self.fetch_server_public_key():
                return payload_obj  # Fallback to plaintext if key retrieval fails

        try:
            # 1. Generate client ephemeral private key
            client_priv_key = X25519PrivateKey.generate()
            client_pub_key = client_priv_key.public_key()
            client_pub_bytes = client_pub_key.public_bytes(
                encoding=Encoding.Raw,
                format=PublicFormat.Raw
            )

            # 2. Compute shared secret with server public key
            server_pub_key = X25519PublicKey.from_public_bytes(self._server_pubkey_raw)
            shared_secret = client_priv_key.exchange(server_pub_key)

            # 3. Derive 32-byte AES-256 key via HKDF-SHA256
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=HKDF_SALT,
                info=HKDF_INFO,
            )
            aes_key = hkdf.derive(shared_secret)

            # 4. Serialize payload to bytes
            plaintext_bytes = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")

            # 5. Encrypt with AES-256-GCM (12-byte nonce)
            nonce = os.urandom(12)
            aesgcm = AESGCM(aes_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)

            # 6. Return envelope
            return {
                "encrypted": True,
                "algorithm": "x25519-aes256gcm",
                "client_pubkey": base64.b64encode(client_pub_bytes).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii")
            }

        except Exception as e:
            print(f"⚠️ [Security] Encryption failed ({e}), falling back to plaintext.")
            self._server_pubkey_raw = None  # Reset key cache on failure
            return payload_obj
