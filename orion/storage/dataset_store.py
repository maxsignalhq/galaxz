import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import aiofiles.os

from core.contracts import TrainingExample


class DatasetStore:
    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path)

    def _domain_path(self, domain: str) -> Path:
        return self._base / f"{domain}.jsonl"

    def _snapshot_path(self, domain: str, version: str) -> Path:
        return self._base / f"{domain}_{version}.jsonl"

    async def append_example(self, example: TrainingExample) -> None:
        await aiofiles.os.makedirs(self._base, exist_ok=True)
        path = self._domain_path(example.domain)
        line = example.model_dump_json() + "\n"
        async with aiofiles.open(path, mode="a", encoding="utf-8") as f:
            await f.write(line)

    async def get_domain_stats(self, domain: str) -> dict:
        path = self._domain_path(domain)
        count = 0
        human_correction_count = 0
        quality_sum = 0.0
        last_updated = None

        if path.exists():
            stat = await aiofiles.os.stat(path)
            last_updated = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

            async with aiofiles.open(path, encoding="utf-8") as f:
                async for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    count += 1
                    quality_sum += data.get("quality_score", 0.0)
                    if data.get("source") == "human_correction":
                        human_correction_count += 1

        return {
            "count": count,
            "human_correction_count": human_correction_count,
            "avg_quality_score": round(quality_sum / count, 4) if count else 0.0,
            "last_updated": last_updated,
            "file_path": str(path),
        }

    async def snapshot(self, domain: str, version: str) -> str:
        src = self._domain_path(domain)
        dst = self._snapshot_path(domain, version)
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.copy2, str(src), str(dst)
        )
        return str(dst)

    async def list_domains(self) -> list[str]:
        if not self._base.exists():
            return []
        entries = await aiofiles.os.listdir(self._base)
        return [
            Path(e).stem
            for e in entries
            if e.endswith(".jsonl") and "_" not in Path(e).stem
        ]
