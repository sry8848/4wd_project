"""Persist one stopped obstacle's selected visual frame and final handling facts."""

from __future__ import annotations

from src.hardware.camera import CameraCaptureError
from src.server.obstacle_store import ObstacleStore


class ObstacleRecorder:
    """Combine the backend camera frame writer with strict obstacle storage.

    Parameters:
    store: ObstacleStore owning the JSON/JPEG directory contract.
    camera: BackendCamera owning the process's only camera session.
    """

    def __init__(self, store: ObstacleStore, camera):
        self.store = store
        self.camera = camera

    def record(
        self,
        *,
        ride_id: str,
        from_point: str,
        to_point: str,
        distance_cm: float,
        visual_result,
        handling_result: str,
        recovery_status,
        recovered_point,
    ):
        """Save the exact classification frame and one final strict JSON record.

        Steps:
        Allocate one record identity, save the in-memory frame without re-reading the
        camera, then persist JSON even when no frame exists or JPEG writing fails.
        Navigation decisions are already final and are never changed by save errors.
        """

        record_id, created_at, image_path = self.store.prepare_record(
            from_point,
            to_point,
        )
        image_filename = None
        capture_error = None
        if visual_result.record_frame is None:
            capture_error = "视觉识别没有可保存的原始帧"
        else:
            try:
                self.camera.save_frame(image_path, visual_result.record_frame)
                image_filename = image_path.name
            except CameraCaptureError as exc:
                capture_error = str(exc)

        return self.store.save_record(
            record_id=record_id,
            ride_id=ride_id,
            created_at=created_at,
            from_point=from_point,
            to_point=to_point,
            distance_cm=distance_cm,
            obstacle_type=visual_result.obstacle_type,
            detected_color=visual_result.detected_color,
            classification_status=visual_result.classification_status,
            station_id=visual_result.station_id,
            recognition_error=visual_result.recognition_error,
            handling_result=handling_result,
            recovery_status=recovery_status,
            recovered_point=recovered_point,
            image_filename=image_filename,
            capture_error=capture_error,
        )
