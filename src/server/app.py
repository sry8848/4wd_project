"""FastAPI entry point for real 4WD ride execution."""

from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    BackgroundTasks,
    Body,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src import config as project_config
from src.algorithms.astar import PASSABLE
from src.algorithms.color_detect import ColorDetectionError, ColorDetector
from src.algorithms.face_recognition import (
    FaceRecognitionError,
    HaarFaceDetector,
    LocalFaceRecognizer,
)
from src.algorithms.qr_detect import QRCodeRecognitionError, QRCodeRecognizer
from src.server.camera_runtime import BackendCamera, parse_camera_device
from src.server.face_verification_store import (
    FACE_RECORD_ID_RE,
    FaceVerificationRecorder,
    FaceVerificationStore,
    FaceVerificationStoreError,
)
from src.server.hardware_factory import create_grid_navigation_hardware
from src.server.obstacle_recorder import ObstacleRecorder
from src.server.obstacle_store import ObstacleStore, ObstacleStoreError
from src.server.point_codec import PointValidationError
from src.server.ride_service import RideService
from src.server.runtime_state import RuntimeState, RuntimeStateError
from src.server.schemas import (
    CarStatusResponse,
    ErrorDetail,
    ErrorResponse,
    GridResponse,
    ObstacleRecordResponse,
    RideCreateRequest,
    RideStatusResponse,
)
from src.tasks.face_verification import FaceVerificationTask
from src.tasks.obstacle_visual_classification import (
    ObstacleVisualClassificationTask,
)
from src.tasks.toll_clearance import TollClearanceTask


LOGGER = logging.getLogger(__name__)
NAVIGATION_MODE_HARDWARE = "hardware"
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
OBSTACLE_CAPTURE_DIR = (
    Path(__file__).resolve().parents[2] / "captures" / "obstacles"
)
FACE_DATASET_DIR = Path(__file__).resolve().parents[2] / "captures" / "faces"
FACE_VERIFICATION_DIR = (
    Path(__file__).resolve().parents[2] / "captures" / "face_verifications"
)
from src.services.mail_sender import (
    AsyncMailNotifier,
    load_mail_config_from_env,
    send_email,
)


def load_navigation_configuration(environ):
    """读取并严格校验实车启动时的可信姿态。

    参数说明：
    environ: 环境变量映射，只读取 CAR_INITIAL_POSITION 和
        CAR_INITIAL_HEADING。

    分步逻辑：
    1. 强制要求显式提供初始点位和朝向。
    2. 缺少任一配置时拒绝启动，避免用虚构姿态控制实车。
    """
    initial_position = environ.get("CAR_INITIAL_POSITION")
    initial_heading = environ.get("CAR_INITIAL_HEADING")
    if initial_position is None or initial_heading is None:
        raise RuntimeError(
            "实车后端必须设置 CAR_INITIAL_POSITION 和 CAR_INITIAL_HEADING"
        )
    return initial_position, initial_heading


def create_mail_notifier(environ):
    """从环境变量创建 QQ 邮件异步发送器；配置缺失不阻止后端启动。"""

    try:
        config = load_mail_config_from_env(environ)
    except ValueError as exc:
        return AsyncMailNotifier(unavailable_reason=str(exc))
    return AsyncMailNotifier(
        send_fn=lambda subject, body: send_email(subject, body, config)
    )


