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

"""
Version is read from the COAPIS_VERSION environment variable.

How to update:
  - Development (.env):        COAPIS_VERSION=0.8.26-dev
  - Production (.env.prod):    COAPIS_VERSION=0.8.25
  - Just change the env var when releasing a new version.
"""

import os

__version__ = os.environ.get("COAPIS_VERSION", "0.0.0-dev")
