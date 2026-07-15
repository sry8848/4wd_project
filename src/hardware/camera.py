"""Camera capture helpers for Raspberry Pi car experiments.

The preferred backend is OpenCV because it works well with USB cameras. CSI
cameras on Raspberry Pi OS may use either ``libcamera-still`` on newer images
or ``raspistill`` on older Yahboom/Raspberry Pi images.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import time
from typing import Optional, Union


DEFAULT_CAPTURE_DIR = Path("captures")
DEFAULT_PHOTO_PREFIX = "photo"
DEFAULT_PHOTO_EXTENSION = ".jpg"
CameraBackend = str
CameraDevice = Union[int, str]
DEFAULT_BACKEND: CameraBackend = "auto"


class CameraCaptureError(RuntimeError):
    """Raised when the camera cannot capture or save a frame."""


@dataclass(frozen=True)
class CaptureResult:
    """Metadata for one saved camera frame."""

    path: Path
    width: int
    height: int
    device_index: Optional[CameraDevice]
    backend: str
    sharpness: Optional[float] = None


@dataclass(frozen=True)
class SavedFrameDiagnostics:
    """Metadata for one diagnostic frame written from an in-memory image.

    Args:
        path: Exact JPEG path written to disk.
        width: Actual frame width in pixels.
        height: Actual frame height in pixels.
        mean_brightness: Mean grayscale brightness from 0 to 255.
        sharpness: Laplacian-variance sharpness score; larger is usually clearer.
    """

    path: Path
    width: int
    height: int
    mean_brightness: float
    sharpness: float


@dataclass(frozen=True)
class OpenCVCameraSettings:
    """Optional OpenCV camera controls.

    Args:
        fps: Requested camera frame rate.
        fourcc: Requested pixel format, for example ``MJPG``.
        brightness: Camera brightness value if supported by the driver.
        contrast: Camera contrast value if supported by the driver.
        saturation: Camera saturation value if supported by the driver.
        gain: Camera gain value if supported by the driver.
        exposure: Camera exposure value if supported by the driver.
        focus: Camera focus value if supported by the driver.
        sharpness: Camera-side sharpening value if supported by the driver.
        autofocus: Enable or disable autofocus if supported by the driver.
        auto_exposure: Raw OpenCV auto-exposure value. On many V4L2 cameras,
            ``1`` means manual and ``3`` means auto.
        buffer_size: Requested capture buffer size.
    """

    fps: Optional[float] = None
    fourcc: Optional[str] = "MJPG"
    brightness: Optional[float] = None
    contrast: Optional[float] = None
    saturation: Optional[float] = None
    gain: Optional[float] = None
    exposure: Optional[float] = None
    focus: Optional[float] = None
    sharpness: Optional[float] = None
    autofocus: Optional[bool] = None
    auto_exposure: Optional[float] = None
    buffer_size: Optional[float] = 1


PathLike = Union[str, Path]


class OpenCVCameraSession:
    """Keep one OpenCV camera open while capturing several photos.

    Args:
        device_index: OpenCV camera index or stable V4L2 device path.
        width: Optional requested frame width.
        height: Optional requested frame height.
        warmup_frames: Frames discarded once after opening the camera.
        warmup_seconds: Delay after opening the camera, allowing exposure to
            stabilize.
    """

    def __init__(
        self,
        *,
        device_index: CameraDevice = 0,
        width: Optional[int] = None,
        height: Optional[int] = None,
        warmup_frames: int = 5,
        warmup_seconds: float = 0.5,
        settings: Optional[OpenCVCameraSettings] = None,
    ):
        if warmup_frames < 0:
            raise ValueError("warmup_frames must be greater than or equal to 0")
        if warmup_seconds < 0:
            raise ValueError("warmup_seconds must be greater than or equal to 0")

        self.device_index = device_index
        self.width = width
        self.height = height
        self.warmup_frames = warmup_frames
        self.warmup_seconds = warmup_seconds
        self.settings = settings or OpenCVCameraSettings()
        self._cv2 = None
        self._camera = None

    def open(self) -> "OpenCVCameraSession":
        """Open the OpenCV camera and discard initial warmup frames."""

        try:
            import cv2
        except ImportError as exc:
            raise CameraCaptureError(
                "OpenCV is not installed. Install python3-opencv, or use "
                "--backend libcamera if this is a CSI camera."
            ) from exc

        camera = cv2.VideoCapture(self.device_index)
        if not camera.isOpened():
            camera.release()
            raise CameraCaptureError(
                f"Cannot open camera device {self.device_index}. Check the "
                "camera index, connection, and whether a video service is "
                "using it."
            )

        if self.width is not None:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height is not None:
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        apply_opencv_camera_settings(cv2, camera, self.settings)

        if self.warmup_seconds > 0:
            time.sleep(self.warmup_seconds)

        self._cv2 = cv2
        self._camera = camera
        if self.warmup_frames:
            self._read_frame(self.warmup_frames)
        return self

    def capture(
        self,
        output_path: PathLike,
        *,
        warmup_frames: int = 0,
        delay_seconds: float = 0.0,
        burst_count: int = 1,
    ) -> CaptureResult:
        """Capture one frame from the open camera and save it.

        Args:
            output_path: Exact file path to save.
            warmup_frames: Extra frames to discard immediately before saving.
            delay_seconds: Optional delay after servo movement and before read.
            burst_count: Number of candidate frames to score and choose from.

        Returns:
            CaptureResult containing the saved path and frame dimensions.
        """

        if warmup_frames < 0:
            raise ValueError("warmup_frames must be greater than or equal to 0")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be greater than or equal to 0")
        if burst_count < 1:
            raise ValueError("burst_count must be greater than or equal to 1")
        if self._camera is None or self._cv2 is None:
            raise CameraCaptureError("OpenCV camera session is not open")

        if delay_seconds > 0:
            time.sleep(delay_seconds)

        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        frame, sharpness = self._read_best_frame(warmup_frames, burst_count)

        saved = self._cv2.imwrite(str(target_path), frame)
        if not saved:
            raise CameraCaptureError(f"Failed to write photo to {target_path}")

        frame_height, frame_width = frame.shape[:2]
        return CaptureResult(
            path=target_path,
            width=int(frame_width),
            height=int(frame_height),
            device_index=self.device_index,
            backend="opencv",
            sharpness=sharpness,
        )

    def read_frame(self, *, warmup_frames: int = 0, copy: bool = True):
        """Read one frame without saving it to disk.

        Args:
            warmup_frames: Buffered frames to discard before returning a frame.
            copy: Return an independent frame copy when true.

        Returns:
            The latest OpenCV BGR image frame.

        This method supports continuous image-processing tasks such as QR-code
        recognition while keeping camera ownership inside the hardware layer.
        """

        if warmup_frames < 0:
            raise ValueError("warmup_frames must be greater than or equal to 0")
        if self._camera is None or self._cv2 is None:
            raise CameraCaptureError("OpenCV camera session is not open")

        # 1. Discard any requested buffered frames and obtain the newest frame.
        frame = self._read_frame(warmup_frames)
        # 2. Isolate the returned image from the capture buffer when requested.
        return frame.copy() if copy else frame

    def save_diagnostic_frame(
        self,
        output_path: PathLike,
        frame,
    ) -> SavedFrameDiagnostics:
        """Save an already-read frame and report image-quality diagnostics.

        Args:
            output_path: Exact JPEG path used for the diagnostic snapshot.
            frame: OpenCV BGR image previously returned by read_frame().

        The supplied frame can still be saved after the capture handle is released.
        An open session reuses its imported OpenCV module; a closed session imports
        OpenCV only for image encoding.
        """

        return write_diagnostic_frame(
            output_path,
            frame,
            cv2_module=self._cv2,
        )

    def close(self) -> None:
        """Release the OpenCV camera resource."""

        if self._camera is not None:
            self._camera.release()
            self._camera = None
        self._cv2 = None

    def _read_frame(self, warmup_frames: int):
        """Read from OpenCV, discarding requested buffered frames first."""

        if self._camera is None:
            raise CameraCaptureError("OpenCV camera session is not open")

        frame = None
        reads = max(1, warmup_frames + 1)
        for _ in range(reads):
            ok, current_frame = self._camera.read()
            if ok and current_frame is not None:
                frame = current_frame
            else:
                time.sleep(0.05)

        if frame is None:
            raise CameraCaptureError(
                f"Camera device {self.device_index} opened, but no frame was read."
            )
        return frame

    def _read_best_frame(self, warmup_frames: int, burst_count: int):
        """Read several frames and return the sharpest one.

        Args:
            warmup_frames: Buffered frames to discard before scoring.
            burst_count: Number of frames scored by Laplacian variance.

        Returns:
            Tuple of ``(frame, sharpness_score)``.
        """

        if self._camera is None or self._cv2 is None:
            raise CameraCaptureError("OpenCV camera session is not open")

        best_frame = None
        best_score = -1.0
        total_reads = max(0, warmup_frames) + max(1, burst_count)
        for read_index in range(total_reads):
            ok, frame = self._camera.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            if read_index < warmup_frames:
                continue
            score = sharpness_score(self._cv2, frame)
            if score > best_score:
                best_score = score
                best_frame = frame

        if best_frame is None:
            raise CameraCaptureError(
                f"Camera device {self.device_index} opened, but no frame was read."
            )
        return best_frame, best_score

    def __enter__(self) -> "OpenCVCameraSession":
        return self.open()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def write_diagnostic_frame(
    output_path: PathLike,
    frame,
    *,
    cv2_module=None,
) -> SavedFrameDiagnostics:
    """Save one existing BGR frame without requiring an open camera handle.

    Args:
        output_path: Exact JPEG path used for the diagnostic snapshot.
        frame: OpenCV BGR image previously returned by a camera read.
        cv2_module: Existing OpenCV module when the caller already imported it.

    Steps:
        1. Load only the OpenCV image encoder when the caller did not provide it.
        2. Write the exact supplied frame without opening or reading a camera.
        3. Return resolution and image-quality diagnostics.
    """

    if frame is None:
        raise CameraCaptureError("Diagnostic frame is empty")
    if cv2_module is None:
        try:
            import cv2 as cv2_module
        except ImportError as exc:
            raise CameraCaptureError(
                "OpenCV is not installed; the diagnostic frame cannot be saved."
            ) from exc

    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2_module.imwrite(str(target_path), frame):
        raise CameraCaptureError(
            f"Failed to write diagnostic frame to {target_path}"
        )

    frame_height, frame_width = frame.shape[:2]
    gray = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY)
    return SavedFrameDiagnostics(
        path=target_path,
        width=int(frame_width),
        height=int(frame_height),
        mean_brightness=float(gray.mean()),
        sharpness=sharpness_score(cv2_module, frame),
    )


def build_photo_path(
    output_dir: PathLike = DEFAULT_CAPTURE_DIR,
    prefix: str = DEFAULT_PHOTO_PREFIX,
    extension: str = DEFAULT_PHOTO_EXTENSION,
) -> Path:
    """Build a timestamped output path for one captured photo."""

    clean_extension = extension if extension.startswith(".") else "." + extension
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"{prefix}_{timestamp}{clean_extension}"


def capture_photo(
    output_path: Optional[PathLike] = None,
    *,
    output_dir: PathLike = DEFAULT_CAPTURE_DIR,
    prefix: str = DEFAULT_PHOTO_PREFIX,
    extension: str = DEFAULT_PHOTO_EXTENSION,
    backend: CameraBackend = DEFAULT_BACKEND,
    device_index: CameraDevice = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    warmup_frames: int = 5,
    warmup_seconds: float = 0.5,
    settings: Optional[OpenCVCameraSettings] = None,
    burst_count: int = 1,
) -> CaptureResult:
    """Capture one photo from an OpenCV camera and save it to disk.

    Args:
        output_path: Exact file path to save. If omitted, a timestamped path is
            created under ``output_dir``.
        output_dir: Directory used when ``output_path`` is omitted.
        prefix: Filename prefix used when ``output_path`` is omitted.
        extension: File extension used when ``output_path`` is omitted.
        backend: ``opencv`` for USB cameras, ``libcamera`` or ``raspistill``
            for CSI cameras, or ``auto`` to try known backends in order.
        device_index: OpenCV camera index or stable V4L2 device path.
        width: Optional requested frame width.
        height: Optional requested frame height.
        warmup_frames: Number of frames to discard before saving the final one.
        warmup_seconds: Delay after opening the camera, allowing exposure to
            stabilize.
        settings: Optional OpenCV camera controls.
        burst_count: Number of candidate frames to score and choose from.

    Returns:
        CaptureResult containing the saved path and frame dimensions.
    """

    if warmup_frames < 0:
        raise ValueError("warmup_frames must be greater than or equal to 0")
    if warmup_seconds < 0:
        raise ValueError("warmup_seconds must be greater than or equal to 0")
    if burst_count < 1:
        raise ValueError("burst_count must be greater than or equal to 1")

    target_path = (
        Path(output_path)
        if output_path is not None
        else build_photo_path(output_dir, prefix, extension)
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    errors = []

    if backend in ("auto", "opencv"):
        try:
            return _capture_with_opencv(
                target_path=target_path,
                device_index=device_index,
                width=width,
                height=height,
                warmup_frames=warmup_frames,
                warmup_seconds=warmup_seconds,
                settings=settings,
                burst_count=burst_count,
            )
        except CameraCaptureError as exc:
            if backend == "opencv":
                raise
            errors.append(f"opencv: {exc}")

    if backend in ("auto", "libcamera"):
        try:
            return _capture_with_libcamera(
                target_path=target_path,
                width=width,
                height=height,
                warmup_seconds=warmup_seconds,
            )
        except CameraCaptureError as exc:
            if backend == "libcamera":
                raise
            errors.append(f"libcamera: {exc}")

    if backend in ("auto", "raspistill"):
        try:
            return _capture_with_raspistill(
                target_path=target_path,
                width=width,
                height=height,
                warmup_seconds=warmup_seconds,
            )
        except CameraCaptureError as exc:
            if backend == "raspistill":
                raise
            errors.append(f"raspistill: {exc}")

    detail = "; ".join(errors) if errors else f"unsupported backend: {backend}"
    raise CameraCaptureError(
        f"Camera capture failed ({detail}). Try --device 1, --backend "
        "raspistill, --backend libcamera, or stop services such as "
        "mjpg-streamer that may own the camera."
    )


def _capture_with_opencv(
    *,
    target_path: Path,
    device_index: CameraDevice,
    width: Optional[int],
    height: Optional[int],
    warmup_frames: int,
    warmup_seconds: float,
    settings: Optional[OpenCVCameraSettings],
    burst_count: int,
) -> CaptureResult:
    with OpenCVCameraSession(
        device_index=device_index,
        width=width,
        height=height,
        warmup_frames=warmup_frames,
        warmup_seconds=warmup_seconds,
        settings=settings,
    ) as camera:
        return camera.capture(target_path, burst_count=burst_count)


def apply_opencv_camera_settings(cv2, camera, settings: OpenCVCameraSettings) -> None:
    """Apply supported OpenCV camera properties.

    Args:
        cv2: Imported OpenCV module.
        camera: OpenCV ``VideoCapture`` object.
        settings: Camera controls requested by the caller.

    Simple steps:
        1. Apply format and buffer controls first.
        2. Disable auto controls before manual focus/exposure values.
        3. Apply image quality controls when the driver exposes them.
    """

    if settings.fourcc:
        fourcc = settings.fourcc.strip()
        if len(fourcc) == 4:
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    _set_if_present(cv2, camera, "CAP_PROP_FPS", settings.fps)
    _set_if_present(cv2, camera, "CAP_PROP_BUFFERSIZE", settings.buffer_size)
    _set_if_present(cv2, camera, "CAP_PROP_AUTOFOCUS", _bool_to_number(settings.autofocus))
    _set_if_present(cv2, camera, "CAP_PROP_AUTO_EXPOSURE", settings.auto_exposure)
    _set_if_present(cv2, camera, "CAP_PROP_BRIGHTNESS", settings.brightness)
    _set_if_present(cv2, camera, "CAP_PROP_CONTRAST", settings.contrast)
    _set_if_present(cv2, camera, "CAP_PROP_SATURATION", settings.saturation)
    _set_if_present(cv2, camera, "CAP_PROP_GAIN", settings.gain)
    _set_if_present(cv2, camera, "CAP_PROP_EXPOSURE", settings.exposure)
    _set_if_present(cv2, camera, "CAP_PROP_FOCUS", settings.focus)
    _set_if_present(cv2, camera, "CAP_PROP_SHARPNESS", settings.sharpness)


def sharpness_score(cv2, frame) -> float:
    """Estimate image sharpness with Laplacian variance."""

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _set_if_present(cv2, camera, property_name: str, value: Optional[float]) -> None:
    """Set an OpenCV property only when both property and value exist."""

    if value is None or not hasattr(cv2, property_name):
        return
    camera.set(getattr(cv2, property_name), float(value))


def _bool_to_number(value: Optional[bool]) -> Optional[float]:
    """Convert optional booleans to OpenCV numeric property values."""

    if value is None:
        return None
    return 1.0 if value else 0.0


def _capture_with_libcamera(
    *,
    target_path: Path,
    width: Optional[int],
    height: Optional[int],
    warmup_seconds: float,
) -> CaptureResult:
    executable = shutil.which("libcamera-still")
    if executable is None:
        raise CameraCaptureError("libcamera-still command was not found")

    timeout_ms = max(1, int(warmup_seconds * 1000))
    command = [
        executable,
        "--nopreview",
        "--timeout",
        str(timeout_ms),
        "-o",
        str(target_path),
    ]
    if width is not None:
        command.extend(["--width", str(width)])
    if height is not None:
        command.extend(["--height", str(height)])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise CameraCaptureError(
            message or f"libcamera-still exited with {completed.returncode}"
        )
    if not target_path.exists() or target_path.stat().st_size == 0:
        raise CameraCaptureError(f"libcamera did not create {target_path}")

    return CaptureResult(
        path=target_path,
        width=width or 0,
        height=height or 0,
        device_index=None,
        backend="libcamera",
    )


def _capture_with_raspistill(
    *,
    target_path: Path,
    width: Optional[int],
    height: Optional[int],
    warmup_seconds: float,
) -> CaptureResult:
    executable = shutil.which("raspistill")
    if executable is None:
        raise CameraCaptureError("raspistill command was not found")

    timeout_ms = max(1, int(warmup_seconds * 1000))
    command = [
        executable,
        "-n",
        "-t",
        str(timeout_ms),
        "-o",
        str(target_path),
    ]
    if width is not None:
        command.extend(["-w", str(width)])
    if height is not None:
        command.extend(["-h", str(height)])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise CameraCaptureError(
            message or f"raspistill exited with {completed.returncode}"
        )
    if not target_path.exists() or target_path.stat().st_size == 0:
        raise CameraCaptureError(f"raspistill did not create {target_path}")

    return CaptureResult(
        path=target_path,
        width=width or 0,
        height=height or 0,
        device_index=None,
        backend="raspistill",
    )
