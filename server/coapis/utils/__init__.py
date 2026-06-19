# -*- coding: utf-8 -*-
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

from .system_info import (
    get_architecture,
    get_cuda_version,
    get_memory_size_gb,
    get_os_name,
    get_system_info,
    get_vram_size_gb,
)

__all__ = [
    "get_architecture",
    "get_cuda_version",
    "get_memory_size_gb",
    "get_os_name",
    "get_system_info",
    "get_vram_size_gb",
]
