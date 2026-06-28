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

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from .base import BaseJobRepository
from ..models import CronJobSpec, JobsFile

logger = logging.getLogger(__name__)


class JsonJobRepository(BaseJobRepository):
    """jobs.json repository (single-file storage).

    Notes:
    - Single-machine, no cross-process lock.
    - Atomic write: write tmp then replace.
    """

    def __init__(self, path: Path | str):
        if isinstance(path, str):
            path = Path(path)
        self._path = path.expanduser()

    @property
    def path(self) -> Path:
        return self._path

    async def load(self) -> JobsFile:
        if not self._path.exists():
            return JobsFile(version=1, jobs=[])

        data = json.loads(self._path.read_text(encoding="utf-8"))
        version = data.get("version", 1)
        raw_jobs = data.get("jobs", [])

        # Validate each job individually — skip malformed ones instead of failing all
        valid_jobs = []
        for i, raw in enumerate(raw_jobs):
            try:
                job = CronJobSpec.model_validate(raw)
                valid_jobs.append(job)
            except Exception as e:
                job_name = raw.get("name", f"index={i}")
                logger.warning(
                    "Skipping malformed cron job '%s' in %s: %s",
                    job_name, self._path, e,
                )

        return JobsFile(version=version, jobs=valid_jobs)

    async def save(self, jobs_file: JobsFile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = jobs_file.model_dump(mode="json")

        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(self._path))
