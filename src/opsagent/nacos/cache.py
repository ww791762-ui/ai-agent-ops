import json
from pathlib import Path


class FileCache:
    """把最后一次成功从 Nacos 拉取的内容存到本地，供 Nacos 不可用时兜底。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _paths(self, kind: str, key: str) -> tuple[Path, Path]:
        # key 可能包含点号（如 ops.reflect.inrun），不能用 with_suffix，否则不同 key 会撞名
        base = self._root / kind / key.replace("/", "_")
        return Path(f"{base}.bin"), Path(f"{base}.json")

    def save(self, kind: str, key: str, data: bytes, meta: dict) -> None:
        data_path, meta_path = self._paths(kind, key)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_bytes(data)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def load(self, kind: str, key: str) -> tuple[bytes, dict] | None:
        data_path, meta_path = self._paths(kind, key)
        if not data_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return data_path.read_bytes(), meta
