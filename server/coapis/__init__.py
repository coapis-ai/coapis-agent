# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

import logging
import os
import time

from .utils.logging import setup_logger

# Fallback before we can safely read canonical constant definitions.
LOG_LEVEL_ENV = "COAPIS_LOG_LEVEL"

_bootstrap_err: Exception | None = None
try:
    # Load persisted env vars before importing modules that read env-backed
    # constants at import time (e.g., WORKING_DIR).
    from .envs import load_envs_into_environ

    load_envs_into_environ()
except Exception as exc:
    # Best effort: package import should not fail if env bootstrap fails.
    _bootstrap_err = exc

_t0 = time.perf_counter()
setup_logger(os.environ.get(LOG_LEVEL_ENV, "info"))
if _bootstrap_err is not None:
    logging.getLogger(__name__).warning(
        "coapis: failed to load persisted envs on init: %s",
        _bootstrap_err,
    )
logging.getLogger(__name__).debug(
    "%.3fs package init",
    time.perf_counter() - _t0,
)
