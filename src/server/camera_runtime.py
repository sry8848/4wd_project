"""Own the backend camera while keeping capture handles task-scoped."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from src.hardware.camera import (
    CameraCaptureError,
    OpenCVCameraSession,
    write_diagnostic_frame,
)


LOGGER = logging.getLogger(__name__)


class BackendCamera:
    """后端进程内唯一的摄像头资源所有者。

    参数说明：
    device: OpenCV 摄像头编号或稳定的 V4L2 设备路径。
    session_factory: 创建 OpenCVCameraSession 的函数，测试时可注入假对象。
    """

    def __init__(
        self,
        device=0,
        width=640,
        height=480,
        session_factory: Callable[..., OpenCVCameraSession] = OpenCVCameraSession,
    ):
        self.device = device
        self.width = width
        self.height = height
        self._session_factory = session_factory
        self._session: Optional[OpenCVCameraSession] = None
        self._ready = False
        self.error: Optional[str] = None

    @property
    def ready(self) -> bool:
        """返回最近一次打开或读帧是否成功，不表示当前持有句柄。"""

        return self._ready

    def probe(self) -> bool:
        """启动时读取一帧确认设备状态，然后立即释放句柄。

        分步逻辑：
        1. 通过 read_frame() 按需打开并读取一帧。
        2. 已知摄像头错误只更新健康状态，不阻止后端启动。
        3. 无论成功失败都释放探测句柄，等待真实视觉任务重新打开。
        """

        try:
            self.read_frame()
        except CameraCaptureError as exc:
            LOGGER.warning("Backend camera probe failed: %s", exc)
            return False
        finally:
            self.close()
        return self.ready

    def capture(self, output_path) -> Path:
        """执行一次独立抓拍，并在结束后释放摄像头句柄。

        参数说明：
        output_path: ObstacleStore 为本条记录分配的唯一 JPEG 路径。

        分步逻辑：
        1. 按需打开会话，丢弃一个可能缓存的旧帧并写入 JPEG。
        2. 打开或抓拍失败时记录最近错误，但不永久禁用摄像头。
        3. 无论结果如何都释放本次抓拍句柄，后续调用可以重新尝试。
        """

        session = self._ensure_session()
        try:
            result = session.capture(output_path, warmup_frames=1)
        except CameraCaptureError as exc:
            self._ready = False
            self.error = str(exc)
            LOGGER.warning("Backend camera capture failed: %s", exc)
            raise
        else:
            self._ready = True
            self.error = None
            return result.path
        finally:
            self.close()

    def read_frame(self):
        """从当前任务会话读取一张独立 BGR 帧。

        分步逻辑：
        1. 没有活动会话时按需打开，已有会话时直接复用。
        2. 读取独立帧，避免调用方修改摄像头内部缓冲区。
        3. 打开或读帧失败时释放失效会话；下一次调用可以重新打开。
        """

        session = self._ensure_session()
        try:
            frame = session.read_frame(copy=True)
        except CameraCaptureError as exc:
            self.close()
            self._ready = False
            self.error = str(exc)
            LOGGER.warning("Backend camera frame read failed: %s", exc)
            raise
        self._ready = True
        self.error = None
        return frame

    def save_frame(self, output_path, frame) -> Path:
        """保存调用方选中的准确帧，不重新读取摄像头。

        参数说明：
        output_path: 目标 JPEG 路径。
        frame: 先前由 read_frame() 返回的 BGR 帧。

        写盘只使用内存帧，不要求摄像头仍处于打开状态，也不改变设备健康状态。
        """

        return write_diagnostic_frame(output_path, frame).path

    def close(self):
        """幂等释放当前任务持有的摄像头句柄。"""

        if self._session is not None:
            self._session.close()
            self._session = None

    def _ensure_session(self) -> OpenCVCameraSession:
        """复用当前会话，或为本次视觉任务打开一个新会话。"""

        if self._session is not None:
            return self._session

        session = self._session_factory(
            device_index=self.device,
            width=self.width,
            height=self.height,
        )
        try:
            session.open()
        except CameraCaptureError as exc:
            session.close()
            self._ready = False
            self.error = str(exc)
            LOGGER.warning("Backend camera open failed: %s", exc)
            raise
        self._session = session
        return session


def parse_camera_device(environ):
    """读取唯一 CAMERA_DEVICE 配置，数字转为编号，其余值保留为路径。"""

    value = environ.get("CAMERA_DEVICE", "0").strip()
    if not value:
        raise RuntimeError("CAMERA_DEVICE 不能为空")
    if value.isdecimal():
        return int(value)
    return value
