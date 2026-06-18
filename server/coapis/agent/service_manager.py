# -*- coding: utf-8 -*-
"""ServiceManager — 声明式服务生命周期管理。

借鉴 CoApis ServiceManager + ServiceDescriptor 模式，
为 CoApis workspace 提供统一的服务注册、优先级排序、并发初始化、
依赖管理和组件复用能力。

用法:
    sm = ServiceManager(workspace)
    sm.register(ServiceDescriptor(
        name="memory",
        factory=lambda ws: MemoryManager(ws.workspace_dir),
        start_method="start",
        stop_method="stop",
        priority=10,
    ))
    await sm.start_all()
    await sm.stop_all()
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


@dataclass
class ServiceDescriptor:
    """服务声明 — 描述一个可管理的服务组件。

    Attributes:
        name: 唯一标识符 (e.g. "memory", "channel_manager")
        factory: 工厂函数 f(workspace) -> instance
        start_method: 启动时调用的方法名 (e.g. "start")
        stop_method: 停止时调用的方法名 (e.g. "stop")
        post_init: 创建后调用的钩子 f(workspace, instance)
        dependencies: 必须先启动的服务列表
        priority: 启动优先级 (越小越先启动，同优先级并发)
        concurrent: 同优先级内是否并发初始化
        reusable: 是否支持跨 reload 复用实例
        attr_name: 设置到 workspace 上的属性名 (默认 = name)
    """

    name: str
    factory: Optional[Callable[["Workspace"], Any]] = None
    start_method: Optional[str] = None
    stop_method: Optional[str] = None
    post_init: Optional[Callable[["Workspace", Any], Any]] = None
    dependencies: List[str] = field(default_factory=list)
    priority: int = 100
    concurrent: bool = True
    reusable: bool = False
    attr_name: Optional[str] = None


class ServiceManager:
    """声明式服务生命周期管理器。

    功能:
    - 按优先级分组启动服务
    - 同优先级并发初始化
    - 依赖检查
    - 优雅停止 (逆序)
    - 组件复用 (reusable)
    - 启动耗时统计
    """

    def __init__(self, workspace: "Workspace"):
        self.workspace = workspace
        self._descriptors: Dict[str, ServiceDescriptor] = {}
        self._instances: Dict[str, Any] = {}
        self._reused: Set[str] = set()
        self._started = False

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, descriptor: ServiceDescriptor) -> None:
        """注册一个服务声明。"""
        if descriptor.name in self._descriptors:
            logger.warning(
                "Service '%s' already registered, overwriting",
                descriptor.name,
            )
        self._descriptors[descriptor.name] = descriptor

    def register_batch(self, descriptors: List[ServiceDescriptor]) -> None:
        """批量注册服务声明。"""
        for d in descriptors:
            self.register(d)

    # ------------------------------------------------------------------
    # 复用
    # ------------------------------------------------------------------

    async def set_reusable(self, name: str, instance: Any) -> None:
        """标记一个实例为复用的（跨 reload）。"""
        if name not in self._descriptors:
            logger.warning("Unknown service '%s', cannot mark as reusable", name)
            return
        if not self._descriptors[name].reusable:
            logger.warning("Service '%s' is not marked as reusable", name)
            return
        self._instances[name] = instance
        self._reused.add(name)
        attr = self._descriptors[name].attr_name or name
        setattr(self.workspace, attr, instance)

    def get_reusable_services(self) -> Dict[str, Any]:
        """获取所有可复用的服务实例。"""
        return {
            name: self._instances[name]
            for name, desc in self._descriptors.items()
            if desc.reusable and name in self._instances
        }

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """按优先级顺序启动所有已注册服务。"""
        if self._started:
            return

        groups = self._group_by_priority()
        import time as _time
        total_t0 = _time.monotonic()

        for priority in sorted(groups.keys()):
            group = groups[priority]
            concurrent = [d for d in group if d.concurrent]
            sequential = [d for d in group if not d.concurrent]

            # 并发启动
            if concurrent:
                await asyncio.gather(
                    *(self._init_service(d) for d in concurrent),
                )

            # 顺序启动
            for d in sequential:
                await self._init_service(d)

        self._started = True
        total_elapsed = _time.monotonic() - total_t0
        logger.info(
            "ServiceManager: all %d services started in %.2fs",
            len(self._instances),
            total_elapsed,
        )

    async def _init_service(self, desc: ServiceDescriptor) -> None:
        """初始化并启动单个服务。"""
        import time as _time

        # 跳过复用的服务
        if desc.name in self._reused:
            logger.debug("Service '%s' reusing previous instance", desc.name)
            return

        # 依赖检查
        for dep in desc.dependencies:
            if dep not in self._instances:
                raise RuntimeError(
                    f"Service '{desc.name}' depends on '{dep}', "
                    f"but '{dep}' is not initialized"
                )

        t0 = _time.monotonic()
        try:
            # 工厂创建
            if desc.factory is None:
                raise ValueError(f"Service '{desc.name}' has no factory")

            instance = desc.factory(self.workspace)
            if asyncio.iscoroutine(instance):
                instance = await instance

            self._instances[desc.name] = instance
            attr = desc.attr_name or desc.name
            setattr(self.workspace, attr, instance)

            # post_init 钩子
            if desc.post_init:
                result = desc.post_init(self.workspace, instance)
                if asyncio.iscoroutine(result):
                    await result

            # start 方法
            if desc.start_method:
                method = getattr(instance, desc.start_method, None)
                if method:
                    result = method()
                    if asyncio.iscoroutine(result):
                        await result

            elapsed = _time.monotonic() - t0
            logger.info(
                "Service '%s' started in %.2fs", desc.name, elapsed,
            )

        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.error(
                "Service '%s' failed after %.2fs: %s",
                desc.name, elapsed, e,
                exc_info=True,
            )
            raise

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------

    async def stop_all(self) -> None:
        """按优先级逆序停止所有服务。"""
        if not self._started:
            return

        groups = self._group_by_priority()
        for priority in sorted(groups.keys(), reverse=True):
            group = groups[priority]
            for desc in reversed(group):
                if desc.name in self._reused:
                    continue  # 复用的实例不负责停止
                instance = self._instances.get(desc.name)
                if instance and desc.stop_method:
                    method = getattr(instance, desc.stop_method, None)
                    if method:
                        try:
                            result = method()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.warning(
                                "Error stopping '%s': %s",
                                desc.name, e,
                            )

        self._started = False
        logger.info("ServiceManager: all services stopped")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, name: str) -> Any:
        """获取已启动的服务实例。"""
        return self._instances.get(name)

    def get_state(self) -> Dict[str, Any]:
        """获取所有服务的状态摘要。"""
        return {
            name: {
                "started": name in self._instances,
                "reused": name in self._reused,
                "priority": desc.priority,
                "attr_name": desc.attr_name or desc.name,
            }
            for name, desc in self._descriptors.items()
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _group_by_priority(self) -> Dict[int, List[ServiceDescriptor]]:
        """按优先级分组。"""
        groups: Dict[int, List[ServiceDescriptor]] = {}
        for desc in self._descriptors.values():
            groups.setdefault(desc.priority, []).append(desc)
        return groups
