# 后端架构与接口文档

本文档根据当前 `frontend/` 页面代码反推后端职责、模块边界和第一版 HTTP 接口契约。

目标不是一次性做完整后台，而是让页面从“浏览器内模拟叫车”平滑接入真实树莓派小车，同时保留小车硬件安全边界。

## 1. 当前前端事实

### 1.1 页面能力

当前前端由以下文件组成：

- `frontend/index.html`
- `frontend/app.js`
- `frontend/styles.css`

页面包含两个视图：

- 首页：呼叫小车、填写起点、终点、途径点、查看 5x5 地图、小车当前位置和消息列表。
- 邮箱页：展示到达邮件入口和模拟邮件记录。

### 1.2 当前前端数据模型

前端使用固定 5x5 网格：

```text
A1 A2 A3 A4 A5
B1 B2 B3 B4 B5
C1 C2 C3 C4 C5
D1 D2 D3 D4 D5
E1 E2 E3 E4 E5
```

页面展示坐标使用 `A1` 到 `E5`。后端内部导航模块使用零基坐标 `(row, col)`，因此后端必须提供明确转换：

```text
A1 -> (0, 0)
A2 -> (0, 1)
B1 -> (1, 0)
E5 -> (4, 4)
```

### 1.3 当前前端仍是模拟逻辑

当前 `frontend/app.js` 没有真实 `fetch()`、WebSocket 或后端地址。以下行为都发生在浏览器内：

- 路径由 `buildPath()` 和 `buildMultiStopPath()` 直接生成。
- 小车位置由 `setTimeout()` 定时移动。
- 消息列表由 `setMessage()` 本地追加。
- 到达邮件由 `mailSubject` 和 `mailBody` 本地写入。

这意味着后端文档不能假设已有接口。后端需要把这些模拟行为逐步替换成真实接口。

## 2. 后端目标

### 2.1 当前目标

建立一个运行在树莓派上的轻量 Python 后端，负责：

1. 接收前端叫车请求。
2. 校验起点、途径点和终点。
3. 根据当前小车位置规划路径。
4. 调用现有小车任务模块执行导航。
5. 持续保存当前行程状态、当前位置和消息。
6. 到达终点后调用邮件服务发送到达通知。
7. 为前端提供状态查询接口。
8. 普通取消在前方下一可信节点停车；失败或急停必须立即进入安全停车。

### 2.2 非目标

第一版不做：

- Java/Spring Boot 后端。
- 数据库。
- 用户登录、权限系统、订单系统。
- 多辆车调度。
- 多个并发行程。
- 复杂 WebSocket 协议。
- AI 自动驾驶或自然语言直接控制 GPIO。

第一版只允许一个活动行程。这样更符合当前硬件演示目标，也能避免调度状态过早复杂化。

## 3. 推荐后端架构

### 3.1 部署位置

推荐第一版后端直接运行在树莓派上。

```text
浏览器
  -> HTTP 请求
树莓派 Python 后端
  -> src/tasks/ 和 src/hardware/
Yahboom 4WD 小车
```

原因：

- 小车 GPIO、摄像头和传感器都在树莓派上。
- 后端能直接调用当前仓库已有 Python 模块。
- 不需要先设计电脑端到树莓派的二次通信协议。
- 页面可由同一个后端静态托管，减少跨域问题。

### 3.2 技术选择

推荐使用 FastAPI 作为 HTTP API 层。

原因：

- Python 技术栈与当前项目一致。
- 适合用类型模型描述接口字段。
- 可以托管 `frontend/` 静态文件。
- 自带 OpenAPI 文档，适合小组协作。

但需要注意：后端框架只是入口层，不能把电机、巡线、邮件和 AI 逻辑都堆进 `app.py`。

### 3.3 建议目录结构

```text
src/
  server/
    __init__.py
    app.py
    schemas.py
    point_codec.py
    runtime_state.py
    ride_service.py
    hardware_factory.py
```

文件职责：

| 文件 | 职责 |
| --- | --- |
| `src/server/app.py` | 创建 FastAPI 应用、注册 API 路由、托管前端静态文件 |
| `src/server/schemas.py` | 定义请求和响应数据结构，不 import GPIO |
| `src/server/point_codec.py` | 只负责 `A1` 与 `(row, col)` 互转和点位校验 |
| `src/server/runtime_state.py` | 保存当前小车状态、活动行程、消息序号和最近邮件状态 |
| `src/server/ride_service.py` | 编排行程：规划路径、调用导航、更新状态、触发邮件 |
| `src/server/hardware_factory.py` | 统一创建 `MotorController`、`LineSensor`、`GridNavigator` 等硬件对象 |

