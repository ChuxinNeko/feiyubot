"""进程内唯一的飞鱼服务：数据库、模型路由和对话管道。"""

from __future__ import annotations

import os
from pathlib import Path

from feiyubot.core.llm import ChatBackend, HttpxBackend, ProviderRouter
from feiyubot.core.pipeline import Pipeline
from feiyubot.core.store import Store

_SERVICE: Service | None = None


class Service:
    def __init__(self, store: Store, backend: ChatBackend, data_dir: Path):
        self.store = store
        self.backend = backend
        self.data_dir = data_dir
        self.router = ProviderRouter(store, backend)
        self.pipeline = Pipeline(store, self.router)

    @classmethod
    def open(
        cls,
        data_dir: Path,
        *,
        admin_password: str | None = None,
        backend: ChatBackend | None = None,
    ) -> Service:
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(data_dir / "feiyu.sqlite")
        store.ensure_defaults(admin_password, data_dir / "admin_password.txt")
        return cls(store, backend or HttpxBackend(), data_dir)

    async def aclose(self) -> None:
        await self.backend.aclose()
        self.store.close()


def init_service(data_dir: Path | None = None, *, admin_password: str | None = None, backend: ChatBackend | None = None) -> Service:
    global _SERVICE
    directory = data_dir or Path(os.environ.get("FEIYU_DATA_DIR", "data"))
    password = admin_password if admin_password is not None else os.environ.get("FEIYU_ADMIN_PASSWORD")
    _SERVICE = Service.open(directory, admin_password=password or None, backend=backend)
    return _SERVICE


def get_service() -> Service:
    if _SERVICE is None:
        raise RuntimeError("飞鱼还没启动")
    return _SERVICE


def read_runtime(data_dir: Path) -> dict[str, str]:
    path = Path(data_dir) / "runtime.env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def write_runtime(data_dir: Path, updates: dict[str, str | None]) -> None:
    path = Path(data_dir) / "runtime.env"
    current = read_runtime(data_dir)
    for key, value in updates.items():
        if value is None or value == "":
            current.pop(key, None)
        else:
            if "\n" in value or "\r" in value:
                raise ValueError("配置不能包含换行")
            current[key] = value
    lines = [f"{key}={current[key]}" for key in sorted(current)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
