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

"""Error handling middleware - user-friendly error messages.

Solves P0-3: Users see technical error messages instead of user-friendly ones.

Features:
- Catches technical exceptions and converts to user-friendly messages
- Preserves error details in logs for debugging
- Returns consistent error response format
- Supports error categorization (client_error, server_error, auth_error, etc.)
"""

import logging
import traceback
import uuid
from typing import Any, Dict

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

logger = logging.getLogger(__name__)

# Error category mappings
ERROR_CATEGORIES = {
    "client_error": {
        "code": "CLIENT_ERROR",
        "user_message": "Please check your input and try again.",
        "status_code": 400,
    },
    "auth_error": {
        "code": "AUTH_ERROR",
        "user_message": "Authentication required. Please log in.",
        "status_code": 401,
    },
    "permission_error": {
        "code": "PERMISSION_ERROR",
        "user_message": "You don't have permission to perform this action.",
        "status_code": 403,
    },
    "not_found": {
        "code": "NOT_FOUND",
        "user_message": "The requested resource was not found.",
        "status_code": 404,
    },
    "validation_error": {
        "code": "VALIDATION_ERROR",
        "user_message": "Some input fields are invalid. Please check and try again.",
        "status_code": 422,
    },
    "server_error": {
        "code": "SERVER_ERROR",
        "user_message": "An unexpected error occurred. Please try again later.",
        "status_code": 500,
    },
}


class UserFriendlyErrorMiddleware(BaseHTTPMiddleware):
    """Middleware that converts technical errors to user-friendly messages."""

    def __init__(self, app, show_details: bool = False):
        super().__init__(app)
        self.show_details = show_details  # Set True for debugging only

    async def dispatch(self, request: Request, call_next):
        try:
            # Try to get response from next handler
            response = await call_next(request)
            return response

        except RequestValidationError as e:
            # Handle Pydantic validation errors
            return self._handle_validation_error(e)

        except Exception as e:
            # Handle all other exceptions
            return await self._handle_exception(request, e)

    def _handle_validation_error(self, e: RequestValidationError) -> Response:
        """Handle validation errors with user-friendly messages."""
        # Log full error details
        logger.warning(
            "Validation error: %s",
            str(e.errors())[:500],  # Truncate for log
        )

        # Return user-friendly message
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "Some input fields are invalid. Please check and try again.",
                "details": e.errors() if self.show_details else None,
            },
        )

    async def _handle_exception(
        self, request: Request, e: Exception
    ) -> Response:
        """Handle unexpected exceptions with user-friendly messages."""
        # Generate error ID for tracking
        error_id = str(uuid.uuid4())[:8]

        # Get exception type and message
        exc_type = type(e).__name__
        exc_msg = str(e)

        # Log full error details with traceback
        logger.error(
            "Error [%s]: %s: %s\n%s",
            error_id,
            exc_type,
            exc_msg,
            traceback.format_exc(),
        )

        # Determine error category
        category = self._categorize_error(e)
        category_info = ERROR_CATEGORIES.get(category, ERROR_CATEGORIES["server_error"])

        # Build response
        response_content = {
            "error": category_info["code"],
            "message": category_info["user_message"],
            "error_id": error_id,
        }

        # Add details if debugging enabled
        if self.show_details:
            response_content["details"] = {
                "type": exc_type,
                "message": exc_msg,
            }

        # Return user-friendly response
        return JSONResponse(
            status_code=category_info["status_code"],
            content=response_content,
        )

    def _categorize_error(self, e: Exception) -> str:
        """Categorize an exception for appropriate user message."""
        # Authentication errors
        if "auth" in type(e).__name__.lower() or "token" in str(e).lower():
            return "auth_error"

        # Permission errors
        if "permission" in type(e).__name__.lower() or "forbidden" in str(e).lower():
            return "permission_error"

        # Not found errors
        if "not found" in str(e).lower() or "404" in str(e):
            return "not_found"

        # Client errors (4xx)
        if hasattr(e, "status_code") and 400 <= e.status_code < 500:
            return "client_error"

        # Server errors (5xx or unexpected)
        return "server_error"


def setup_error_handling(app: FastAPI, show_details: bool = False):
    """Set up user-friendly error handling for the app.

    Args:
        app: FastAPI app instance
        show_details: If True, include technical details in error responses (debug only)
    """
    app.add_middleware(UserFriendlyErrorMiddleware, show_details=show_details)

    # Add custom exception handlers for common cases
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "Some input fields are invalid. Please check and try again.",
                "details": exc.errors() if show_details else None,
            },
        )

    logger.info("User-friendly error handling enabled")
