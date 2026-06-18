# -*- coding: utf-8 -*-
"""Enterprise Clustering API Router.

Provides cluster management endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from coapis.app.auth import require_admin
from .node_manager import NodeManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cluster", tags=["enterprise-clustering"])

# Global node manager instance
_node_manager = NodeManager()


@router.get("/status")
async def get_cluster_status(request: Request) -> Dict[str, Any]:
    """Get cluster status.
    
    Enterprise feature: Multi-node clustering.
    """
    require_admin(request)
    
    return _node_manager.get_cluster_stats()


@router.get("/nodes")
async def list_nodes(request: Request) -> Dict[str, Any]:
    """List all nodes in the cluster.
    
    Enterprise feature: Multi-node clustering.
    """
    require_admin(request)
    
    nodes = [_node.model_dump() for _node in _node_manager._nodes.values()]
    
    return {
        "nodes": nodes,
        "total": len(nodes),
    }


@router.post("/nodes/{node_id}/drain")
async def drain_node(request: Request, node_id: str) -> Dict[str, Any]:
    """Start draining a node (stop accepting new connections).
    
    Enterprise feature: Node lifecycle management.
    """
    require_admin(request)
    
    node = _node_manager.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    
    node.status = "draining"
    
    return {
        "success": True,
        "message": f"Node '{node_id}' is now draining",
    }


@router.post("/nodes/{node_id}/activate")
async def activate_node(request: Request, node_id: str) -> Dict[str, Any]:
    """Activate a node (start accepting connections).
    
    Enterprise feature: Node lifecycle management.
    """
    require_admin(request)
    
    node = _node_manager.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    
    node.status = "active"
    
    return {
        "success": True,
        "message": f"Node '{node_id}' is now active",
    }


@router.get("/health")
async def check_cluster_health(request: Request) -> Dict[str, Any]:
    """Check health of all nodes.
    
    Enterprise feature: Cluster health monitoring.
    """
    require_admin(request)
    
    health = _node_manager.check_health()
    
    return {
        "health": health,
        "overall": "healthy" if all(h["status"] == "healthy" for h in health.values()) else "degraded",
    }
