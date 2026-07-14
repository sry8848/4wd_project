"""Own the backend's single long-lived OpenCV camera session."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from src.hardware.camera import CameraCaptureError, OpenCVCameraSession


LOGGER = logging.getLogger(__name__)


class BackendCamera:
    """后端进程内唯一的长期摄像头资源所有者。

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
        self._started = False
        self.error: Optional[str] = None

    @property
    def available(self) -> bool:
        """返回当前进程是否仍持有可用于抓拍的摄像头。"""

        return self._session is not None

    def start(self) -> bool:
        """后端启动时只尝试一次打开摄像头。

        分步逻辑：
        1. 创建并打开唯一 OpenCV 会话。
        2. 已知摄像头错误只记录为不可用，不阻止后端启动。
        3. 同一实例禁止重复启动，避免产生第二个设备所有者。
        """

        if self._started:
            raise RuntimeError("后端摄像头只能启动一次")
        self._started = True
        session = self._session_factory(
            device_index=self.device,
            width=self.width,
            height=self.height,
        )
        try:
            session.open()
        except CameraCaptureError as exc:
            session.close()
            self.error = str(exc)
            LOGGER.error("Backend camera unavailable at startup: %s", exc)
            return False

        self._session = session
        self.error = None
        return True

    def capture(self, output_path) -> Path:
        """使用长期会话抓拍 JPEG；失败后本次进程不再重连。

        参数说明：
        output_path: ObstacleStore 为本条记录分配的唯一 JPEG 路径。

        分步逻辑：
        1. 丢弃一个可能缓存的旧帧，再写入真实 JPEG。
        2. 读取或写盘失败时立即释放会话并保存错误原因。
        3. 后续调用直接报告不可用，等待后端重启重新初始化。
        """

        if self._session is None:
            raise CameraCaptureError(self.error or "后端摄像头不可用")
        try:
            result = self._session.capture(output_path, warmup_frames=1)
        except CameraCaptureError as exc:
            self._session.close()
            self._session = None
            self.error = str(exc)
            LOGGER.error("Backend camera disabled after capture failure: %s", exc)
            raise
        return result.path

    def read_frame(self):
        """从唯一长期会话读取一张独立 BGR 帧。

        分步逻辑：
        1. 拒绝使用已经不可用的摄像头会话。
        2. 读取独立帧，避免调用方修改摄像头内部缓冲区。
        3. 读帧失败后关闭会话，本进程不自动重连。
        """

        if self._session is None:
            raise CameraCaptureError(self.error or "后端摄像头不可用")
        try:
            return self._session.read_frame(copy=True)
        except CameraCaptureError as exc:
            self._session.close()
            self._session = None
            self.error = str(exc)
            LOGGER.error("Backend camera disabled after frame read failure: %s", exc)
            raise

    def save_frame(self, output_path, frame) -> Path:
        """保存调用方选中的准确帧，不重新读取摄像头。

        参数说明：
        output_path: 目标 JPEG 路径。
        frame: 先前由 read_frame() 返回的 BGR 帧。

        写盘失败不关闭摄像头，因为设备仍可能继续正常读帧。
        """

        if self._session is None:
            raise CameraCaptureError(self.error or "后端摄像头不可用")
        return self._session.save_diagnostic_frame(output_path, frame).path

    def close(self):
        """后端关闭时释放自己持有的摄像头资源。"""

        if self._session is not None:
            self._session.close()
            self._session = None


def parse_camera_device(environ):
    """读取唯一 CAMERA_DEVICE 配置，数字转为编号，其余值保留为路径。"""

    value = environ.get("CAMERA_DEVICE", "0").strip()
    if not value:
        raise RuntimeError("CAMERA_DEVICE 不能为空")
    if value.isdecimal():
        return int(value)
    return value
