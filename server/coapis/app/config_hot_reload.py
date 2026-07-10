# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Config hot reload module - reload configuration without restarting the server.

Solves P0-4: Config changes require server restart.

Features:
- Watch config file for changes
- Automatic reload on file modification
- Manual reload via API endpoint
- Graceful error handling for invalid config
- Config diff tracking
"""

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)


class ConfigHotReloadManager:
    """Manages configuration hot reload functionality."""

    def __init__(
        self,
        config_path: str,
        reload_callbacks: Optional[List[Callable]] = None,
        poll_interval: float = 5.0,
    ):
        self.config_path = config_path
        self.reload_callbacks = reload_callbacks or []
        self.poll_interval = poll_interval
        self._current_hash: Optional[str] = None
        self._current_config: Dict[str, Any] = {}
        self._watch_thread: Optional[threading.Thread] = None
        self._running = False
        self._reload_history: List[Dict[str, Any]] = []

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            new_hash = self._compute_hash(config)
            
            if new_hash != self._current_hash:
                # Config changed
                old_config = self._current_config.copy()
                self._current_config = config
                self._current_hash = new_hash
                
                # Record reload event
                reload_event = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "old_hash": self._current_hash,
                    "new_hash": new_hash,
                    "source": "file_watch",
                }
                self._reload_history.append(reload_event)
                
                # Notify callbacks
                for callback in self.reload_callbacks:
                    try:
                        callback(config, old_config)
                    except Exception as e:
                        logger.error("Error in reload callback: %s", e)
                
                logger.info("Config reloaded from %s", self.config_path)
                
                return config
        except FileNotFoundError:
            logger.warning("Config file not found: %s", self.config_path)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in config file: %s", e)
        except Exception as e:
            logger.error("Error loading config: %s", e)
        
        return self._current_config

    def _compute_hash(self, config: Dict[str, Any]) -> str:
        """Compute hash of config for change detection."""
        config_str = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(config_str.encode()).hexdigest()

    def start_watching(self):
        """Start watching config file for changes."""
        if self._running:
            return
        
        self._running = True
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="config-watcher",
        )
        self._watch_thread.start()
        
        logger.info("Config file watcher started (poll interval: %ss)", self.poll_interval)

    def stop_watching(self):
        """Stop watching config file."""
        self._running = False
        if self._watch_thread:
            self._watch_thread.join(timeout=10)
            self._watch_thread = None
        
        logger.info("Config file watcher stopped")

    def _watch_loop(self):
        """Background loop that watches for config changes."""
        while self._running:
            time.sleep(self.poll_interval)
            self.load_config()

    def reload_manual(self) -> Dict[str, Any]:
        """Manually trigger config reload."""
        config = self.load_config()
        
        reload_event = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "manual_api",
        }
        self._reload_history.append(reload_event)
        
        return {
            "ok": True,
            "reloaded": True,
            "config": config,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current config status."""
        return {
            "config_path": self.config_path,
            "watching": self._running,
            "current_hash": self._current_hash,
            "reload_count": len(self._reload_history),
            "last_reload": self._reload_history[-1] if self._reload_history else None,
        }

    def get_reload_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get reload history."""
        return self._reload_history[-limit:]


# Global config manager instance (initialized in _app.py)
config_manager: Optional[ConfigHotReloadManager] = None


# ---- API Router ----

router = APIRouter(prefix="/config/reload", tags=["Config Hot Reload"])


@router.post("")
async def reload_config():
    """Manually reload configuration."""
    if config_manager is None:
        raise HTTPException(status_code=503, detail="Config hot reload not initialized")
    
    result = config_manager.reload_manual()
    return result


@router.get("/status")
async def get_config_status():
    """Get config hot reload status."""
    if config_manager is None:
        raise HTTPException(status_code=503, detail="Config hot reload not initialized")
    
    return config_manager.get_status()


@router.get("/history")
async def get_reload_history(limit: int = 10):
    """Get config reload history."""
    if config_manager is None:
        raise HTTPException(status_code=503, detail="Config hot reload not initialized")
    
    return config_manager.get_reload_history(limit)


def setup_config_hot_reload(
    config_path: str,
    reload_callbacks: Optional[List[Callable]] = None,
    poll_interval: float = 5.0,
) -> ConfigHotReloadManager:
    """Set up config hot reload functionality.

    Args:
        config_path: Path to config file to watch
        reload_callbacks: List of callbacks to call on config change
        poll_interval: How often to check for changes (seconds)

    Returns:
        ConfigHotReloadManager instance
    """
    global config_manager
    
    config_manager = ConfigHotReloadManager(
        config_path=config_path,
        reload_callbacks=reload_callbacks,
        poll_interval=poll_interval,
    )
    
    # Load initial config
    config_manager.load_config()
    
    # Start watching
    config_manager.start_watching()
    
    logger.info("Config hot reload enabled (P0-4): %s", config_path)
    
    return config_manager
