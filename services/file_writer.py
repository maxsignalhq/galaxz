from pathlib import Path

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "javascript",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".txt": "text",
}


def infer_language_from_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return _EXT_TO_LANGUAGE.get(ext, "text")


class FileWriter:
    def __init__(self, workspace_root: str) -> None:
        root = Path(workspace_root).resolve()
        if not root.exists():
            raise FileNotFoundError(f"workspace_root does not exist: {root}")
        self.workspace_root = root

    def write(self, artifacts: list[dict], subdir: str | None = None) -> list[dict]:
        base = self.workspace_root / subdir if subdir else self.workspace_root
        results = []
        for artifact in artifacts:
            filename = artifact["filename"]
            full_path = base / filename
            result: dict = {
                "filename": filename,
                "path": str(full_path),
                "written": False,
                "artifact_type": artifact.get("artifact_type", ""),
                "language": artifact.get("language", ""),
                "error": None,
            }
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(artifact["content"], encoding="utf-8")
                result["written"] = True
            except Exception as exc:
                result["error"] = str(exc)
            results.append(result)
        return results
