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
