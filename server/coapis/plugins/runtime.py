# -*- coding: utf-8 -*-
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

"""Runtime helper functions for plugins."""

from typing import List
import logging

logger = logging.getLogger(__name__)


class RuntimeHelpers:
    """Runtime helper functions accessible to plugins."""

    def __init__(self, provider_manager=None):
        """Initialize runtime helpers.

        Args:
            provider_manager: ProviderManager instance
        """
        self.provider_manager = provider_manager

    def get_provider(self, provider_id: str):
        """Get provider instance.

        Args:
            provider_id: Provider identifier

        Returns:
            Provider instance or None
        """
        if self.provider_manager:
            return self.provider_manager.get_provider(provider_id)
        return None

    def list_providers(self) -> List[str]:
        """List all available providers.

        Returns:
            List of provider IDs
        """
        if self.provider_manager:
            return [p.id for p in self.provider_manager.list_providers()]
        return []

    def log_info(self, message: str):
        """Log info message.

        Args:
            message: Log message
        """
        logger.info(message)

    def log_error(self, message: str, exc_info=False):
        """Log error message.

        Args:
            message: Log message
            exc_info: Include exception info
        """
        logger.error(message, exc_info=exc_info)

    def log_debug(self, message: str):
        """Log debug message.

        Args:
            message: Log message
        """
        logger.debug(message)
