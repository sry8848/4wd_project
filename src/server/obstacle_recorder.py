"""Record one confirmed obstacle after edge recovery has finished."""

from __future__ import annotations

from src.hardware.camera import CameraCaptureError
from src.server.obstacle_store import RECOVERED, RECOVERY_FAILED, ObstacleStore
from src.tasks.edge_follow import EDGE_RECOVERED_TO_START_NODE


class ObstacleRecorder:
    """组合长期摄像头与磁盘记录，但不参与导航决策。

    参数说明：
    store: JPEG 与同名 JSON 的持久化存储。
    camera: 后端唯一的 BackendCamera 实例。
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
        recovery_status: str,
    ):
        """在恢复流程结束后保存一条完整障碍记录。

        分步逻辑：
        1. 预先分配记录 ID、时间和 JPEG 路径。
        2. 只有成功回到可信起点并完成居中后才调用摄像头。
        3. 无论是否拍到真实照片都保存 JSON，供重启后继续查看。
        """

        record_id, created_at, image_path = self.store.prepare_record(
            from_point,
            to_point,
        )
        recovered = recovery_status == EDGE_RECOVERED_TO_START_NODE
        image_filename = None
        capture_error = None

        if recovered:
            try:
                self.camera.capture(image_path)
                image_filename = image_path.name
            except CameraCaptureError as exc:
                capture_error = str(exc)
        else:
            capture_error = "小车未安全恢复到可信节点，未执行抓拍"

        return self.store.save_record(
            record_id=record_id,
            ride_id=ride_id,
            created_at=created_at,
            from_point=from_point,
            to_point=to_point,
            distance_cm=distance_cm,
            recovered_point=from_point if recovered else None,
            status=RECOVERED if recovered else RECOVERY_FAILED,
            image_filename=image_filename,
            capture_error=capture_error,
        )
