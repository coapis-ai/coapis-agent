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

"""Re-export audit logger from canonical location.

This module exists to support legacy import paths (``from .audit_logger import
AuditLogger`` inside ``agents/security/``) while keeping the **single**
singleton in ``coapis.agent.security.audit_logger``.

All classes and functions are re-exported so existing callers need zero changes.
"""

from ...agent.security.audit_logger import (  # noqa: F401
    AuditEvent,
    AuditLogger,
    create_audit_event,
)
