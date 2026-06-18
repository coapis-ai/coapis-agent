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

"""audioop compatibility polyfill for Python 3.13+.

The ``audioop`` module was removed in Python 3.13 (PEP 594).
This shim imports the built-in module when available (<=3.12)
and falls back to the ``audioop-lts`` package on 3.13+.

The module is injected into ``sys.modules["audioop"]`` so that
third-party libraries (e.g. pyVoIP) that ``import audioop``
internally will also pick it up without modification.
"""
from __future__ import annotations

import sys

try:
    import audioop  # pylint: disable=deprecated-module
except ImportError:
    try:
        import audioop_lts as audioop  # type: ignore[no-redef]

        sys.modules["audioop"] = audioop
    except ImportError:
        raise ImportError(
            "The 'audioop' module was removed in Python 3.13. "
            "Please install the 'audioop-lts' package: "
            "pip install 'audioop-lts'",
        ) from None

__all__ = ["audioop"]
