"""Persist obstacle metadata and photos without introducing a database."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.algorithms.qr_detect import QR_IDENTIFIER_PATTERN
from src.server.schemas import ObstacleRecordResponse
from src.tasks.obstacle_visual_classification import (
    CLASSIFICATION_FAILED,
    CLASSIFICATION_SUCCESS,
    OBSTACLE_TYPE_ORDINARY,
    OBSTACLE_TYPE_TOLL,
    VALID_RECOGNITION_ERRORS,
)


OBSTACLE_ID_RE = re.compile(
    r"^obstacle_[0-9]{8}_[0-9]{6}_[0-9]{6}_"
    r"(?P<from_point>[A-E][1-5])_(?P<to_point>[A-E][1-5])$"
)
RECOVERED = "recovered"
RECOVERY_FAILED = "recovery_failed"
HANDLING_CONTINUED_CURRENT_EDGE = "continued_current_edge"
HANDLING_BLOCKED_AND_REPLANNED = "blocked_and_replanned"
HANDLING_CANCELED_AFTER_RECOVERY = "canceled_after_recovery"
HANDLING_RECOVERY_FAILED = "recovery_failed"
VALID_HANDLING_RESULTS = (
    HANDLING_CONTINUED_CURRENT_EDGE,
    HANDLING_BLOCKED_AND_REPLANNED,
    HANDLING_CANCELED_AFTER_RECOVERY,
    HANDLING_RECOVERY_FAILED,
)
VALID_RECOVERY_STATUSES = (RECOVERED, RECOVERY_FAILED, None)
POINT_RE = re.compile(r"^[A-E][1-5]$")


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
        obstacle_type: str,
        detected_color: Optional[str],
        classification_status: str,
        station_id: Optional[str],
        recognition_error: Optional[str],
        handling_result: str,
        recovery_status: Optional[str],
        recovered_point: Optional[str],
        image_filename: Optional[str],
        capture_error: Optional[str],
    ) -> ObstacleRecordResponse:
        """严格按固定字段保存一条障碍 JSON，并返回前端响应。"""

        self._validate_id(record_id)
        payload = {
            "id": record_id,
            "ride_id": ride_id,
            "created_at": created_at,
            "from_point": from_point,
            "to_point": to_point,
            "distance_cm": float(distance_cm),
            "obstacle_type": obstacle_type,
            "detected_color": detected_color,
            "classification_status": classification_status,
            "station_id": station_id,
            "recognition_error": recognition_error,
            "handling_result": handling_result,
            "recovery_status": recovery_status,
            "recovered_point": recovered_point,
            "image_filename": image_filename,
            "capture_error": capture_error,
        }
        self._validate_payload(payload, "待保存记录")
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
            "obstacle_type",
            "detected_color",
            "classification_status",
            "station_id",
            "recognition_error",
            "handling_result",
            "recovery_status",
            "recovered_point",
            "image_filename",
            "capture_error",
        }
        if not isinstance(payload, dict) or set(payload) != required_fields:
            raise ObstacleStoreError(f"障碍记录字段不符合契约: {path.name}")
        self._validate_payload(payload, path.name)
        return payload

    def _validate_payload(self, payload, source_name):
        """Validate untrusted JSON values and cross-field business invariants."""

        self._validate_id(payload["id"])
        id_match = OBSTACLE_ID_RE.fullmatch(payload["id"])
        if not isinstance(payload["ride_id"], str) or not payload["ride_id"]:
            raise ObstacleStoreError(f"障碍行程 ID 不符合契约: {source_name}")
        try:
            created_at = datetime.fromisoformat(payload["created_at"])
        except (TypeError, ValueError) as exc:
            raise ObstacleStoreError(
                f"障碍记录时间不符合契约: {source_name}"
            ) from exc
        if created_at.tzinfo is None:
            raise ObstacleStoreError(f"障碍记录时间不符合契约: {source_name}")
        if (
            not isinstance(payload["from_point"], str)
            or not isinstance(payload["to_point"], str)
            or not POINT_RE.fullmatch(payload["from_point"])
            or not POINT_RE.fullmatch(payload["to_point"])
        ):
            raise ObstacleStoreError(f"障碍点位不符合契约: {source_name}")
        if (
            id_match.group("from_point") != payload["from_point"]
            or id_match.group("to_point") != payload["to_point"]
        ):
            raise ObstacleStoreError(
                f"障碍记录 ID 与点位不一致: {source_name}"
            )
        if not isinstance(payload["distance_cm"], (int, float)) or isinstance(
            payload["distance_cm"], bool
        ):
            raise ObstacleStoreError(f"障碍距离不符合契约: {source_name}")
        if float(payload["distance_cm"]) <= 0:
            raise ObstacleStoreError(f"障碍距离必须大于 0: {source_name}")

        obstacle_type = payload["obstacle_type"]
        detected_color = payload["detected_color"]
        classification_status = payload["classification_status"]
        station_id = payload["station_id"]
        recognition_error = payload["recognition_error"]
        if obstacle_type not in (OBSTACLE_TYPE_ORDINARY, OBSTACLE_TYPE_TOLL):
            raise ObstacleStoreError(f"障碍类型不符合契约: {source_name}")
        if detected_color not in ("red", "blue", None):
            raise ObstacleStoreError(f"障碍颜色不符合契约: {source_name}")
        if classification_status not in (CLASSIFICATION_SUCCESS, CLASSIFICATION_FAILED):
            raise ObstacleStoreError(f"障碍分类状态不符合契约: {source_name}")

        if classification_status == CLASSIFICATION_SUCCESS:
            if recognition_error is not None:
                raise ObstacleStoreError(f"成功分类不能包含识别错误: {source_name}")
            if obstacle_type == OBSTACLE_TYPE_ORDINARY:
                valid_classification = detected_color == "red" and station_id is None
            else:
                valid_classification = (
                    detected_color == "blue"
                    and isinstance(station_id, str)
                    and QR_IDENTIFIER_PATTERN.fullmatch(station_id) is not None
                )
            if not valid_classification:
                raise ObstacleStoreError(f"成功分类字段互相矛盾: {source_name}")
        else:
            if obstacle_type != OBSTACLE_TYPE_ORDINARY or station_id is not None:
                raise ObstacleStoreError(f"失败分类必须采用普通障碍策略: {source_name}")
            if recognition_error not in VALID_RECOGNITION_ERRORS:
                raise ObstacleStoreError(f"失败分类识别错误不符合契约: {source_name}")

        handling_result = payload["handling_result"]
        recovery_status = payload["recovery_status"]
        recovered_point = payload["recovered_point"]
        if handling_result not in VALID_HANDLING_RESULTS:
            raise ObstacleStoreError(f"障碍处理结果不符合契约: {source_name}")
        if recovery_status not in VALID_RECOVERY_STATUSES:
            raise ObstacleStoreError(f"障碍恢复状态不符合契约: {source_name}")
        if handling_result == HANDLING_CONTINUED_CURRENT_EDGE:
            valid_handling = (
                obstacle_type == OBSTACLE_TYPE_TOLL
                and recovery_status is None
                and recovered_point is None
            )
        elif handling_result in (
            HANDLING_BLOCKED_AND_REPLANNED,
            HANDLING_CANCELED_AFTER_RECOVERY,
        ):
            valid_handling = (
                recovery_status == RECOVERED
                and recovered_point == payload["from_point"]
            )
        else:
            valid_handling = recovery_status == RECOVERY_FAILED and recovered_point is None
        if not valid_handling:
            raise ObstacleStoreError(f"障碍处理与恢复字段互相矛盾: {source_name}")

        filename = payload["image_filename"]
        capture_error = payload["capture_error"]
        if filename is not None:
            if (
                filename != f"{payload['id']}.jpg"
                or capture_error is not None
            ):
                raise ObstacleStoreError(f"障碍照片字段不符合契约: {source_name}")
        elif not isinstance(capture_error, str) or not capture_error:
            raise ObstacleStoreError(f"缺失照片必须包含保存错误: {source_name}")

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
            obstacle_type=payload["obstacle_type"],
            detected_color=payload["detected_color"],
            classification_status=payload["classification_status"],
            station_id=payload["station_id"],
            recognition_error=payload["recognition_error"],
            handling_result=payload["handling_result"],
            recovery_status=payload["recovery_status"],
            recovered_point=payload["recovered_point"],
            image_url=image_url,
            capture_error=capture_error,
        )

    @staticmethod
    def _validate_id(record_id: str):
        if not isinstance(record_id, str) or not OBSTACLE_ID_RE.fullmatch(record_id):
            raise ObstacleStoreError("障碍记录 ID 不符合契约")


def _utc_now():
    return datetime.now(timezone.utc)