已有模块继续保持原职责：

| 现有模块 | 后端使用方式 |
| --- | --- |
| `src/algorithms/astar.py` | 规划网格路径，后端不重复写路径算法 |
| `src/tasks/grid_navigation.py` | 执行真实点到点导航 |
| `src/tasks/line_follow.py` | 巡线和节点识别，不知道前端和 HTTP |
| `src/hardware/*` | 只封装硬件能力，不知道订单和页面 |
| `src/services/mail_sender.py` | 发送邮件，密钥从环境变量读取 |

## 4. 信任边界和安全契约

### 4.1 前端请求是不可信输入

后端必须校验：

- `start`、`end`、`waypoints` 都必须是 `A1` 到 `E5`。
- 起点、途径点、终点不能重复。
- 起点和终点不能相同。
- 途径点数量第一版建议最多 3 个，避免演示路径过长。
- 有活动行程时不能创建新行程，返回 `409 conflict`。

前端校验只改善用户体验，不能替代后端校验。

### 4.2 小车当前位置不能由乘客请求决定

前端可以展示当前位置，但不应该在叫车请求里传“当前小车位置”。当前真实位置应由后端运行状态维护。

第一版建议服务启动时明确设置初始位置和朝向：

```text
current_position = C3
heading = north/east/south/west 之一
```

实机演示前如果小车没有放在该点位，应先用维护接口或启动参数校准。不能让前端用户随意提交小车当前位置。

### 4.3 运动必须可停止

以下场景必须触发停车：

- 行程取消到达前方下一可信节点。
- 急停接口被调用。
- 导航返回失败。
- 路径规划无路可走。
- 传感器超时或丢线。
- 后端进程收到中断信号。

接口层不能直接操作 GPIO。急停接口也应调用后端统一的控制服务，由服务层调用 `motor.brake()`。

### 4.4 敏感信息不得写入代码

邮件配置继续使用环境变量：

