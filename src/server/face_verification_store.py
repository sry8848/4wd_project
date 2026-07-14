"""Persist fixed-camera passenger verification records and selected frames."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Callable, Optional, Tuple

from src.tasks.face_verification import FACE_MATCHED, FACE_TIMEOUT


FACE_RECORD_ID_RE = re.compile(r"^face_[0-9]{8}_[0-9]{6}_[0-9]{6}$")
VALID_RESULTS = (FACE_MATCHED, FACE_TIMEOUT)


class FaceVerificationStoreError(RuntimeError):
    """表示人脸核验记录不符合固定磁盘契约。"""


@dataclass(frozen=True)
class FaceVerificationRecord:
    """一次已持久化的人脸核验记录。"""

    id: str
    ride_id: str
    passenger_id: str
    detected_passenger_id: Optional[str]
    result: str
    distance: Optional[float]
    created_at: str
    image_url: Optional[str]
    image_error: Optional[str]


class FaceVerificationStore:
    """严格保存并读取同名 JPEG/JSON 人脸核验记录。"""

    def __init__(
        self,
        root_dir,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.root_dir = Path(root_dir)
        self._now = now_fn if now_fn is not None else _utc_now

    def prepare_record(self) -> Tuple[str, str, Path]:
        """生成记录 ID、带时区创建时间和目标 JPEG 路径。"""

        now = self._now()
        if now.tzinfo is None:
            raise FaceVerificationStoreError("人脸核验记录时间必须包含时区")
        record_id = f"face_{now.strftime('%Y%m%d_%H%M%S_%f')}"
        return record_id, now.isoformat(), self.root_dir / f"{record_id}.jpg"

    def save_record(
        self,
        *,
        record_id: str,
        ride_id: str,
        passenger_id: str,
        detected_passenger_id: Optional[str],
        result: str,
        distance: Optional[float],
        created_at: str,
        image_filename: Optional[str],
        image_error: Optional[str],
    ) -> FaceVerificationRecord:
        """按固定字段原子写入 JSON，并返回可公开记录。"""

        self._validate_id(record_id)
        if result not in VALID_RESULTS:
            raise FaceVerificationStoreError(f"不支持的人脸核验结果: {result}")
        if image_filename is not None and Path(image_filename).name != image_filename:
            raise FaceVerificationStoreError("image_filename 只能是记录目录内的文件名")

        payload = {
            "id": record_id,
            "ride_id": ride_id,
            "passenger_id": passenger_id,
            "detected_passenger_id": detected_passenger_id,
            "result": result,
            "distance": float(distance) if distance is not None else None,
            "created_at": created_at,
            "image_filename": image_filename,
            "image_error": image_error,
        }
        target = self.root_dir / f"{record_id}.json"
        temporary = self.root_dir / f"{record_id}.json.tmp"
        try:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(target)
        except OSError as exc:
            raise FaceVerificationStoreError(
                f"无法保存人脸核验记录: {record_id}"
            ) from exc
        return self._to_record(payload)

    def get_image_path(self, record_id: str) -> Path:
        """只返回合法 JSON 已登记且真实存在的 JPEG。"""

        self._validate_id(record_id)
        json_path = self.root_dir / f"{record_id}.json"
        if not json_path.is_file():
            raise FileNotFoundError(f"人脸核验记录不存在: {record_id}")
        payload = self._read_payload(json_path)
        filename = payload["image_filename"]
        if filename is None:
            raise FileNotFoundError(f"人脸核验记录没有真实照片: {record_id}")
        image_path = self.root_dir / filename
        if not image_path.is_file():
            raise FileNotFoundError(f"人脸核验照片不存在: {record_id}")
        return image_path

    def _read_payload(self, path: Path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FaceVerificationStoreError(
                f"无法读取人脸核验记录: {path.name}"
            ) from exc
        required_fields = {
            "id",
            "ride_id",
            "passenger_id",
            "detected_passenger_id",
            "result",
            "distance",
            "created_at",
            "image_filename",
            "image_error",
        }
        if not isinstance(payload, dict) or set(payload) != required_fields:
            raise FaceVerificationStoreError(
                f"人脸核验记录字段不符合契约: {path.name}"
            )
        self._validate_id(payload["id"])
        if path.name != f"{payload['id']}.json":
            raise FaceVerificationStoreError("人脸核验记录文件名与 id 不一致")
        if payload["result"] not in VALID_RESULTS:
            raise FaceVerificationStoreError("人脸核验结果不符合契约")
        filename = payload["image_filename"]
        if filename is not None and Path(filename).name != filename:
            raise FaceVerificationStoreError("人脸核验图片文件名不安全")
        return payload

    def _to_record(self, payload) -> FaceVerificationRecord:
        filename = payload["image_filename"]
        image_path = self.root_dir / filename if filename is not None else None
        image_url = (
            f"/api/face-verifications/{payload['id']}/image"
            if image_path is not None and image_path.is_file()
            else None
        )
        return FaceVerificationRecord(
            id=payload["id"],
            ride_id=payload["ride_id"],
            passenger_id=payload["passenger_id"],
            detected_passenger_id=payload["detected_passenger_id"],
            result=payload["result"],
            distance=(
                float(payload["distance"])
                if payload["distance"] is not None
                else None
            ),
            created_at=payload["created_at"],
            image_url=image_url,
            image_error=payload["image_error"],
        )

    @staticmethod
    def _validate_id(record_id: str):
        if not isinstance(record_id, str) or not FACE_RECORD_ID_RE.fullmatch(record_id):
            raise FaceVerificationStoreError("人脸核验记录 ID 不符合契约")


class FaceVerificationRecorder:
    """组合唯一摄像头写帧与严格人脸记录存储。"""

    def __init__(self, store: FaceVerificationStore, camera):
        self.store = store
        self.camera = camera

    def record(self, *, ride_id: str, passenger_id: str, verification_result):
        """保存一次成功或超时结果，图片失败时仍保存 JSON。"""

        record_id, created_at, image_path = self.store.prepare_record()
        image_filename = None
        image_error = None
        if verification_result.frame is None:
            image_error = "本次核验没有可保存的摄像头帧"
        else:
            try:
                self.camera.save_frame(image_path, verification_result.frame)
                image_filename = image_path.name
            # 图片编码器和文件系统可能抛出不同异常；这里是统一的持久化边界，
            # 必须把错误写入 JSON，不能把已经确认的人脸结果改判为失败。
            except Exception as exc:
                image_error = str(exc)
        return self.store.save_record(
            record_id=record_id,
            ride_id=ride_id,
            passenger_id=passenger_id,
            detected_passenger_id=verification_result.detected_passenger_id,
            result=verification_result.outcome,
            distance=verification_result.distance,
            created_at=created_at,
            image_filename=image_filename,
            image_error=image_error,
        )


def _utc_now():
    return datetime.now(timezone.utc)
