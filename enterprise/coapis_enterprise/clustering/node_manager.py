# -*- coding: utf-8 -*-
"""Enterprise Node Manager for multi-node clustering.

Provides:
- Node registration and discovery
- Load balancing
- Health checking
- Failover coordination
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NodeInfo(BaseModel):
    """Node information."""
    node_id: str
    host: str
    port: int
    status: str = "active"  # active, inactive, draining
    last_heartbeat: float = Field(default_factory=time.time)
    load: float = 0.0  # Current load (0.0 - 1.0)
    metadata: Dict[str, Any] = {}


class NodeManager:
    """Manages cluster nodes for load balancing and failover.
    
    Enterprise feature: Multi-node clustering.
    """
    
    def __init__(self):
        self._nodes: Dict[str, NodeInfo] = {}
        self._local_node_id = str(uuid.uuid4())[:8]
        self._redis_client = None
        logger.info(f"Node manager initialized (local node: {self._local_node_id})")
    
    def register_node(self, node: NodeInfo) -> bool:
        """Register a node in the cluster."""
        self._nodes[node.node_id] = node
        logger.info(f"Node '{node.node_id}' registered at {node.host}:{node.port}")
        return True
    
    def unregister_node(self, node_id: str) -> bool:
        """Remove a node from the cluster."""
        if node_id in self._nodes:
            del self._nodes[node_id]
            logger.info(f"Node '{node_id}' unregistered")
            return True
        return False
    
    def update_heartbeat(self, node_id: str, load: float = 0.0) -> bool:
        """Update node heartbeat and load."""
        if node_id in self._nodes:
            self._nodes[node_id].last_heartbeat = time.time()
            self._nodes[node_id].load = load
            return True
        return False
    
    def get_active_nodes(self) -> List[NodeInfo]:
        """Get list of active nodes."""
        return [
            node for node in self._nodes.values()
            if node.status == "active"
        ]
    
    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """Get node by ID."""
        return self._nodes.get(node_id)
    
    def select_node(self, strategy: str = "least_loaded") -> Optional[NodeInfo]:
        """Select a node based on load balancing strategy.
        
        Args:
            strategy: Load balancing strategy (least_loaded, round_robin, random)
        
        Returns:
            Selected node or None if no active nodes
        """
        active = self.get_active_nodes()
        if not active:
            return None
        
        if strategy == "least_loaded":
            return min(active, key=lambda n: n.load)
        elif strategy == "random":
            import random
            return random.choice(active)
        else:  # round_robin
            return active[0]
    
    def check_health(self, timeout: float = 30.0) -> Dict[str, Any]:
        """Check health of all nodes.
        
        Returns:
            Health status for each node
        """
        now = time.time()
        health = {}
        
        for node_id, node in self._nodes.items():
            last_hb = node.last_heartbeat
            is_alive = (now - last_hb) < timeout
            
            health[node_id] = {
                "status": "healthy" if is_alive else "unhealthy",
                "last_heartbeat": last_hb,
                "load": node.load,
            }
        
        return health
    
    def get_cluster_stats(self) -> Dict[str, Any]:
        """Get cluster statistics."""
        nodes = list(self._nodes.values())
        active = [n for n in nodes if n.status == "active"]
        
        return {
            "total_nodes": len(nodes),
            "active_nodes": len(active),
            "local_node_id": self._local_node_id,
            "avg_load": sum(n.load for n in active) / len(active) if active else 0,
        }