INITIAL_POSITION, INITIAL_HEADING = load_navigation_configuration(os.environ)
runtime_state = RuntimeState(
    initial_position=INITIAL_POSITION,
    initial_heading=INITIAL_HEADING,
)
mail_notifier = create_mail_notifier(os.environ)
ride_service = RideService(runtime_state, mail_notifier)
obstacle_store = ObstacleStore(OBSTACLE_CAPTURE_DIR)
face_verification_store = FaceVerificationStore(FACE_VERIFICATION_DIR)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """在 FastAPI 生命周期内创建并安全释放唯一一组真实硬件。

    参数说明：
    app_instance: 当前 FastAPI 应用，用 state 保存硬件资源所有者。

    分步逻辑：
    1. 启动前创建 5x5 网格导航硬件，失败则拒绝启动。
    2. 只创建一个长期摄像头所有者；打不开时保留后端其它能力。
    3. 关闭时强制终止活动行程，先停车，再释放摄像头。
    """
    grid_definition = GridResponse.default()
    grid = [
        [PASSABLE for _col in grid_definition.cols]
        for _row in grid_definition.rows
    ]
    hardware = create_grid_navigation_hardware(grid)
    camera = BackendCamera(device=parse_camera_device(os.environ))
    camera.start()
    obstacle_recorder = ObstacleRecorder(obstacle_store, camera)
    face_verifier = None
    face_recorder = None
    obstacle_visual_task = None
    toll_clearance_task = None
    passenger_ids = ()
    try:
        detector = HaarFaceDetector()
        recognizer = LocalFaceRecognizer(detector=detector, threshold=0.30)
        recognizer.load_dataset(FACE_DATASET_DIR)
        passenger_ids = recognizer.labels
        if camera.available:
            face_verifier = FaceVerificationTask(
                recognizer,
                camera,
                confirm_frames=3,
                timeout_seconds=20.0,
            )
            face_recorder = FaceVerificationRecorder(face_verification_store, camera)
    except FaceRecognitionError as exc:
        LOGGER.warning("Face recognition unavailable at startup: %s", exc)
    try:
        if camera.available:
            color_detector = ColorDetector(
                colors=("red", "blue"),
                min_area=project_config.OBSTACLE_COLOR_MIN_AREA,
            )
            qr_recognizer = QRCodeRecognizer()
            obstacle_visual_task = ObstacleVisualClassificationTask(
                color_detector,
                qr_recognizer,
                camera,
                color_confirm_frames=(
                    project_config.OBSTACLE_COLOR_CONFIRM_FRAMES
                ),
                color_timeout_seconds=(
                    project_config.OBSTACLE_COLOR_TIMEOUT_SECONDS
                ),
                qr_timeout_seconds=project_config.TOLL_QR_TIMEOUT_SECONDS,
            )
    except (ColorDetectionError, QRCodeRecognitionError) as exc:
        LOGGER.warning("Obstacle vision unavailable at startup: %s", exc)
    if hardware.ultrasonic is not None:
        toll_clearance_task = TollClearanceTask(
            hardware.ultrasonic,
            clear_threshold_cm=project_config.ULTRASONIC_THRESHOLD,
            confirm_samples=project_config.TOLL_CLEARANCE_CONFIRM_SAMPLES,
            timeout_seconds=project_config.TOLL_CLEARANCE_TIMEOUT_SECONDS,
        )
    app_instance.state.navigation_hardware = hardware
    app_instance.state.backend_camera = camera
    app_instance.state.obstacle_recorder = obstacle_recorder
    app_instance.state.face_verifier = face_verifier
    app_instance.state.face_recorder = face_recorder
    app_instance.state.obstacle_visual_task = obstacle_visual_task
    app_instance.state.toll_clearance_task = toll_clearance_task
    app_instance.state.passenger_ids = passenger_ids

    try:
        yield
    finally:
        if hardware is not None:
            try:
                active_ride = runtime_state.get_active_ride()
                if active_ride is not None:
                    ride_service.force_cancel_ride(active_ride.id, "server_shutdown")
            finally:
                try:
                    hardware.close()
                finally:
                    try:
                        camera.close()
                    finally:
                        mail_notifier.close()
                        app_instance.state.navigation_hardware = None
                        app_instance.state.backend_camera = None
                        app_instance.state.obstacle_recorder = None
                        app_instance.state.face_verifier = None
                        app_instance.state.face_recorder = None
                        app_instance.state.obstacle_visual_task = None
                        app_instance.state.toll_clearance_task = None
                        app_instance.state.passenger_ids = ()


