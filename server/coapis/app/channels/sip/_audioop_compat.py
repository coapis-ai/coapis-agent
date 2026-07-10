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