- `MAIL_SMTP_HOST`
- `MAIL_SMTP_PORT`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_FROM`
- `MAIL_TO`

后续 AI API Key、微信密钥等也只能走环境变量或本地不提交配置。

## 5. 状态模型

### 5.1 小车状态

```json
{
  "online": true,
  "mode": "idle",
  "current_position": "C3",
  "heading": "north",
  "active_ride_id": null,
  "last_message": "等待小车上报位置。",
  "updated_at": "2026-07-09T15:30:00+08:00"
}
```

`mode` 取值：

| 值 | 含义 |
| --- | --- |
| `idle` | 空闲，可接收新行程 |
| `running` | 正在执行行程 |
| `stopping` | 正在停车或取消 |
| `error` | 发生错误，需要人工确认 |

### 5.2 行程状态

```json
{
  "id": "ride-20260709-153000",
  "status": "to_pickup",
  "start": "A1",
  "waypoints": ["C2"],
  "end": "E5",
  "current_position": "B3",
  "route": ["C3", "B3", "A3", "A2", "A1", "B1", "C1", "C2", "C3", "C4", "C5", "D5", "E5"],
  "progress": ["C3", "B3"],
  "eta_text": "来车中",
  "mail_status": "pending",
  "error_message": null,
  "created_at": "2026-07-09T15:30:00+08:00",
  "updated_at": "2026-07-09T15:30:03+08:00"
}
```

`status` 取值：

| 值 | 含义 |
| --- | --- |
| `dispatching` | 后端已接单，准备规划和执行 |
| `to_pickup` | 小车正在前往起点 |
| `arrived_pickup` | 小车已到达起点 |
| `in_trip` | 小车正在从起点前往终点 |
| `canceling` | 已收到取消请求，正在驶向前方下一个可信节点 |
| `arrived` | 小车已到达终点 |
| `failed` | 行程失败，小车应已停车 |
| `canceled` | 行程被取消，小车应已停车 |

`mail_status` 取值：

| 值 | 含义 |
| --- | --- |
| `disabled` | 未配置邮件环境变量或未启用邮件 |
| `pending` | 行程未完成或邮件待发送 |
| `sent` | 到达邮件已发送 |
| `failed` | 邮件发送失败，但行程本身可能已完成 |

### 5.3 消息事件

```json
{
  "seq": 12,
  "type": "car",
  "text": "已到达起点 A1，请上车",
  "created_at": "2026-07-09T15:30:06+08:00"
}
```

`type` 取值建议：

| 值 | 用途 |
| --- | --- |
| `system` | 系统提示、校验失败、重置 |
| `passenger` | 前端发起的叫车请求 |
| `car` | 小车运行消息 |
| `mail` | 邮件发送结果 |

## 6. 第一版 HTTP 接口

接口路径统一以 `/api` 开头。前端静态页面建议由后端根路径 `/` 托管。

### 6.1 健康检查

```http
GET /api/health
```

响应：

```json
{
  "ok": true,
  "service": "4wd-backend",
  "time": "2026-07-09T15:30:00+08:00"
}
```

用途：

- 前端判断后端是否在线。
- 调试时确认 HTTP 服务已启动。

### 6.2 查询网格定义

```http
GET /api/grid
```

响应：

```json
{
  "rows": ["A", "B", "C", "D", "E"],
  "cols": ["1", "2", "3", "4", "5"],
  "points": ["A1", "A2", "A3", "A4", "A5"],
  "blocked_points": [],
  "blocked_edges": []
}
```

说明：

- `points` 示例中省略了后续点位，真实响应应返回 25 个点。
- 第一版可先返回空 `blocked_points` 和 `blocked_edges`。
- 后续如果导航过程中发现动态障碍边，可以把它们返回给前端用于展示。

### 6.3 查询小车状态

```http
GET /api/car/status
```

响应：

```json
{
  "online": true,
  "mode": "idle",
  "current_position": "C3",
  "heading": "north",
  "active_ride_id": null,
  "last_message": "等待小车上报位置。",
  "updated_at": "2026-07-09T15:30:00+08:00"
}
```

前端用途：

- 替换页面初始 `carPoint = "C3"`。
- 初始化顶部小车位置、地图小车 marker 和当前消息。

### 6.4 校准小车位置

```http
POST /api/car/position
```

请求：

```json
{
  "position": "C3",
  "heading": "north"
}
```

响应：

```json
{
  "current_position": "C3",
  "heading": "north",
  "message": "小车位置已校准为 C3，朝向 north"
}
```

约束：

- 仅允许在 `mode = idle` 时调用。
- 如果小车正在运行，返回 `409 conflict`。
- 这是维护接口，不应该暴露成普通乘客操作。

### 6.5 急停

```http
POST /api/car/stop
```

请求：

```json
{
  "reason": "operator_stop"
}
```

响应：

```json
{
  "stopped": true,
  "active_ride_id": "ride-20260709-153000",
  "message": "小车已停车，活动行程已取消"
}
```

约束：

- 无论当前是否有活动行程，都可以调用。
- 必须尽快调用电机停车。
- 如果存在活动行程，应把行程状态更新为 `canceled`。

### 6.6 创建行程

```http
POST /api/rides
```

请求：

```json
{
  "start": "A1",
  "waypoints": ["C2"],
  "end": "E5"
}
```

成功响应：

```http
202 Accepted
```

```json
{
  "id": "ride-20260709-153000",
  "status": "dispatching",
  "start": "A1",
  "waypoints": ["C2"],
  "end": "E5",
  "current_position": "C3",
  "route": [],
  "progress": ["C3"],
  "eta_text": "派单中",
  "mail_status": "pending",
  "error_message": null,
  "created_at": "2026-07-09T15:30:00+08:00",
  "updated_at": "2026-07-09T15:30:00+08:00"
}
```

后端动作：

1. 校验点位。
2. 检查是否已有活动行程。
3. 创建行程状态。
4. 记录乘客消息：`请求路线 A1 → C2 → E5`。
5. 启动后台行程执行。
6. 立即返回 `202`，不要让 HTTP 请求一直阻塞到小车到达终点。

行程执行路径：

```text
当前小车位置 -> 起点 -> 途径点 1 -> ... -> 终点
```

### 6.7 查询活动行程

```http
GET /api/rides/active
```

有活动行程响应：

```json
{
  "id": "ride-20260709-153000",
  "status": "to_pickup",
  "start": "A1",
  "waypoints": ["C2"],
  "end": "E5",
  "current_position": "B3",
  "route": ["C3", "B3", "A3", "A2", "A1", "B1", "C1", "C2", "C3", "C4", "C5", "D5", "E5"],
  "progress": ["C3", "B3"],
  "eta_text": "来车中",
  "mail_status": "pending",
  "error_message": null,
  "created_at": "2026-07-09T15:30:00+08:00",
  "updated_at": "2026-07-09T15:30:03+08:00"
}
```

没有活动行程响应：

```http
204 No Content
```

前端用途：

- 页面刷新后恢复当前行程。
- 替代本地 `running`、`carPoint`、`etaText` 的真实来源。

### 6.8 查询指定行程

```http
GET /api/rides/{ride_id}
```

响应结构与 `GET /api/rides/active` 相同。

错误：

- 不存在时返回 `404 not_found`。

### 6.9 取消行程

```http
POST /api/rides/{ride_id}/cancel
```

请求：

```json
{
  "reason": "passenger_cancel"
}
```

响应：

```json
{
  "id": "ride-20260709-153000",
  "status": "canceling",
  "current_position": "B3",
  "message": "取消请求已收到，小车将在前方下一个节点停车"
}
```

约束：

- 只能取消活动行程。
- 已 `arrived`、`failed` 或 `canceled` 的行程重复取消应返回 `409 conflict`。
- 接口先返回 `canceling`，行程保持活动，前端继续轮询。
- 小车不得回到已走过的节点；完成当前前向边并确认下一节点后停车，再把状态更新为 `canceled`。
- 障碍、循迹失败和急停属于安全例外，可以优先停止或执行安全回退。

### 6.10 查询行程消息

```http
GET /api/rides/{ride_id}/events?after=0
```

响应：

```json
{
  "events": [
    {
      "seq": 1,
      "type": "passenger",
      "text": "请求路线 A1 → C2 → E5",
      "created_at": "2026-07-09T15:30:00+08:00"
    },
    {
      "seq": 2,
      "type": "car",
      "text": "收到叫车请求，当前上报位置 C3",
      "created_at": "2026-07-09T15:30:01+08:00"
    }
  ],
  "next_after": 2
}
```

前端用途：

- 替换当前 `setMessage()` 的本地消息来源。
- 前端可以每 500 到 1000 毫秒轮询一次。

第一版推荐轮询，不强制 WebSocket。原因是当前消息频率低，轮询足够，调试成本低。

### 6.11 查询最近邮件状态

```http
GET /api/mail/latest
```

响应：

```json
{
  "status": "sent",
  "subject": "4WD 小车到达通知：E5",
  "body": "小车已完成路线 A1 → C2 → E5，当前位置 E5。",
  "sent_at": "2026-07-09T15:31:20+08:00",
  "error_message": null
}
```

如果没有发送过邮件：

```json
{
  "status": "none",
  "subject": "暂无真实邮件",
  "body": "完成行程后，后端会记录最近一次到达邮件状态。",
  "sent_at": null,
  "error_message": null
}
```

前端用途：

- 替换邮箱页当前的模拟邮件显示。
- 不需要真的读取邮箱收件箱，只展示本系统最近一次发送结果。

## 7. 统一错误响应

错误响应统一使用：

```json
{
  "error": {
    "code": "invalid_point",
    "message": "起点必须是 A1 到 E5 之间的点位",
    "details": {
      "field": "start"
    }
  }
}
```

建议错误码：

| HTTP 状态 | code | 场景 |
| --- | --- | --- |
| `400` | `invalid_point` | 点位不在 A1 到 E5 |
| `400` | `duplicate_stop` | 起点、途径点、终点重复 |
| `400` | `same_start_end` | 起点和终点相同 |
| `409` | `ride_already_running` | 已有活动行程 |
| `409` | `car_busy` | 小车运行中，不能校准位置 |
| `404` | `ride_not_found` | 指定行程不存在 |
| `503` | `hardware_unavailable` | 树莓派硬件初始化失败 |
| `503` | `mail_unavailable` | 邮件环境变量缺失或 SMTP 不可用 |

## 8. 前端接入建议

### 8.1 页面初始化

当前前端初始化：

```text
carPoint = "C3"
resetRide()
```

接入后端后应改为：

```text
GET /api/car/status
-> setCarPoint(response.current_position)
-> setMessage("系统", response.last_message)
GET /api/rides/active
-> 如果有活动行程，恢复 route/progress/eta/status
GET /api/mail/latest
-> 刷新邮箱页最近邮件
```

### 8.2 叫车

当前前端提交后直接调用：

```text
startRide(start, end)
```

接入后端后应改为：

```text
POST /api/rides
-> 保存 ride_id
-> 禁用叫车按钮
-> 开始轮询 /api/rides/{ride_id}
-> 开始轮询 /api/rides/{ride_id}/events
```

前端本地路径绘制可以先保留作预览，但真实运行中的 `route` 和 `progress` 应以后端返回为准。

### 8.3 重置和取消

当前前端 `resetRide()` 只清空浏览器定时器。

真实接入后需要区分：

- 页面重置：只清 UI，不影响小车，应该仅在无活动行程时允许。
- 行程取消：调用 `POST /api/rides/{ride_id}/cancel`。
- 急停：调用 `POST /api/car/stop`。

不能把“前端重置页面”当成“小车停车”。

### 8.4 邮件页

当前 `simulateMailButton` 只改本地文字。

接入后端后建议：

- 页面进入邮箱页时调用 `GET /api/mail/latest`。
- “模拟到达邮件”按钮可以删除，或改成“刷新邮件状态”。
- 真实邮件发送由行程到达事件触发，不由前端直接触发。

## 9. 后端执行流程

### 9.1 创建行程后的流程

```text
POST /api/rides
-> validate request
-> create ride state
-> return 202
-> background ride worker:
   -> append "收到叫车请求"
   -> plan current_position -> start
   -> execute GridNavigator.navigate()
   -> update current_position and progress
   -> append "已到达起点"
   -> for each waypoint/end:
      -> plan next segment
      -> execute navigation
      -> update progress
   -> when arrived:
      -> status = arrived
      -> call send_email()
      -> record mail status
