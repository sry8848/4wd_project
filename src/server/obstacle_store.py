"""Persist obstacle metadata and photos without introducing a database."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.server.schemas import ObstacleRecordResponse


OBSTACLE_ID_RE = re.compile(r"^obstacle_[0-9]{8}_[0-9]{6}_[0-9]{6}_[A-E][1-5]_[A-E][1-5]$")
RECOVERED = "recovered"
RECOVERY_FAILED = "recovery_failed"
VALID_STATUSES = (RECOVERED, RECOVERY_FAILED)


class ObstacleStoreError(RuntimeError):
    """表示障碍记录文件不符合当前持久化契约。"""


class ObstacleStore:
    """保存并重新读取 JPEG 与同名 JSON 障碍记录。

    参数说明：
    root_dir: 障碍 JSON 和 JPEG 的唯一目录。
    now_fn: 返回带时区 datetime 的函数，默认使用当前 UTC 时间。
    """

    def __init__(
        self,
        root_dir,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.root_dir = Path(root_dir)
        self._now = now_fn if now_fn is not None else _utc_now

    def prepare_record(self, from_point: str, to_point: str) -> Tuple[str, str, Path]:
        """生成本次记录 ID、创建时间和目标 JPEG 路径。

        分步逻辑：读取一次当前时间，用同一时间生成 ID 和展示时间，再返回
        摄像头应写入的唯一 JPEG 路径。
        """

        now = self._now()
        if now.tzinfo is None:
            raise ObstacleStoreError("障碍记录时间必须包含时区")
        record_id = (
            f"obstacle_{now.strftime('%Y%m%d_%H%M%S_%f')}_"
            f"{from_point}_{to_point}"
        )
        return record_id, now.isoformat(), self.root_dir / f"{record_id}.jpg"

    def save_record(
        self,
        *,
        record_id: str,
        ride_id: str,
        created_at: str,
        from_point: str,
        to_point: str,
        distance_cm: float,
        recovered_point: Optional[str],
        status: str,
        image_filename: Optional[str],
        capture_error: Optional[str],
    ) -> ObstacleRecordResponse:
        """严格按固定字段保存一条障碍 JSON，并返回前端响应。"""

        self._validate_id(record_id)
        if status not in VALID_STATUSES:
            raise ObstacleStoreError(f"不支持的障碍状态: {status}")
        if image_filename is not None and Path(image_filename).name != image_filename:
            raise ObstacleStoreError("image_filename 只能是障碍目录内的文件名")

        payload = {
            "id": record_id,
            "ride_id": ride_id,
            "created_at": created_at,
            "from_point": from_point,
            "to_point": to_point,
            "distance_cm": float(distance_cm),
            "recovered_point": recovered_point,
            "status": status,
            "image_filename": image_filename,
            "capture_error": capture_error,
        }
        self.root_dir.mkdir(parents=True, exist_ok=True)
        target = self.root_dir / f"{record_id}.json"
        temporary = self.root_dir / f"{record_id}.json.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return self._to_response(payload)

    def list_records(self) -> List[ObstacleRecordResponse]:
        """从磁盘读取全部障碍 JSON，并按时间倒序返回。"""

        if not self.root_dir.exists():
            return []
        records = [self._load_file(path) for path in self.root_dir.glob("obstacle_*.json")]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def get_image_path(self, record_id: str) -> Path:
        """返回已登记且真实存在的障碍 JPEG 路径。"""

        self._validate_id(record_id)
        json_path = self.root_dir / f"{record_id}.json"
        if not json_path.is_file():
            raise FileNotFoundError(f"障碍记录不存在: {record_id}")
        payload = self._read_payload(json_path)
        filename = payload["image_filename"]
        if filename is None:
            raise FileNotFoundError(f"障碍记录没有真实照片: {record_id}")
        image_path = self.root_dir / filename
        if not image_path.is_file():
            raise FileNotFoundError(f"障碍照片文件不存在: {record_id}")
        return image_path

    def _load_file(self, path: Path) -> ObstacleRecordResponse:
        payload = self._read_payload(path)
        self._validate_id(payload["id"])
        if path.name != f"{payload['id']}.json":
            raise ObstacleStoreError(f"障碍记录文件名与 id 不一致: {path.name}")
        return self._to_response(payload)

    def _read_payload(self, path: Path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ObstacleStoreError(f"无法读取障碍记录: {path.name}") from exc

        required_fields = {
            "id",
            "ride_id",
            "created_at",
            "from_point",
            "to_point",
            "distance_cm",
            "recovered_point",
            "status",
            "image_filename",
            "capture_error",
        }
        if not isinstance(payload, dict) or set(payload) != required_fields:
            raise ObstacleStoreError(f"障碍记录字段不符合契约: {path.name}")
        if payload["status"] not in VALID_STATUSES:
            raise ObstacleStoreError(f"障碍记录状态不符合契约: {path.name}")
        filename = payload["image_filename"]
        if filename is not None and Path(filename).name != filename:
            raise ObstacleStoreError(f"障碍照片文件名不安全: {path.name}")
        return payload

    def _to_response(self, payload) -> ObstacleRecordResponse:
        filename = payload["image_filename"]
        image_path = self.root_dir / filename if filename is not None else None
        image_url = (
            f"/api/obstacles/{payload['id']}/image"
            if image_path is not None and image_path.is_file()
            else None
        )
        capture_error = payload["capture_error"]
        if filename is not None and image_url is None:
            capture_error = "障碍照片文件不存在"
        return ObstacleRecordResponse(
            id=payload["id"],
            ride_id=payload["ride_id"],
            created_at=payload["created_at"],
            from_point=payload["from_point"],
            to_point=payload["to_point"],
            distance_cm=float(payload["distance_cm"]),
            recovered_point=payload["recovered_point"],
            status=payload["status"],
            image_url=image_url,
            capture_error=capture_error,
        )

    @staticmethod
    def _validate_id(record_id: str):
        if not isinstance(record_id, str) or not OBSTACLE_ID_RE.fullmatch(record_id):
            raise ObstacleStoreError("障碍记录 ID 不符合契约")


def _utc_now():
    return datetime.now(timezone.utc)
