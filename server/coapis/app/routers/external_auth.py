# -*- coding: utf-8 -*-
"""External Identity Authentication Router - Community Version (JSON File Storage)

Provides API endpoints for external system SSO callback, identity binding, and unbinding.
"""
import json
import hmac
import hashlib
import time
import os
import tempfile
import shutil
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Dict, Any

# Mapping file path and shared secret (from environment variable)
MAPPINGS_FILE = "data/external_identity_mappings.json"
# Use COAPIS_JWT_SECRET_KEY for external SSO signature verification, fallback to EXTERNAL_SSO_SECRET, then default
EXTERNAL_SSO_SECRET = os.getenv("COAPIS_JWT_SECRET_KEY") or os.getenv("EXTERNAL_SSO_SECRET") or "default_secret_key_community"

router = APIRouter(prefix="/api/auth", tags=["external_auth"])


def load_bindings() -> Dict[str, Any]:
    """Safely read local JSON mapping file"""
    if not os.path.exists(MAPPINGS_FILE):
        return {"bindings": []}
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"bindings": []}


def save_bindings_atomic(mappings_data: Dict[str, Any]):
    """Atomically write back JSON file to prevent concurrent overwrite"""
    # First write to a temporary file, then replace the original file on success
    dir_name = os.path.dirname(MAPPINGS_FILE) or "."
    fd, temp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(mappings_data, f, indent=2)
        shutil.move(temp_path, MAPPINGS_FILE)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def find_binding_by_external(mappings_data: Dict[str, Any], provider: str, external_id: str) -> Dict[str, Any]:
    """Find matching binding record in memory"""
    for b in mappings_data.get("bindings", []):
        if b.get("provider") == provider and b.get("external_id") == external_id and b.get("status") == 1:
            return b
    return None


@router.post("/external/login")
async def external_login(request: Request):
    """External system SSO callback / login verification endpoint"""
    # 1. Parse request parameters
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    external_id = data.get("external_id")
    
    # Ensure timestamp is integer
    try:
        timestamp = int(data.get("timestamp"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid timestamp")
        
    signature = data.get("signature")

    if not provider or not external_id or not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Missing required parameters: provider, external_id, timestamp, signature")

    # 2. Replay attack prevention (5 minutes validity)
    current_time = int(time.time())
    if abs(current_time - timestamp) > 300:
        raise HTTPException(status_code=401, detail="Request expired or timestamp invalid")

    # 3. Signature verification logic
    sign_string = f"provider={provider}&external_id={external_id}&timestamp={timestamp}"
    expected_signature = hmac.new(
        EXTERNAL_SSO_SECRET.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # 4. Check file mapping
    mappings = load_bindings()
    binding_record = find_binding_by_external(mappings, provider, external_id)

    if not binding_record:
        # No binding record found, return specific status code to guide user for manual binding
        raise HTTPException(status_code=403, detail="BINDING_REQUIRED")

    # 5. Generate CoApis local JWT Token / Session (community version lightweight token)
    local_user_id = binding_record["user_id"]
    
    # Here you would call your existing token generation logic
    # For community version, we return a simple success response with user_id
    return {
        "success": True, 
        "token": f"mock_jwt_token_for_{local_user_id}",
        "user_id": local_user_id,
        "message": "External identity login successful"
    }


@router.post("/users/identity/bind")
async def bind_external_identity(request: Request, current_user_id: str = None):
    """Manual binding endpoint for external identity"""
    if not current_user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    external_id = data.get("external_id")

    if not provider or not external_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: provider, external_id")

    mappings = load_bindings()
    
    # Check if the same external ID is already bound
    for b in mappings.get("bindings", []):
        if b.get("provider") == provider and b.get("external_id") == external_id:
            raise HTTPException(status_code=400, detail="External ID already bound to another account or exists.")

    # Add new binding record
    new_binding = {
        "user_id": current_user_id,
        "provider": provider,
        "external_id": external_id,
        "status": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    
    mappings.setdefault("bindings", []).append(new_binding)
    save_bindings_atomic(mappings)

    return {"success": True, "message": "Binding successful"}


@router.post("/users/identity/unbind")
async def unbind_external_identity(request: Request, current_user_id: str = None):
    """Manual unbinding endpoint for external identity"""
    if not current_user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    external_id = data.get("external_id")

    if not provider or not external_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: provider, external_id")

    mappings = load_bindings()
    updated_bindings = []
    found = False
    
    for b in mappings.get("bindings", []):
        if b.get("user_id") == current_user_id and b.get("provider") == provider and b.get("external_id") == external_id:
            # Unbind: remove the record from the list
            found = True
            continue  # Skip this record, do not add to updated_bindings
        updated_bindings.append(b)

    if not found:
        raise HTTPException(status_code=404, detail="Binding record not found")

    mappings["bindings"] = updated_bindings
    save_bindings_atomic(mappings)

    return {"success": True, "message": "Unbinding successful"}


@router.post("/external/auto-login")
async def auto_login_by_identifier(request: Request):
    """Auto login endpoint for external systems using openid or other identifier"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider = data.get("provider")
    openid = data.get("openid")  # optional parameter for compatibility
    
    if not provider:
        raise HTTPException(status_code=400, detail="Missing required parameter: provider")

    # Query identity mappings
    mappings_data = load_bindings()
    bindings = mappings_data.get("bindings", [])
    
    matched_binding = None
    
    # Support both 'openid' and generic 'identifier' or 'external_id' fields
    identifier = openid or data.get("identifier") or data.get("external_id")
    
    if not identifier:
        raise HTTPException(status_code=400, detail="Missing required parameter: openid or identifier")

    for b in bindings:
        if b.get("provider") == provider and str(b.get("external_id")) == str(identifier) and b.get("status") == 1:
            matched_binding = b
            break

    if not matched_binding:
        # Not found or status not active
        raise HTTPException(status_code=401, detail="Identity binding not found or inactive. Please bind first.")

    user_id = matched_binding.get("user_id")
    
    # Generate JWT Token using COAPIS_JWT_SECRET_KEY
    secret_key = os.getenv("COAPIS_JWT_SECRET_KEY") or EXTERNAL_SSO_SECRET
    
    if not secret_key:
        raise HTTPException(status_code=500, detail="JWT secret key not configured")

    payload = {
        "user_id": user_id,
        "provider": provider,
        "external_id": matched_binding.get("external_id"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24)
    }
    
    token = jwt.encode(payload, secret_key, algorithm="HS256")

    return {
        "success": True, 
        "message": "Auto-login successful",
        "data": {
            "token": token,
            "user_id": user_id,
            "provider": provider,
            "external_id": matched_binding.get("external_id")
        }
    }