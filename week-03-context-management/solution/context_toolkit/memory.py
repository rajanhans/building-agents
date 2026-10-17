"""The drawer: notes kept outside the window. The model decides what to write; we host the files."""

from pathlib import Path


class FileMemory:
    def __init__(self, root: Path | str = "memories"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, p: str) -> Path:
        full = (self.root / p.strip().lstrip("/").removeprefix("memories/")).resolve()
        if not full.is_relative_to(self.root):
            raise PermissionError(f"'{p}' is outside the memory folder")
        return full

    def handle(self, command: str, path: str = "", text: str = "", query: str = "") -> str:
        if command == "view":
            target = self._path(path or ".")
            if target.is_dir():                        # the whole drawer: every note, with its content
                notes = [f"## {f.relative_to(self.root)}\n{f.read_text(encoding='utf-8')[:1000]}"
                         for f in sorted(target.rglob("*")) if f.is_file()]
                return "\n\n".join(notes) or "(memory is empty)"
            return target.read_text(encoding="utf-8") if target.exists() else f"No memory file '{path}'."
        if command == "write":
            target = self._path(path)
            if target == self.root:
                raise ValueError("write needs a file name")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return f"Saved {target.relative_to(self.root)}"
        if command == "search":
            hits = [f"{f.relative_to(self.root)}: {line}" for f in sorted(self.root.rglob("*")) if f.is_file()
                    for line in f.read_text(encoding="utf-8").splitlines() if query.lower() in line.lower()]
            return "\n".join(hits) or "(no matches)"
        if command == "delete":
            self._path(path).unlink(missing_ok=True)
            return f"Deleted {path}"
        raise ValueError("command must be view, write, search or delete")
