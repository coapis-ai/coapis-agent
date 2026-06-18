# -*- coding: utf-8 -*-
"""RSA-based License Signing and Verification for CoApis Enterprise.

This module provides cryptographically secure license key generation
and verification using RSA-2048 signatures.

Usage:
    # Generate key pair (run once)
    from coapis.license_crypto import generate_keypair
    generate_keypair("./license_keys")
    
    # Generate license key
    from coapis.license_crypto import LicenseSigner
    signer = LicenseSigner.load("./license_keys/license_private.pem")
    key = signer.create_license("Acme Corp", "professional", 365)
    
    # Verify license key
    from coapis.license_crypto import LicenseVerifier
    verifier = LicenseVerifier.load("./license_keys/license_public.pem")
    info = verifier.verify(key)
    if info.is_valid:
        print(f"Valid until {info.expires}")
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# License Info Data Model
# ═══════════════════════════════════════════════════════════

@dataclass
class LicenseInfo:
    """Decoded and verified license information."""
    
    is_valid: bool = False
    license_id: str = ""
    customer: str = ""
    customer_id: str = ""
    tier: str = "community"
    issued: Optional[datetime] = None
    expires: Optional[datetime] = None
    features: List[str] = field(default_factory=list)
    max_nodes: int = 1
    max_users: int = 10
    max_agents: int = 5
    machine_fingerprint: str = ""
    is_trial: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    
    @property
    def is_expired(self) -> bool:
        """Check if license is expired."""
        if not self.expires:
            return False
        return datetime.now(timezone.utc) > self.expires
    
    @property
    def days_remaining(self) -> int:
        """Get days until expiration."""
        if not self.expires:
            return -1
        delta = self.expires - datetime.now(timezone.utc)
        return max(0, delta.days)
    
    @property
    def is_machine_bound(self) -> bool:
        """Check if license is bound to a specific machine."""
        return bool(self.machine_fingerprint)
    
    def matches_machine(self) -> bool:
        """Check if license matches current machine."""
        if not self.machine_fingerprint:
            return True  # Not bound
        return self.machine_fingerprint == get_machine_fingerprint()


# ═══════════════════════════════════════════════════════════
# Machine Fingerprint
# ═══════════════════════════════════════════════════════════

def get_machine_fingerprint() -> str:
    """Generate a stable machine fingerprint.
    
    Uses multiple identifiers for robustness while preserving privacy.
    """
    parts = [
        platform.node(),           # Hostname
        platform.machine(),        # Architecture
        platform.system(),         # OS
        str(uuid.getnode()),       # MAC address
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════
# Key Generation
# ═══════════════════════════════════════════════════════════

def generate_keypair(output_dir: str = ".") -> tuple[str, str]:
    """Generate RSA-2048 key pair for license signing.
    
    Args:
        output_dir: Directory to save key files
        
    Returns:
        (private_key_path, public_key_path)
    """
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    
    # Get public key
    public_key = private_key.public_key()
    
    # Serialize private key (PEM format)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    
    # Serialize public key (PEM format)
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    
    # Save to files
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    private_path = out_path / "license_private.pem"
    public_path = out_path / "license_public.pem"
    
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    
    # Set restrictive permissions on private key
    os.chmod(private_path, 0o600)
    
    logger.info("RSA key pair generated: %s, %s", private_path, public_path)
    
    return str(private_path), str(public_path)


# ═══════════════════════════════════════════════════════════
# License Signer (Sales/Admin side)
# ═══════════════════════════════════════════════════════════

class LicenseSigner:
    """Creates and signs license keys using RSA private key.
    
    This should only be used by the sales/admin team,
    NOT embedded in the product.
    """
    
    def __init__(self, private_key: rsa.RSAPrivateKey):
        self._private_key = private_key
    
    @classmethod
    def load(cls, key_path: str) -> "LicenseSigner":
        """Load signer from private key file."""
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend(),
            )
        return cls(private_key)
    
    def create_license(
        self,
        customer: str,
        tier: str,
        duration_days: int = 365,
        features: Optional[List[str]] = None,
        max_nodes: int = 1,
        max_users: int = 10,
        max_agents: int = 5,
        machine_fingerprint: str = "",
        is_trial: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a signed license key.
        
        Args:
            customer: Customer company name
            tier: License tier (starter/professional/enterprise)
            duration_days: License validity period
            features: Explicit feature list (auto-selected from tier if None)
            max_nodes: Maximum cluster nodes
            max_users: Maximum users
            max_agents: Maximum agents
            machine_fingerprint: Bind to specific machine (optional)
            is_trial: Whether this is a trial license
            metadata: Additional metadata
            
        Returns:
            Signed license key string
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=duration_days)
        
        # Build payload
        payload = {
            "version": 1,
            "license_id": str(uuid.uuid4()),
            "customer": customer,
            "customer_id": _hash_customer(customer),
            "tier": tier,
            "issued": now.isoformat(),
            "expires": expires.isoformat(),
            "features": features or [],
            "max_nodes": max_nodes,
            "max_users": max_users,
            "max_agents": max_agents,
            "machine_fingerprint": machine_fingerprint,
            "trial": is_trial,
            "metadata": metadata or {},
        }
        
        # Serialize and sign
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        
        signature = self._private_key.sign(
            payload_json.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
        
        return f"{payload_b64}.{signature_b64}"


# ═══════════════════════════════════════════════════════════
# License Verifier (Product side)
# ═══════════════════════════════════════════════════════════

class LicenseVerifier:
    """Verifies license keys using RSA public key.
    
    This is embedded in the product to verify licenses.
    """
    
    def __init__(self, public_key: rsa.RSAPublicKey):
        self._public_key = public_key
    
    @classmethod
    def load(cls, key_path: str) -> "LicenseVerifier":
        """Load verifier from public key file."""
        with open(key_path, "rb") as f:
            public_key = serialization.load_pem_public_key(
                f.read(),
                backend=default_backend(),
            )
        return cls(public_key)
    
    @classmethod
    def from_pem(cls, pem_data: str) -> "LicenseVerifier":
        """Load verifier from PEM string."""
        public_key = serialization.load_pem_public_key(
            pem_data.encode(),
            backend=default_backend(),
        )
        return cls(public_key)
    
    def verify(self, license_key: str) -> LicenseInfo:
        """Verify and decode a license key.
        
        Args:
            license_key: Signed license key string
            
        Returns:
            LicenseInfo with validation results
        """
        info = LicenseInfo()
        
        if not license_key:
            info.error = "Empty license key"
            return info
        
        # Parse format: payload.signature
        parts = license_key.split(".")
        if len(parts) != 2:
            info.error = "Invalid license format (expected payload.signature)"
            return info
        
        payload_b64, signature_b64 = parts
        
        # Decode (add padding back)
        try:
            # Add padding to base64
            payload_b64_padded = payload_b64 + "=" * (4 - len(payload_b64) % 4) if len(payload_b64) % 4 else payload_b64
            signature_b64_padded = signature_b64 + "=" * (4 - len(signature_b64) % 4) if len(signature_b64) % 4 else signature_b64
            
            payload_json = base64.urlsafe_b64decode(payload_b64_padded).decode()
            signature = base64.urlsafe_b64decode(signature_b64_padded)
        except Exception as e:
            info.error = f"Base64 decode failed: {e}"
            return info
        
        # Verify signature
        try:
            self._public_key.verify(
                signature,
                payload_json.encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception:
            info.error = "Signature verification failed"
            return info
        
        # Parse payload
        try:
            data = json.loads(payload_json)
        except Exception as e:
            info.error = f"Invalid payload JSON: {e}"
            return info
        
        # Extract fields
        info.is_valid = True
        info.license_id = data.get("license_id", "")
        info.customer = data.get("customer", "")
        info.customer_id = data.get("customer_id", "")
        info.tier = data.get("tier", "community")
        info.issued = _parse_datetime(data.get("issued"))
        info.expires = _parse_datetime(data.get("expires"))
        info.features = data.get("features", [])
        info.max_nodes = data.get("max_nodes", 1)
        info.max_users = data.get("max_users", 10)
        info.max_agents = data.get("max_agents", 5)
        info.machine_fingerprint = data.get("machine_fingerprint", "")
        info.is_trial = data.get("trial", False)
        info.metadata = data.get("metadata", {})
        
        # Check expiration
        if info.is_expired:
            info.is_valid = False
            info.error = "License expired"
            return info
        
        # Check machine binding
        if not info.matches_machine():
            info.is_valid = False
            info.error = "License bound to different machine"
            return info
        
        return info


# ═══════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════

def _hash_customer(customer: str) -> str:
    """Generate customer ID from name."""
    return hashlib.md5(customer.encode()).hexdigest()[:8]


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO format datetime string."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None