```

### 9.2 导航失败流程

```text
GridNavigator.navigate() returns no_path/failed
-> motor.brake()
-> ride.status = failed
-> car.mode = error
-> append failure message
-> do not send arrival email
```

### 9.3 取消流程

```text
POST /api/rides/{ride_id}/cancel
-> mark cancellation requested
-> ride.status = canceling
-> finish current forward edge
-> confirm and report the next trusted node
-> motor.brake()
-> ride.status = canceled
-> car.mode = idle
-> append cancel message
```

## 10. AI 接口边界

当前前端没有 AI 控件，因此第一版后端接口不包含 AI。

后续如果加入 AI，建议只做以下边界：

```text
摄像头拍照 -> 后端保存图片 -> AI 分析图片 -> 返回文字结果
```

AI 不允许直接输出电机控制命令。即使未来支持自然语言控制，也必须先转成受限命令，再由后端白名单校验。

未来可选接口：

```http
POST /api/ai/analyze-photo
```

但该接口应在摄像头拍照和图片保存稳定后再设计，不并入第一版叫车后端。

## 11. 验证标准

### 11.1 文档对应的第一版后端完成标准

后端实现完成时必须满足：

1. 浏览器能打开前端页面。
2. `GET /api/car/status` 返回小车当前位置。
3. `POST /api/rides` 能创建行程并返回 `202`。
4. 有活动行程时再次创建行程返回 `409`。
5. 无效点位返回 `400 invalid_point`。
6. 前端能根据轮询结果更新小车位置、路径进度和消息列表。
7. 行程取消会在前方下一可信节点停车，急停会立即调用停车逻辑。
8. 到达终点后记录最近邮件状态。
9. 邮件配置缺失不会导致小车运动失败。
10. 任何导航失败都会停车并把行程标记为 `failed`。

### 11.2 推荐测试顺序

1. 本地测试 `point_codec`：`A1`、`E5`、非法点位、重复点位。
2. 本地测试接口 schema：创建行程、重复行程、错误响应。
3. 不接硬件测试后端状态机：用假导航对象模拟到达、失败、取消。
4. 树莓派上测试 `GET /api/health` 和静态页面托管。
5. 树莓派上测试 `POST /api/car/stop`，确认能停车。
6. 树莓派上测试单段短路线。
7. 最后接入完整前端轮询。

## 12. 关键取舍

推荐第一版采用“HTTP + 轮询”，不是 WebSocket。

理由：

- 当前前端消息频率低，不需要实时双向通信。
- 轮询更容易调试。
- 小车安全不依赖推送实时性，关键安全逻辑在后端和任务层。

如果后续需要摄像头实时画面，可以继续使用当前已有的 `src/tools/stream_camera_mjpeg.py` 独立验证，再考虑是否集成进后端。
