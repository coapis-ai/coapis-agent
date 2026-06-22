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

"""
Version is read from the COAPIS_VERSION environment variable.

How to update:
  - Development (.env):        COAPIS_VERSION=0.8.26-dev
  - Production (.env.prod):    COAPIS_VERSION=0.8.25
  - Just change the env var when releasing a new version.
"""

import os

__version__ = os.environ.get("COAPIS_VERSION", "0.0.0-dev")
