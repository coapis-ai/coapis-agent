# -*- coding: utf-8 -*-
"""External Systems Admin Management Router - Community Version (JSON File Storage)

Provides API endpoints for admin to manage external system configurations and identity bindings.
"""
import json
import os
import tempfile
import shutil
import time
from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any, List, Optional

# Mapping file paths
from ...constant import SYSTEM_DIR

# 与 users.json/auth.json 同一运行时数据目录（避免相对路径受 CWD 影响）
SYSTEMS_CONFIG_FILE = str(SYSTEM_DIR / "external_systems_config.json")
MAPPINGS_FILE = str(SYSTEM_DIR / "external_identity_mappings.json")

router_admin = APIRouter(prefix="/admin", tags=["external_systems_admin"])


def load_systems_config() -> Dict[str, Any]:
    """Safely read local external systems config JSON file"""
    if not os.path.exists(SYSTEMS_CONFIG_FILE):
        return {"systems": []}
    with open(SYSTEMS_CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"systems": []}


def save_systems_config_atomic(config_data: Dict[str, Any]):
    """Atomically write back external systems config JSON file to prevent concurrent overwrite"""
    dir_name = os.path.dirname(SYSTEMS_CONFIG_FILE) or "."
    fd, temp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        shutil.move(temp_path, SYSTEMS_CONFIG_FILE)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def load_bindings() -> Dict[str, Any]:
    """Safely read local identity mappings JSON file"""
    if not os.path.exists(MAPPINGS_FILE):
        return {"bindings": []}
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"bindings": []}


def save_bindings_atomic(mappings_data: Dict[str, Any]):
    """Atomically write back identity mappings JSON file to prevent concurrent overwrite"""
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


@router_admin.get("/external-systems/config")
async def get_external_systems_config():
    """Get list of configured external systems"""
    config_data = load_systems_config()
    return {
        "success": True,
        "data": config_data.get("systems", [])
    }


def _check_base_url_overlap(
    new_base_urls: List[str],
    existing_systems: List[Dict[str, Any]],
    current_provider_id: str,
) -> Optional[str]:
    """Check if new base_urls overlap with *other* systems' base_urls.

    Overlap = two base URLs are identical, or one is a path-prefix of the
    other (e.g. ``https://oa.corp.com`` vs ``https://oa.corp.com/finance``).
    Such configurations are ambiguous — the intent is unclear even though
    longest-prefix-match would pick one — so we block them at save time.

    Returns an error message string if overlap is found, None if OK.
    """
    for other_sys in existing_systems:
        if other_sys.get("provider_id") == current_provider_id:
            continue  # skip self when updating
        for other_base in (other_sys.get("base_urls") or []):
            other_base = (other_base or "").rstrip("/")
            if not other_base:
                continue
            other_name = other_sys.get("name", other_sys.get("provider_id", "?"))
            for new_base in new_base_urls:
                new_base = (new_base or "").rstrip("/")
                if not new_base:
                    continue
                if new_base == other_base:
                    return (
                        f"base_url 冲突: '{new_base}' 与系统 "
                        f"[{other_name}] 的 '{other_base}' 完全相同，"
                        f"无法区分归属"
                    )
                if new_base.startswith(other_base + "/") or other_base.startswith(new_base + "/"):
                    return (
                        f"base_url 冲突: '{new_base}' 与系统 "
                        f"[{other_name}] 的 '{other_base}' 前缀重叠，"
                        f"请改用不同的域名或路径"
                    )
    return None


