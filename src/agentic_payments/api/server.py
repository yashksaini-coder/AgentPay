"""Trio-native REST/WebSocket API server using Quart + Hypercorn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
import trio
from quart_trio import QuartTrio

from agentic_payments.api.routes import register_routes

if TYPE_CHECKING:
    from agentic_payments.config import APIConfig

logger = structlog.get_logger(__name__)


def create_app(node: Any) -> QuartTrio:
    """Create a Quart application with all routes registered."""
    app = QuartTrio(__name__)
    app.config["node"] = node
    register_routes(app)

    # CORS: restrict to known frontend origins to prevent CSRF
    allowed_origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }

    @app.after_request
    async def add_cors_headers(response: Any) -> Any:
        from quart import request as quart_request

        origin = quart_request.headers.get("Origin", "")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        if response.status_code == 405 and quart_request.method == "OPTIONS":
            response.status_code = 204
        return response

    return app


async def serve_api(
    config: APIConfig,
    node: Any,
    task_status: Any = trio.TASK_STATUS_IGNORED,
) -> None:
    """Start the API server using Hypercorn with trio worker."""
    from hypercorn.config import Config as HyperConfig
    from hypercorn.trio import serve

    app = create_app(node)

    hyper_config = HyperConfig()
    hyper_config.bind = [f"{config.host}:{config.port}"]
    hyper_config.accesslog = "-"

    logger.info("api_server_starting", host=config.host, port=config.port)
    task_status.started()
    await serve(app, hyper_config)