app = FastAPI(title="4WD Car Backend", version="0.3.0", lifespan=lifespan)
app.state.navigation_hardware = None
app.state.backend_camera = None
app.state.obstacle_recorder = None
app.state.face_verifier = None
app.state.face_recorder = None
app.state.obstacle_visual_task = None
app.state.toll_clearance_task = None
app.state.passenger_ids = ()


@app.exception_handler(PointValidationError)
async def handle_point_validation_error(
    _request: Request,
    exc: PointValidationError,
):
    """把业务输入校验错误转换为统一的 400 响应。

    参数说明：
    _request: 触发错误的 HTTP 请求，当前无需读取。
    exc: 点位或请求字段校验错误。

    分步逻辑：
    1. 使用现有 ErrorResponse 生成统一错误结构。
    2. 返回 HTTP 400。
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse.from_validation_error(exc).to_dict(),
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    _request: Request,
    exc: RequestValidationError,
):
    """把 FastAPI 参数解析错误转换为统一的 400 响应。

    参数说明：
    _request: 触发错误的 HTTP 请求，当前无需读取。
    exc: FastAPI 解析请求体或查询参数时产生的错误。

    分步逻辑：
    1. 提取第一个错误字段，不返回请求体或内部堆栈。
    2. 返回 invalid_request 错误。
    """
    errors = exc.errors()
    location = errors[0].get("loc", ()) if errors else ()
    details = {"field": str(location[-1])} if location else {}
    error = ErrorResponse(
        error=ErrorDetail(
            code="invalid_request",
            message="请求参数格式不正确",
            details=details,
        )
    )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=error.to_dict(),
    )


@app.exception_handler(RuntimeStateError)
async def handle_runtime_state_error(
    _request: Request,
    exc: RuntimeStateError,
):
    """把已知运行状态冲突转换为对应 HTTP 状态。

    参数说明：
    _request: 触发错误的 HTTP 请求，当前无需读取。
    exc: RuntimeState 抛出的状态错误。

    分步逻辑：
    1. 将不存在映射为 404，将活动行程冲突映射为 409。
    2. 未知状态错误记录日志并返回不泄露内部信息的 500。
    """
    if exc.code == "ride_not_found":
        http_status = status.HTTP_404_NOT_FOUND
        code = exc.code
        message = exc.message
    elif exc.code in (
        "ride_already_running",
        "ride_not_active",
        "invalid_ride_operation",
        "ride_command_pending",
    ):
        http_status = status.HTTP_409_CONFLICT
        code = exc.code
        message = exc.message
    elif exc.code in (
        "hardware_not_ready",
        "camera_not_ready",
        "face_recognition_not_ready",
    ):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        code = exc.code
        message = exc.message
    else:
        LOGGER.error(
            "Unhandled RuntimeStateError code=%s message=%s",
            exc.code,
            exc.message,
        )
        http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
        code = "internal_error"
        message = "后端状态处理失败"

    details = {"field": exc.field} if exc.field is not None else {}
    error = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
        )
    )
    return JSONResponse(status_code=http_status, content=error.to_dict())


@app.get("/api/health")
def get_health():
    """返回后端进程健康状态。

    参数说明：
    无。

    分步逻辑：
    1. 生成带时区的当前 UTC 时间。
    2. 返回服务名称和在线标记。
    """
    return {
        "ok": True,
        "service": "4wd-backend",
        "navigation_mode": NAVIGATION_MODE_HARDWARE,
        "hardware_ready": app.state.navigation_hardware is not None,
        "camera_ready": (
            app.state.backend_camera is not None
            and app.state.backend_camera.available
        ),
        "camera_error": (
            app.state.backend_camera.error
            if app.state.backend_camera is not None
            else None
        ),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/grid", response_model=GridResponse)
def get_grid():
    """返回第一版 5x5 网格定义。

    参数说明：
    无。

    分步逻辑：
    1. 调用现有 schema 创建默认网格。
    2. 由 FastAPI 序列化 dataclass 响应。
    """
    return GridResponse.default()


@app.get("/api/car/status", response_model=CarStatusResponse)
def get_car_status():
    """返回当前可信小车状态。

    参数说明：
    无。

    分步逻辑：
    1. 从 RuntimeState 读取状态。
    2. 返回给前端轮询。
    """
    return runtime_state.get_car_status()


@app.get("/api/passengers", response_model=List[str])
def list_passengers():
    """返回后端启动时成功加载的固定人脸标签。"""

    return list(app.state.passenger_ids)


@app.post(
    "/api/rides",
    response_model=RideStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_ride(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """创建行程并注册真实硬件后台导航。

    参数说明：
    payload: 前端 JSON 请求体，只允许 passenger_id、start、waypoints、end。
    background_tasks: FastAPI 为本次请求提供的后台任务容器。

    分步逻辑：
    1. 使用 RideCreateRequest 校验外部输入。
    2. 创建行程并立即准备 202 响应。
    3. 注册真实 GridNavigator 执行行程。
    """
    request = RideCreateRequest.from_payload(payload)
    hardware = app.state.navigation_hardware
    obstacle_recorder = app.state.obstacle_recorder
    if hardware is None or obstacle_recorder is None:
        raise RuntimeStateError(
            "hardware_not_ready",
            "真实导航硬件尚未初始化",
        )

    camera = app.state.backend_camera
    if camera is None or not camera.available:
        raise RuntimeStateError(
            "camera_not_ready",
            "固定摄像头不可用，不能创建接客行程",
        )
    face_verifier = app.state.face_verifier
    face_recorder = app.state.face_recorder
    if face_verifier is None or face_recorder is None:
        raise RuntimeStateError(
            "face_recognition_not_ready",
            "人脸识别器没有可用登记样本，请先登记并重启后端",
        )
    if request.passenger_id not in app.state.passenger_ids:
        raise PointValidationError(
            "unknown_passenger",
            "所选乘客不在当前已加载的人脸列表中",
            "passenger_id",
        )
    obstacle_visual_task = app.state.obstacle_visual_task
    toll_clearance_task = app.state.toll_clearance_task
    if obstacle_visual_task is None or toll_clearance_task is None:
        raise RuntimeStateError(
            "obstacle_processing_not_ready",
            "障碍视觉识别或收费站超声波确认能力尚未就绪",
        )

    ride = ride_service.submit_ride(request)
    background_tasks.add_task(
        ride_service.run_hardware_ride,
        ride.id,
        hardware.navigator,
        obstacle_recorder,
        face_verifier,
        face_recorder,
        obstacle_visual_task,
        toll_clearance_task,
    )
    return ride


@app.get(
    "/api/rides/active",
    response_model=RideStatusResponse,
    responses={204: {"description": "当前没有活动行程"}},
)
def get_active_ride():
    """返回当前活动行程，没有时返回 204。

    参数说明：
    无。

    分步逻辑：
    1. 从 RuntimeState 查询活动行程。
    2. 无活动行程时返回空响应，否则返回行程状态。
    """
    ride = runtime_state.get_active_ride()
    if ride is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return ride


@app.post("/api/rides/{ride_id}/cancel")
def cancel_ride(
    ride_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    """取消当前活动行程。

    参数说明：
    ride_id: 要取消的活动行程 ID。
    payload: 可选 JSON 请求体；传入时只允许 reason 字段。

    分步逻辑：
    1. 校验可选取消原因，缺省使用 passenger_cancel。
    2. 请求 RideService 保持当前方向行驶到前方下一个节点。
    3. 返回 canceling 状态，前端继续轮询直至节点停车完成。
    """
    reason = "passenger_cancel"
    if payload is not None:
        if set(payload) != {"reason"}:
            raise PointValidationError(
                "invalid_request",
                "取消请求只允许 reason 字段",
                "reason",
            )
        if not isinstance(payload["reason"], str) or not payload["reason"].strip():
            raise PointValidationError(
                "invalid_request",
                "reason 必须是非空字符串",
                "reason",
            )
        reason = payload["reason"].strip()

    if app.state.navigation_hardware is None:
        raise RuntimeStateError(
            "hardware_not_ready",
            "真实导航硬件尚未初始化",
        )

    ride = ride_service.request_cancel_ride(ride_id, reason)
    return {
        "id": ride.id,
        "status": ride.status,
        "current_position": ride.current_position,
        "message": ride.eta_text,
    }


@app.post(
    "/api/rides/{ride_id}/face-verification/retry",
    response_model=RideStatusResponse,
)
def retry_face_verification(
    ride_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    """唤醒同一活动行程线程重新执行一次人脸核验。"""

    if payload is not None:
        raise PointValidationError(
            "invalid_request",
            "重新识别接口不接受请求体",
        )
    return ride_service.request_face_verification_retry(ride_id)


@app.post(
    "/api/rides/{ride_id}/confirm-boarding",
    response_model=RideStatusResponse,
)
def confirm_boarding(
    ride_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    """确认乘客上车并允许原行程线程继续导航。"""

    if payload is not None:
        raise PointValidationError(
            "invalid_request",
            "确认上车接口不接受请求体",
        )
    return ride_service.confirm_boarding(ride_id)


@app.get("/api/rides/{ride_id}/events")
def list_ride_events(
    ride_id: str,
    after: int = Query(default=0, ge=0),
):
    """返回指定序号之后的行程消息。

    参数说明：
    ride_id: 要查询的行程 ID。
    after: 已读取的最后消息序号，必须大于等于 0。

    分步逻辑：
    1. 查询 after 之后的事件。
    2. 返回事件列表和下一次轮询游标。
    """
    events, next_after = runtime_state.list_ride_events(ride_id, after)
    return {
        "events": [event.to_dict() for event in events],
        "next_after": next_after,
    }


@app.get("/api/rides/{ride_id}", response_model=RideStatusResponse)
def get_ride(ride_id: str):
    """按 ID 返回指定行程。

    参数说明：
    ride_id: submit_ride() 返回的行程 ID。

    分步逻辑：
    1. 从 RuntimeState 按 ID 查询。
    2. 不存在时由统一错误处理器返回 404。
    """
    return runtime_state.get_ride(ride_id)


@app.get("/api/obstacles", response_model=List[ObstacleRecordResponse])
def list_obstacles():
    """返回磁盘中全部障碍记录，后端重启后仍可读取。"""

    return obstacle_store.list_records()


@app.get("/api/obstacles/{record_id}/image")
def get_obstacle_image(record_id: str):
    """只返回已登记且真实存在的障碍 JPEG。"""

    try:
        image_path = obstacle_store.get_image_path(record_id)
    except (FileNotFoundError, ObstacleStoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="障碍照片不存在",
        ) from exc
    return FileResponse(image_path, media_type="image/jpeg")


@app.get("/api/face-verifications/{record_id}/image")
def get_face_verification_image(record_id: str):
    """只返回合法人脸核验 JSON 已登记且真实存在的 JPEG。"""

    if not FACE_RECORD_ID_RE.fullmatch(record_id):
        raise PointValidationError(
            "invalid_face_record_id",
            "人脸核验记录 ID 不符合契约",
            "record_id",
        )
    try:
        image_path = face_verification_store.get_image_path(record_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="人脸核验照片不存在",
        ) from exc
    except FaceVerificationStoreError as exc:
        LOGGER.exception("Invalid face verification record: %s", record_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="人脸核验记录损坏",
        ) from exc
    return FileResponse(image_path, media_type="image/jpeg")


app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)
