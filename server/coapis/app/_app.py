# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# pylint: disable=redefined-outer-name,unused-argument
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import inspect
import asyncio
import mimetypes
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from agentscope_runtime.engine.app import AgentApp
from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ..config import load_config  # pylint: disable=no-name-in-module
from ..config.utils import get_config_path
from ..constant import (
    DOCS_ENABLED,
    LOG_LEVEL_ENV,
    CORS_ORIGINS,
    WORKING_DIR,
    PROJECT_NAME,
    DATA_DIR,
    WORKSPACES_DIR,
)
from ..__version__ import __version__
from ..utils.logging import (
    setup_logger,
    add_project_file_handler,
    LOG_FILE_PATH,
)
from ..utils.system_info import summarize_python_environment
from .routers import router as api_router
from .routers.agent_scoped import AgentContextMiddleware
from ..envs import load_envs_into_environ
from ..providers.provider_manager import ProviderManager
from ..local_models.manager import LocalModelManager
from .multi_agent_manager import MultiAgentManager
from .migration import (
    migrate_legacy_workspace_to_default_agent,
    migrate_legacy_skills_to_skill_pool,
    ensure_default_agent_exists,
    ensure_qa_agent_exists,
    ensure_global_templates_exist,
    ensure_global_agent_roles,
    ensure_layered_templates,
)
from .channels.registry import register_custom_channel_routes
from ..user_system.middleware import (
    install_user_context_middleware,
    install_user_isolation_middleware,
    install_quota_check_middleware,
    install_rate_limit_middleware,
)
from .auth_middleware import install_auth_middleware  # Async-compatible SSE middleware

# Apply log level on load so reload child process gets same level as CLI.
logger = setup_logger(os.environ.get(LOG_LEVEL_ENV, "info"))

# Ensure static assets are served with browser-compatible MIME types across
# platforms (notably Windows may miss .js/.mjs mappings).
mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")

# Load persisted env vars into os.environ at module import time
# so they are available before the lifespan starts.
load_envs_into_environ()


# ═══════════════════════════════════════════════════════════
# Enterprise Plugin Loading
# ═══════════════════════════════════════════════════════════


def _load_enterprise_routes(app: FastAPI) -> None:
    """Load enterprise routes if enterprise package is installed.
    
    This function attempts to import the coapis-enterprise package.
    If successful, it registers the enterprise routes and plugin.
    If not, it logs a message and the stub routes handle upgrade prompts.
    
    Args:
        app: FastAPI application instance
    """
    try:
        from coapis_enterprise import get_routers, register_plugin
        
        routers = get_routers()
        for router in routers:
            app.include_router(router, prefix="/api")
        
        register_plugin()
        logger.info("Enterprise routes loaded (%d routers)", len(routers))
        
    except ImportError:
        logger.info("Enterprise package not installed - running Community edition")
        # Enterprise stub routes already registered - they handle upgrade prompts


