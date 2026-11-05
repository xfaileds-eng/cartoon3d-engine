"""Sổ tài sản: nạp registry, tra tài sản, kiểm giấy phép, nạp file .json của tài sản."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    kind: str
    source: str
    license: str
    commercial_ok: bool
    redistribute_ok: bool
    path: str
    version: int

    @property
    def abs_path(self) -> Path:
        return config.REPO_ROOT / self.path


class RegistryError(KeyError):
    pass


class Registry:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.REGISTRY_PATH)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.records: dict[str, AssetRecord] = {}
        for row in data["assets"]:
            rec = AssetRecord(**{k: row[k] for k in AssetRecord.__dataclass_fields__})
            if rec.asset_id in self.records:
                raise RegistryError(f"asset_id trùng trong registry: {rec.asset_id}")
            self.records[rec.asset_id] = rec

    def get(self, asset_id: str) -> AssetRecord:
        try:
            return self.records[asset_id]
        except KeyError:
            raise RegistryError(f"tài sản '{asset_id}' không có trong assets/registry.json") from None

    def require(self, asset_id: str, kind: str | None = None) -> AssetRecord:
        """Tài sản phải có trong sổ, đúng loại, được dùng thương mại và file tồn tại (G2)."""
        rec = self.get(asset_id)
        if kind and rec.kind != kind:
            raise RegistryError(f"'{asset_id}' là {rec.kind}, không phải {kind}")
        if not rec.commercial_ok:
            raise RegistryError(f"'{asset_id}' có commercial_ok = false, bị chặn vào render")
        if not rec.abs_path.exists():
            raise RegistryError(f"'{asset_id}' trỏ tới file không tồn tại: {rec.path}")
        return rec

    def load(self, asset_id: str, kind: str | None = None) -> dict[str, Any]:
        rec = self.require(asset_id, kind)
        data = json.loads(rec.abs_path.read_text(encoding="utf-8"))
        if data.get("asset_id") != asset_id:
            raise RegistryError(f"file {rec.path} khai asset_id '{data.get('asset_id')}' ≠ '{asset_id}'")
        return data

    def all_rows(self) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8"))["assets"]


def load_style(style_id: str) -> dict[str, Any]:
    path = config.STYLES_DIR / f"{style_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"không có phong cách '{style_id}' trong styles/")
    return json.loads(path.read_text(encoding="utf-8"))