@router_admin.post("/external-systems/config")
async def save_external_systems_config(request: Request):
    """Add or update an external system configuration"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    provider_id = data.get("provider_id")
    name = data.get("name")
    client_id = data.get("client_id", "")
    shared_secret_use_global = data.get("shared_secret_use_global", True)
    shared_secret = data.get("shared_secret", "") if not shared_secret_use_global else ""
    status = data.get("status", 1)
    # 登录方式（新 schema）：sso_redirect(A) | credential(B) | none
    login_type = data.get("login_type") or ""
    # 模型A：SSO 跳转配置块
    sso_cfg = data.get("sso")
    if not isinstance(sso_cfg, dict):
        sso_cfg = {}
    # 模型B：凭证直登配置块（二期实现，schema 先就位）
    credential_cfg = data.get("credential")
    if not isinstance(credential_cfg, dict):
        credential_cfg = {}
    # 用户映射：自动建用户配置块
    user_mapping_cfg = data.get("user_mapping")
    if not isinstance(user_mapping_cfg, dict):
        user_mapping_cfg = {}
    # 登录页展示项
    icon = data.get("icon", "")
    description = data.get("description", "")
    show_on_login = data.get("show_on_login", True)
    try:
        display_order = int(data.get("display_order") or 100)
    except (TypeError, ValueError):
        display_order = 100
    # Outbound identity assertion: which URLs belong to this external system
    # (prefix list, e.g. ["https://oa.example.com"]). Only matched outbound
    # requests carry the signed identity (see app/external_identity.py).
    base_urls = data.get("base_urls", [])
    if not isinstance(base_urls, list):
        base_urls = [base_urls] if isinstance(base_urls, str) else []
    base_urls = [str(u).rstrip("/") for u in base_urls if u]
    # Identity assertion validity in seconds (default 60 min, adjustable)
    try:
        identity_token_ttl = int(data.get("identity_token_ttl") or 3600)
    except (TypeError, ValueError):
        identity_token_ttl = 3600

    if not provider_id or not name:
        raise HTTPException(status_code=400, detail="provider_id and name are required")

    config_data = load_systems_config()
    systems = config_data.get("systems", [])

    # Check if provider_id exists, update if so, else append
    found_index = -1
    for i, sys in enumerate(systems):
        if sys.get("provider_id") == provider_id:
            found_index = i
            break

    new_system_config = {
        "provider_id": provider_id,
        "name": name,
        # 登录方式与展示（新 schema）
        "login_type": login_type,
        "sso": sso_cfg,
        "credential": credential_cfg,
        "user_mapping": user_mapping_cfg,
        "icon": icon,
        "description": description,
        "show_on_login": show_on_login,
        "display_order": display_order,
        # 出站身份断言（现有字段，原样保留）
        "client_id": client_id,
        "shared_secret_use_global": shared_secret_use_global,
        "shared_secret": shared_secret,
        "base_urls": base_urls,
        "identity_token_ttl": identity_token_ttl,
        "status": status,
    }

    if found_index >= 0:
        # 更新：只校验**新增**的 base_urls（已有的重叠是历史遗留，不阻塞更新）
        old_base_urls = systems[found_index].get("base_urls") or []
        new_only = [u for u in base_urls if u not in old_base_urls]
        overlap_err = _check_base_url_overlap(new_only, systems, provider_id)
    else:
        # 创建：校验全部 base_urls
        overlap_err = _check_base_url_overlap(base_urls, systems, provider_id)
    if overlap_err:
        raise HTTPException(status_code=409, detail=overlap_err)

    if found_index >= 0:
        systems[found_index] = new_system_config
    else:
        systems.append(new_system_config)

    config_data["systems"] = systems
    save_systems_config_atomic(config_data)

    return {
        "success": True,
        "message": "External system configuration saved successfully",
        "data": new_system_config
    }


@router_admin.delete("/external-systems/config/{provider_id}")
async def delete_external_systems_config(provider_id: str):
    """Delete an external system configuration"""
    config_data = load_systems_config()
    systems = config_data.get("systems", [])

    updated_systems = [sys for sys in systems if sys.get("provider_id") != provider_id]

    if len(updated_systems) == len(systems):
        raise HTTPException(status_code=404, detail="External system configuration not found")

    config_data["systems"] = updated_systems
    save_systems_config_atomic(config_data)

    return {
        "success": True,
        "message": "External system configuration deleted successfully"
    }


@router_admin.get("/users/identity-bindings")
async def get_identity_bindings(provider: Optional[str] = None, user_id: Optional[str] = None):
    """Get all identity binding records with optional filtering"""
    mappings_data = load_bindings()
    bindings = mappings_data.get("bindings", [])

    if provider:
        bindings = [b for b in bindings if b.get("provider") == provider]
    
    if user_id:
        bindings = [b for b in bindings if b.get("user_id") == user_id]

    return {
        "success": True,
        "data": bindings
    }


@router_admin.post("/users/identity-bindings/bind")
async def bind_external_identity_admin(request: Request):
    """Manual binding endpoint for external identity (Admin version)"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    user_id = data.get("user_id")
    provider = data.get("provider")
    external_id = data.get("external_id")
    external_name = str(data.get("external_name") or "").strip() or None

    if not user_id or not provider or not external_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: user_id, provider, external_id")

    mappings_data = load_bindings()
    
    # Check if the same external ID is already bound to a different user or exists
    for b in mappings_data.get("bindings", []):
        if b.get("provider") == provider and b.get("external_id") == external_id:
            if b.get("user_id") != user_id:
                raise HTTPException(status_code=400, detail="External ID already bound to another account.")
            # If bound to the same user, just update status or return success
            if b.get("status") != 1:
                b["status"] = 1
                b["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                save_bindings_atomic(mappings_data)
            return {"success": True, "message": "Binding already exists and is active."}

    # Add new binding record
    new_binding = {
        "user_id": user_id,
        "provider": provider,
        "external_id": external_id,
        "external_name": external_name,
        "source": "manual",
        "status": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    
    mappings_data.setdefault("bindings", []).append(new_binding)
    save_bindings_atomic(mappings_data)

    return {"success": True, "message": "Admin binding successful"}


@router_admin.post("/users/identity-bindings/unbind")
async def unbind_external_identity_admin(request: Request):
    """Manual unbinding endpoint for external identity (Admin version)"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    user_id = data.get("user_id")
    provider = data.get("provider")
    external_id = data.get("external_id")
    external_name = str(data.get("external_name") or "").strip() or None

    if not user_id or not provider or not external_id:
        raise HTTPException(status_code=400, detail="Missing required parameters: user_id, provider, external_id")

    mappings_data = load_bindings()
    updated_bindings = []
    found = False
    
    for b in mappings_data.get("bindings", []):
        if b.get("user_id") == user_id and b.get("provider") == provider and b.get("external_id") == external_id:
            # Unbind: remove the record from the list
            found = True
            continue  # Skip this record, do not add to updated_bindings
        updated_bindings.append(b)

    if not found:
        raise HTTPException(status_code=404, detail="Binding record not found")

    mappings_data["bindings"] = updated_bindings
    save_bindings_atomic(mappings_data)

    return {"success": True, "message": "Admin unbinding successful"}


@router_admin.post("/users/identity-bindings/import-batch")
async def import_batch_identity_mappings(request: Request):
    """Batch import identity mapping records (user_id <-> external_id mappings)"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    bindings_input = data.get("bindings", [])
    
    if not isinstance(bindings_input, list) or len(bindings_input) == 0:
        raise HTTPException(status_code=400, detail="Invalid 'bindings' array: must be a non-empty list")

    mappings_data = load_bindings()
    existing_bindings = mappings_data.get("bindings", [])
    
    success_count = 0
    failed_count = 0
    errors = []

    for idx, item in enumerate(bindings_input):
        user_id = item.get("user_id")
        provider = item.get("provider")
        external_id = item.get("external_id")

        if not user_id or not provider or not external_id:
            failed_count += 1
            errors.append(f"Row {idx + 1}: Missing required parameters (user_id, provider, or external_id)")
            continue

        # Check if the same external ID is already bound to a different user or exists
        existing_match = None
        for b in existing_bindings:
            if b.get("provider") == provider and b.get("external_id") == external_id:
                existing_match = b
                break

        if existing_match:
            if existing_match.get("user_id") != user_id:
                # External ID already bound to another user
                failed_count += 1
                errors.append(f"Row {idx + 1}: External ID '{external_id}' for provider '{provider}' is already bound to user '{existing_match['user_id']}'.")
            else:
                # Already bound to the same user, update status if needed
                if existing_match.get("status") != 1:
                    existing_match["status"] = 1
                    existing_match["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                success_count += 1
        else:
            # Add new binding record
            new_binding = {
                "user_id": user_id,
                "provider": provider,
                "external_id": external_id,
                "external_name": str(item.get("external_name") or "").strip() or None,
                "source": "manual",
                "status": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            existing_bindings.append(new_binding)
            success_count += 1

    # Save updated bindings if there were changes
    if success_count > 0 or failed_count == 0:
        mappings_data["bindings"] = existing_bindings
        save_bindings_atomic(mappings_data)

    return {
        "success": True,
        "message": f"Batch import completed. Success: {success_count}, Failed: {failed_count}",
        "stats": {
            "success_count": success_count,
            "failed_count": failed_count,
            "errors": errors if len(errors) > 0 else None
        }
    }