# Dynamic runner that selects the correct workspace runner based on request
class DynamicMultiAgentRunner:
    """Runner wrapper that dynamically routes to the correct workspace runner.

    This allows AgentApp to work with multiple agents by inspecting
    the X-Agent-Id header on each request.
    """

    def __init__(self):
        self.framework_type = "agentscope"
        self._multi_agent_manager = None

    def set_multi_agent_manager(self, manager):
        """Set the MultiAgentManager instance after initialization."""
        self._multi_agent_manager = manager

    async def _get_workspace(self, request):
        """Get the correct workspace based on request.

        Returns:
            Workspace: The workspace instance for the current agent.
        """
        from .agent_context import get_current_agent_id

        # Get agent_id from context (set by middleware or header)
        agent_id = get_current_agent_id()

        logger.debug(f"_get_workspace: agent_id={agent_id}")

        # Get the correct workspace
        if not self._multi_agent_manager:
            raise RuntimeError("MultiAgentManager not initialized")

        try:
            # Get username from request state (set by AuthMiddleware)
            # request may be Starlette Request, AgentRequest (Pydantic), or dict
            state = getattr(request, "state", None)
            username = getattr(state, "username", None) if state else None
            # Fallback: dict requests (e.g. from cron executor) use user_id
            if not username and isinstance(request, dict):
                username = request.get("user_id")
            workspace = await self._multi_agent_manager.get_agent(agent_id, username=username)
            logger.debug(
                "Got workspace: %s, runner: %s",
                workspace.agent_id,
                workspace.runner,
            )
            return workspace
        except (ValueError, AppBaseException) as e:
            logger.error(f"Agent not found: {e}")
            raise
        except Exception as e:
            logger.error(
                f"Error getting workspace: {e}",
                exc_info=True,
            )
            raise

    async def _get_workspace_runner(self, request):
        """Get the correct workspace runner based on request."""
        workspace = await self._get_workspace(request)
        return workspace.runner

    async def stream_query(self, request, *args, **kwargs):
        """Dynamically route to the correct workspace runner.

        Registers the task with the workspace's TaskTracker so that
        graceful shutdown during agent reload can detect in-flight
        background tasks (fixes #3275).
        """
        logger.debug("DynamicMultiAgentRunner.stream_query called")
        workspace = None
        run_key = None
        try:
            workspace = await self._get_workspace(request)
            runner = workspace.runner
            logger.debug(f"Got runner: {runner}, type: {type(runner)}")

            # Register this task with the workspace's TaskTracker so
            # _graceful_stop_old_instance() can see it during reload.
            run_key = f"ext-{uuid.uuid4().hex}"
            await workspace.task_tracker.register_external_task(run_key)

            # Delegate to the actual runner's stream_query generator
            count = 0
            async for item in runner.stream_query(request, *args, **kwargs):
                count += 1
                logger.debug(f"Yielding item #{count}: {type(item)}")
                yield item
            logger.debug(f"stream_query completed, yielded {count} items")
        except Exception as e:
            logger.error(
                f"Error in stream_query: {e}",
                exc_info=True,
            )
            # Yield error message to client
            yield {
                "error": str(e),
                "type": "error",
            }
        finally:
            # Always unregister the task when done (success, error,
            # or cancellation).
            if workspace is not None and run_key is not None:
                await workspace.task_tracker.unregister_external_task(run_key)

    async def query_handler(self, request, *args, **kwargs):
        """Dynamically route to the correct workspace runner.

        Registers the task with the workspace's TaskTracker so that
        graceful shutdown during agent reload can detect in-flight
        requests (fixes #3275).
        """
        workspace = None
        run_key = None
        try:
            workspace = await self._get_workspace(request)
            runner = workspace.runner

            run_key = f"ext-{uuid.uuid4().hex}"
            await workspace.task_tracker.register_external_task(run_key)

            async for item in runner.query_handler(request, *args, **kwargs):
                yield item
        finally:
            # Always unregister the task when done (success, error,
            # or cancellation).
            if workspace is not None and run_key is not None:
                await workspace.task_tracker.unregister_external_task(run_key)

    # Async context manager support for AgentApp lifecycle
    async def __aenter__(self):
        """
        No-op context manager entry (workspaces manage their own runners).
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """No-op context manager exit (workspaces manage their own runners)."""
        return None


# Import A2A config types for AgentCard
from agentscope_runtime.engine.deployers.adapter.a2a.a2a_protocol_adapter import (
    AgentCard,
    AgentCardWithRuntimeConfig,
    AgentCapabilities,
    AgentSkill,
)

# Use dynamic runner for AgentApp
runner = DynamicMultiAgentRunner()

agent_app = AgentApp(
    app_name="Friday",
    app_description="A helpful assistant with background task support",
    runner=runner,
    enable_stream_task=True,
    stream_task_queue="stream_query",
    stream_task_timeout=300,
)

# Disable A2A protocol adapter (not needed for CoApis)
# This avoids AgentCard validation errors in newer agentscope_runtime versions
agent_app.protocol_adapters = []


@asynccontextmanager
async def lifespan(  # pylint: disable=too-many-statements,too-many-statements
    app: FastAPI,
):
    startup_start_time = time.time()
    add_project_file_handler(LOG_FILE_PATH)

    # ── Startup state tracking ────────────────────────────────────
    import asyncio as _aio
    app.state.startup_phase = "sync"          # "sync" → "background" → "ready"
    app.state.startup_ready = _aio.Event()    # set when Phase 2 completes
    app.state.startup_start_time = startup_start_time
    app.state.startup_errors: list = []

    # ================================================================
    # Phase 1: Fast synchronous setup (target < 100ms)
    # Everything here must be lightweight so the server starts quickly.
    # ================================================================

    from .auth import auto_register_from_env

    auto_register_from_env()

    try:
        from ..utils.telemetry import (
            collect_and_upload_telemetry,
            has_telemetry_been_collected,
            is_telemetry_opted_out,
        )

        if not is_telemetry_opted_out(
            WORKING_DIR,
        ) and not has_telemetry_been_collected(WORKING_DIR):
            collect_and_upload_telemetry(WORKING_DIR)
    except Exception:
        logger.debug(
            "Telemetry collection skipped due to error",
            exc_info=True,
        )

    logger.debug("Checking for legacy config migration...")
    migrate_legacy_workspace_to_default_agent()
    ensure_default_agent_exists()
    migrate_legacy_skills_to_skill_pool()
    ensure_qa_agent_exists()
    ensure_global_templates_exist()
    ensure_global_agent_roles()
    ensure_layered_templates()

    # Create core managers (instant — no I/O)
    logger.debug("Initializing MultiAgentManager...")
    multi_agent_manager = MultiAgentManager(base_dir=WORKSPACES_DIR)
    provider_manager = ProviderManager.get_instance()
    local_model_manager = LocalModelManager.get_instance()

    # Start token usage manager background tasks
    logger.debug("Starting TokenUsageManager background tasks...")
    from ..token_usage import get_token_usage_manager

    token_usage_manager = get_token_usage_manager()
    token_usage_manager.start(flush_interval=10)

    # Initialize CronManagerRegistry (per-user, stored in workspaces/{username}/crons/)
    logger.debug("Initializing CronManagerRegistry...")
    from .crons.registry import CronManagerRegistry
    cron_registry = CronManagerRegistry(
        runner=runner,
        agent_id="global_default",
    )
    
    # Initialize PermissionManager (config-driven, supports hot-reload)
    logger.debug("Initializing PermissionManager...")
    from .permissions import PermissionManager
    from ..constant import SYSTEM_DIR
    permissions_config_path = SYSTEM_DIR / "permissions.json"
    PermissionManager.initialize(str(permissions_config_path))
    
    # Initialize AuditLogger (structured audit logging for security events)
    # Audit log stored at WORKING_DIR/audit_log/ — mount as Docker volume for persistence
    logger.debug("Initializing AuditLogger...")
    from ..agents.security.audit_logger import AuditLogger
    from ..constant import AUDIT_LOG_DIR
    audit_log_path = AUDIT_LOG_DIR / "audit.jsonl"
    AuditLogger.initialize(str(audit_log_path))
    
    # Initialize Commercial Security Modules (only if enterprise package is installed)
    logger.debug("Checking for enterprise security modules...")
    
    # Import lightweight license manager (always available)
    from ..license_manager_lite import license_manager
    
    try:
        from coapis_enterprise import get_routers, register_plugin
        from coapis_enterprise.license.manager import license_manager as enterprise_license_manager
        
        logger.info("Enterprise package detected - initializing security modules...")
        
        # Use enterprise license manager
        license_manager = enterprise_license_manager
        
        # Get configuration from environment variables
        online_validation_url = os.environ.get("COAPIS_LICENSE_VALIDATION_URL", "")
        online_validation_interval = float(os.environ.get("COAPIS_LICENSE_VALIDATION_INTERVAL", "24"))
        clock_grace_period = float(os.environ.get("COAPIS_CLOCK_GRACE_PERIOD", "300"))
        revocation_grace_period = float(os.environ.get("COAPIS_REVOCATION_GRACE_PERIOD", "24"))
        
        license_manager.init_security_modules(
            online_validation_url=online_validation_url,
            online_validation_interval=online_validation_interval,
            clock_grace_period=clock_grace_period,
            revocation_grace_period=revocation_grace_period,
        )
        logger.info("Security modules initialized successfully")
    except ImportError:
        logger.info("Enterprise package not installed - using lightweight license manager")
    except AttributeError:
        logger.info("Enterprise security modules not available - using lightweight license manager")
    
    # Initialize CrossAgentEvolution engine (global singleton for multi-layer evolution)
    logger.debug("Initializing CrossAgentEvolution engine...")
    from ..evolution.cross_agent_evolution import CrossAgentEvolution, CrossAgentEvolutionConfig
    from ..constant import SYSTEM_DIR
    cross_agent_config = CrossAgentEvolutionConfig()
    cross_agent_evolution = CrossAgentEvolution(
        config=cross_agent_config,
        data_dir=SYSTEM_DIR / "evolution",
    )
    
    # Expose to endpoints (must be set before first request arrives)
    app.state.multi_agent_manager = multi_agent_manager
    app.state.provider_manager = provider_manager
    app.state.local_model_manager = local_model_manager
    app.state.cron_registry = cron_registry
    app.state.cross_agent_evolution = cross_agent_evolution
    app.state.plugin_loader = None
    app.state.plugin_registry = None
    app.state.license_manager = license_manager

    if isinstance(runner, DynamicMultiAgentRunner):
        runner.set_multi_agent_manager(multi_agent_manager)

    async def _get_agent_by_id(agent_id: str = None, username: str = None):
        """Get agent instance by ID, or active agent if not specified.
        
        Args:
            agent_id: Agent ID (defaults to active_agent from config)
            username: Owner username (None for global agents)
        """
        if agent_id is None:
            config = load_config(get_config_path())
            agent_id = config.agents.active_agent or "global_default"
        return await multi_agent_manager.get_agent(agent_id, username=username)

    app.state.get_agent_by_id = _get_agent_by_id

    fast_elapsed = time.time() - startup_start_time
    logger.info(
        f"Server ready in {fast_elapsed:.3f}s "
        f"(agents loading in background)",
    )
    app.state.startup_phase = "background"
    app.state.phase1_elapsed = fast_elapsed

    # ================================================================
    # Phase 2: Background heavy initialization
    # Agents, plugins, and services start in a background task so the
    # server can begin accepting HTTP requests immediately.
    # First API requests that need an agent will await its readiness
    # via MultiAgentManager.get_agent() lazy-loading / event wait.
    # ================================================================

    async def _background_startup():  # pylint: disable=too-many-statements
        try:
            # Start all configured agents (truly parallel now)
            await multi_agent_manager.start_all_configured_agents()

            provider_manager.start_local_model_resume(local_model_manager)

            # ---- Plugin System ----
            logger.debug("Initializing plugin system...")

            from ..plugins.loader import PluginLoader
            from ..plugins.runtime import RuntimeHelpers
            from ..config.utils import get_plugins_dir

            plugin_dirs = [
                get_plugins_dir(),
            ]

            plugin_loader = PluginLoader(plugin_dirs)

            config = load_config(get_config_path())
            plugin_configs = (
                config.plugins if hasattr(config, "plugins") else {}
            )
            logger.debug(
                f"Loading plugins with {len(plugin_configs)} config(s)",
            )

            loaded_plugins = await plugin_loader.load_all_plugins(
                configs=plugin_configs,
            )
            logger.debug(f"Loaded {len(loaded_plugins)} plugin(s)")

            runtime_helpers = RuntimeHelpers(
                provider_manager=provider_manager,
            )
            plugin_loader.registry.set_runtime_helpers(runtime_helpers)

            for (
                provider_id,
                provider_reg,
            ) in plugin_loader.registry.get_all_providers().items():
                provider_manager.register_plugin_provider(
                    provider_id=provider_id,
                    provider_class=provider_reg.provider_class,
                    label=provider_reg.label,
                    base_url=provider_reg.base_url,
                    metadata=provider_reg.metadata,
                )
                logger.debug(
                    f"Registered plugin provider: {provider_id}",
                )

            app.state.plugin_loader = plugin_loader
            app.state.plugin_registry = plugin_loader.registry

            # ---- Plugin Control Commands ----
            logger.debug("Registering plugin control commands...")
            from ..app.runner.control_commands import register_command
            from ..app.channels.command_registry import CommandRegistry

            command_registry = CommandRegistry()

            control_commands = plugin_loader.registry.get_control_commands()
            for cmd_reg in control_commands:
                try:
                    register_command(cmd_reg.handler)

                    command_registry.register_command(
                        f"/{cmd_reg.handler.command_name}",
                        priority_level=cmd_reg.priority_level,
                    )

                    logger.debug(
                        f"Registered plugin control command: "
                        f"/{cmd_reg.handler.command_name} "
                        f"from plugin '{cmd_reg.plugin_id}' (priority"
                        f"={cmd_reg.priority_level})",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to register control command "
                        f"'{cmd_reg.handler.command_name}' "
                        f"from plugin '{cmd_reg.plugin_id}': {e}",
                        exc_info=True,
                    )

            # ---- Startup Hooks ----
            logger.debug("Executing plugin startup hooks...")
            startup_hooks = plugin_loader.registry.get_startup_hooks()
            for hook in startup_hooks:
                try:
                    logger.debug(
                        f"Executing startup hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}' "
                        f"(priority={hook.priority})",
                    )

                    result = hook.callback()
                    if inspect.iscoroutine(
                        result,
                    ) or inspect.isawaitable(result):
                        await result

                    logger.debug(
                        f"Completed startup hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}'",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to execute startup hook "
                        f"'{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}': {e}",
                        exc_info=True,
                    )

            # ---- Approval Service ----
            try:
                default_agent = await multi_agent_manager.get_agent(
                    "global_default",
                )
                if default_agent.channel_manager:
                    from .approvals import get_approval_service

                    get_approval_service().set_channel_manager(
                        default_agent.channel_manager,
                    )
            except Exception as e:
                logger.warning(f"Approval service setup skipped: {e}")

            startup_elapsed = time.time() - startup_start_time
            logger.info(
                "Background startup completed in "
                f"{startup_elapsed:.3f} seconds",
            )
            app.state.startup_phase = "ready"
            app.state.startup_elapsed = startup_elapsed
            app.state.startup_ready.set()

            # Print server URL again so it's visible after background logs
            from ..config.utils import read_last_api
            from ..utils.startup_display import print_ready_banner

            api_info = read_last_api()
            print_ready_banner(api_info, startup_elapsed)
        except Exception:
            logger.error(
                "Background startup encountered an error",
                exc_info=True,
            )
            app.state.startup_phase = "error"
            app.state.startup_ready.set()  # unwait even on error
            app.state.startup_errors.append("background startup failed")

    _bg_task = asyncio.create_task(_background_startup())

    try:
        yield
    finally:
        # Cancel background startup if still in progress
        if not _bg_task.done():
            _bg_task.cancel()
            with suppress(asyncio.CancelledError):
                await _bg_task

        # ==================== Execute Shutdown Hooks ====================
        plugin_registry = getattr(app.state, "plugin_registry", None)
        if plugin_registry is not None:
            logger.info("Executing plugin shutdown hooks...")
            shutdown_hooks = plugin_registry.get_shutdown_hooks()
            for hook in shutdown_hooks:
                try:
                    logger.info(
                        f"Executing shutdown hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}' (priority"
                        f"={hook.priority})",
                    )

                    result = hook.callback()
                    if inspect.iscoroutine(result) or inspect.isawaitable(
                        result,
                    ):
                        await result

                    logger.info(
                        f"✓ Completed shutdown hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}'",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to execute shutdown hook "
                        f"'{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}': {e}",
                        exc_info=True,
                    )

        local_model_mgr = getattr(app.state, "local_model_manager", None)
        if local_model_mgr is not None:
            logger.info("Stopping local model server...")
            try:
                await local_model_mgr.shutdown_server()
            except Exception as exc:
                logger.error(
                    "Error shutting down local model server gracefully: %s",
                    exc,
                )
                with suppress(OSError, RuntimeError, ValueError):
                    local_model_mgr.shutdown_server_sync()

        # Stop multi-agent manager (stops all agents and their components)
        multi_agent_mgr = getattr(app.state, "multi_agent_manager", None)
        if multi_agent_mgr is not None:
            logger.info("Stopping MultiAgentManager...")
            try:
                await multi_agent_mgr.stop_all()
            except Exception as e:
                logger.error(f"Error stopping MultiAgentManager: {e}")

        # Stop token usage manager (drain queue and final flush)
        logger.info("Stopping TokenUsageManager...")
        try:
            await token_usage_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping TokenUsageManager: {e}")

        logger.info("Application shutdown complete")


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

# User system middleware
# NOTE: FastAPI middleware is LIFO (last added = first executed)
# Execution order must be: Auth → RateLimit → QuotaCheck → UserIsolation → UserContext
# Therefore registration order (LIFO): UserContext → UserIsolation → QuotaCheck → RateLimit → Auth
# All middleware now use @app.middleware("http") pattern for SSE compatibility

# Register in LIFO order (last registered = first executed)
# Auth MUST execute first to set request.state.username
install_user_context_middleware(app)
install_user_isolation_middleware(app)
install_quota_check_middleware(app)
install_rate_limit_middleware(app)
install_auth_middleware(app)
logger.info("User system middleware enabled (async-compatible @app.middleware pattern)")

# Apply CORS middleware if CORS_ORIGINS is set
if CORS_ORIGINS:
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

# Apply path compatibility middleware for legacy frontend paths
from .routers.path_compat import PathCompatibilityMiddleware
app.add_middleware(PathCompatibilityMiddleware)
logger.info("Path compatibility middleware enabled (legacy frontend path remapping)")

# Apply user-friendly error handling
from .error_handler import setup_error_handling
setup_error_handling(app, show_details=False)
logger.info("User-friendly error handling enabled (P0-3)")


_CONSOLE_STATIC_ENV = "COAPIS_CONSOLE_STATIC_DIR"


def _resolve_console_static_dir() -> str:
    from ..constant import EnvVarLoader

    static_dir = EnvVarLoader.get_str(_CONSOLE_STATIC_ENV)
    if static_dir:
        return static_dir
    # Shipped dist lives in the package as static data
    pkg_dir = Path(__file__).resolve().parent.parent
    candidate = pkg_dir / "console"
    if candidate.is_dir() and (candidate / "index.html").exists():
        return str(candidate)

    # Fallback to repo data
    repo_dir = pkg_dir.parent.parent
    candidate = repo_dir / "console" / "dist"
    if candidate.is_dir() and (candidate / "index.html").exists():
        return str(candidate)

    # Fallback to cwd data
    cwd = Path(os.getcwd())
    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").exists():
            return str(candidate)

    fallback = cwd / "console" / "dist"
    logger.warning(
        f"Console static directory not found. Falling back to '{fallback}'.",
    )
    return str(fallback)


_CONSOLE_STATIC_DIR = _resolve_console_static_dir()
_CONSOLE_INDEX = (
    Path(_CONSOLE_STATIC_DIR) / "index.html" if _CONSOLE_STATIC_DIR else None
)
logger.info(f"STATIC_DIR: {_CONSOLE_STATIC_DIR}")


@app.get("/")
def read_root():
    if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
        return FileResponse(_CONSOLE_INDEX)
    return {
        "message": (
            f"{PROJECT_NAME} web console is not available. "
            "If you installed the project from source code, please run "
            "`npm ci && npm run build` in the `console/` "
            f"directory, and restart {PROJECT_NAME} to enable the "
            "web console."
        ),
    }


@app.get("/api/version")
def get_version():
    """Return the current application version (public-safe payload)."""
    return {
        "version": __version__,
    }


@app.get("/api/doctor/runtime")
def get_doctor_runtime():
    """Return server runtime diagnostics for authenticated troubleshooting."""
    return {
        "python_executable": sys.executable,
        "python_environment": summarize_python_environment(),
    }


# ═══════════════════════════════════════════════════════════════════════
# 路由注册 — 大部分路由已在 routers/__init__.py 统一注册到 api_router，
# _app.py 只需挂载 api_router + 少量需要特殊处理的子应用。
# ═══════════════════════════════════════════════════════════════════════

# 主 API 路由（包含所有常规端点）
app.include_router(api_router, prefix="/api")

# Agent 子应用 — SSE 长连接 + 独立 lifespan，必须单独挂载
app.include_router(
    agent_app.router,
    prefix="/api/agent",
    tags=["agent"],
)

logger.info("All API routes registered via unified api_router + agent sub-app")

# Load enterprise plugin routes (if enterprise package is installed)
_load_enterprise_routes(app)

# Custom channel routes (before SPA catch-all to ensure route priority)
register_custom_channel_routes(app)

# Console static files and SPA fallback
# Register these AFTER API routes to ensure proper routing priority
if os.path.isdir(_CONSOLE_STATIC_DIR):
    _console_path = Path(_CONSOLE_STATIC_DIR)

    def _serve_console_index():
        if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
            return FileResponse(_CONSOLE_INDEX)

        raise HTTPException(status_code=404, detail="Not Found")

    _assets_dir = _console_path / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    @app.get("/console")
    @app.get("/console/")
    @app.get("/console/{full_path:path}")
    def _console_spa_alias(full_path: str = ""):
        _ = full_path
        return _serve_console_index()

    # SPA fallback: catch-all route for frontend routing
    # Must be registered AFTER all API routes to avoid conflicts
    @app.get("/{full_path:path}")
    def _console_spa(full_path: str):
        # Prevent catching common system/special paths
        if full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Skip API routes (should already be matched due to registration order)
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")

        # Serve static files from the console build directory (e.g. logo SVGs,
        # favicons, images placed in public/).  Only serve regular files whose
        # path does not escape the console directory.
        if full_path and ".." not in full_path:
            static_file = _console_path / full_path
            if static_file.is_file():
                return FileResponse(static_file)

        return _serve_console_index()
