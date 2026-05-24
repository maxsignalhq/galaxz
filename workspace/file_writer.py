from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

_STOP_WORDS = {
    "a", "an", "the", "to", "for", "of", "in", "on", "at",
    "with", "and", "or", "is", "are", "that", "this", "it",
    "be", "as", "by", "from", "into",
}


class WrittenArtifact(BaseModel):
    filename: str
    absolute_path: str
    relative_path: str
    size_bytes: int = Field(ge=0)


class FileWriter:
    def __init__(self, workspace_root: str) -> None:
        self._root = Path(workspace_root)

    def write(self, filename: str, content: str) -> WrittenArtifact:
        full_path = (self._root / filename).resolve()
        if not full_path.is_relative_to(self._root.resolve()):
            raise ValueError(f"filename escapes workspace root: {filename!r}")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return WrittenArtifact(
            filename=filename,
            absolute_path=str(full_path),
            relative_path=filename,
            size_bytes=len(content.encode("utf-8")),
        )

    def infer_filename(self, task_description: str, skill: str) -> str:
        words = task_description.lower().split()
        filtered = [
            re.sub(r"[^a-z0-9]", "", w)
            for w in words
            if w not in _STOP_WORDS
        ]
        filtered = [w for w in filtered if w]
        slug = "_".join(filtered)[:40].rstrip("_")

        if not slug:
            return f"output_{skill}.py"

        if skill == "test_writing":
            return f"test_{slug}.py"
        return f"{slug}.py"
