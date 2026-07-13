"""FastAPI entry point for simulated or real 4WD ride execution."""

from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, Body, FastAPI, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.algorithms.astar import PASSABLE
from src.server.hardware_factory import create_grid_navigation_hardware
from src.server.point_codec import PointValidationError
from src.server.ride_service import RideService
from src.server.runtime_state import RuntimeState, RuntimeStateError
from src.server.schemas import (
    CarStatusResponse,
    ErrorDetail,
    ErrorResponse,
    GridResponse,
    LatestMailResponse,
    RideCreateRequest,
    RideStatusResponse,
)


LOGGER = logging.getLogger(__name__)
NAVIGATION_MODE_FAKE = "fake"
NAVIGATION_MODE_HARDWARE = "hardware"
VALID_NAVIGATION_MODES = (NAVIGATION_MODE_FAKE, NAVIGATION_MODE_HARDWARE)
FAKE_RIDE_STEP_DELAY_SECONDS = 0.5
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def load_navigation_configuration(environ):
    """读取并严格校验导航模式和启动时可信姿态。

    参数说明：
    environ: 环境变量映射，只读取 CAR_NAVIGATION_MODE、
        CAR_INITIAL_POSITION 和 CAR_INITIAL_HEADING。

    分步逻辑：
    1. 模式缺省为 fake；未知值立即报错，不静默回退。
    2. hardware 模式强制要求显式提供初始点位和朝向。
    3. fake 模式继续使用 C3/north 作为本地演示初始值。
    """
    mode = environ.get("CAR_NAVIGATION_MODE", NAVIGATION_MODE_FAKE)
    if mode not in VALID_NAVIGATION_MODES:
        raise RuntimeError("CAR_NAVIGATION_MODE 必须是 fake 或 hardware")

    initial_position = environ.get("CAR_INITIAL_POSITION")
    initial_heading = environ.get("CAR_INITIAL_HEADING")
    if mode == NAVIGATION_MODE_HARDWARE and (
        initial_position is None or initial_heading is None
    ):
        raise RuntimeError(
            "hardware 模式必须设置 CAR_INITIAL_POSITION 和 CAR_INITIAL_HEADING"
        )
    return (
        mode,
        initial_position if initial_position is not None else "C3",
        initial_heading if initial_heading is not None else "north",
    )


NAVIGATION_MODE, INITIAL_POSITION, INITIAL_HEADING = load_navigation_configuration(
    os.environ
)
runtime_state = RuntimeState(
    initial_position=INITIAL_POSITION,
    initial_heading=INITIAL_HEADING,
)
ride_service = RideService(runtime_state)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """在 FastAPI 生命周期内创建并安全释放唯一一组真实硬件。

    参数说明：
    app_instance: 当前 FastAPI 应用，用 state 保存硬件资源所有者。

    分步逻辑：
    1. fake 模式不创建任何 GPIO 对象。
    2. hardware 模式启动前创建 5x5 网格导航硬件，失败则拒绝启动。
    3. 关闭时先取消活动行程，再停车并释放全部硬件资源。
    """
    hardware = None
    if NAVIGATION_MODE == NAVIGATION_MODE_HARDWARE:
        grid_definition = GridResponse.default()
        grid = [
            [PASSABLE for _col in grid_definition.cols]
            for _row in grid_definition.rows
        ]
        hardware = create_grid_navigation_hardware(grid)
    app_instance.state.navigation_hardware = hardware

    try:
        yield
    finally:
        if hardware is not None:
            try:
                active_ride = runtime_state.get_active_ride()
                if active_ride is not None:
                    ride_service.cancel_ride(active_ride.id, "server_shutdown")
            finally:
                hardware.close()
                app_instance.state.navigation_hardware = None


app = FastAPI(title="4WD Car Backend", version="0.2.0", lifespan=lifespan)
app.state.navigation_hardware = None


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
    elif exc.code in ("ride_already_running", "ride_not_active"):
        http_status = status.HTTP_409_CONFLICT
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
        "navigation_mode": NAVIGATION_MODE,
        "hardware_ready": app.state.navigation_hardware is not None,
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


@app.post(
    "/api/rides",
    response_model=RideStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_ride(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """创建行程并按显式启动模式注册后台导航。

    参数说明：
    payload: 前端 JSON 请求体，只允许 start、waypoints、end。
    background_tasks: FastAPI 为本次请求提供的后台任务容器。

    分步逻辑：
    1. 使用 RideCreateRequest 校验外部输入。
    2. 创建行程并立即准备 202 响应。
    3. fake 模式注册模拟行程，hardware 模式注册真实 GridNavigator。
    """
    request = RideCreateRequest.from_payload(payload)
    hardware = None
    if NAVIGATION_MODE == NAVIGATION_MODE_HARDWARE:
        hardware = app.state.navigation_hardware
        if hardware is None:
            raise RuntimeStateError(
                "hardware_not_ready",
                "真实导航硬件尚未初始化",
            )

    ride = ride_service.submit_ride(request)
    if hardware is not None:
        background_tasks.add_task(
            ride_service.run_hardware_ride,
            ride.id,
            hardware.navigator,
        )
    else:
        background_tasks.add_task(
            ride_service.run_fake_ride,
            ride.id,
            FAKE_RIDE_STEP_DELAY_SECONDS,
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
    2. 调用 RideService 终止活动行程。
    3. 返回取消后的关键状态。
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

    hardware = None
    if NAVIGATION_MODE == NAVIGATION_MODE_HARDWARE:
        hardware = app.state.navigation_hardware
        if hardware is None:
            raise RuntimeStateError(
                "hardware_not_ready",
                "真实导航硬件尚未初始化",
            )

    ride = ride_service.cancel_ride(ride_id, reason)
    if hardware is not None:
        hardware.motor.brake()
    return {
        "id": ride.id,
        "status": ride.status,
        "current_position": ride.current_position,
        "message": ride.eta_text,
    }


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


@app.get("/api/mail/latest", response_model=LatestMailResponse)
def get_latest_mail():
    """返回最近一次到达邮件状态。

    参数说明：
    无。

    分步逻辑：
    1. 从 RuntimeState 读取最近邮件记录。
    2. 返回给前端邮箱页面。
    """
    return runtime_state.get_latest_mail()


app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)
