# 前后端实车模式运行说明

## 1. 启动前条件

1. 先用手动工具确认电机、巡线、超声波和相邻节点导航正常。
2. 把小车准确放在一个可信网格节点中心，并确认车头朝向。
3. 实车模式只能启动一个 Uvicorn worker，禁止使用 `--reload`。
4. 保持终端可操作；异常时先按 `Ctrl+C`，应用关闭流程会取消行程、刹车并释放 GPIO。

树莓派当前使用 Python 3.7，必须安装仓库锁定的兼容依赖，不能直接安装最新版：

```bash
python3 -m pip install --user -r requirements-rpi.txt
python3 -c "import fastapi, uvicorn; print(fastapi.__version__, uvicorn.__version__)"
```

预期版本为 FastAPI `0.103.2`、Uvicorn `0.21.1`。

## 2. 启动实车模式

下面示例表示小车实际位于 `A1`，车头朝东：

```bash
export CAR_NAVIGATION_MODE=hardware
export CAR_INITIAL_POSITION=A1
export CAR_INITIAL_HEADING=east
python3 -m uvicorn src.server.app:app --host 0.0.0.0 --port 8000 --workers 1
```

`CAR_NAVIGATION_MODE` 只接受 `fake` 或 `hardware`。实车模式缺少初始点位或朝向时，后端必须拒绝启动，不能回退到假导航。

启动后先检查：

```bash
curl http://127.0.0.1:8000/api/health
```

成功标准：

```text
navigation_mode = hardware
hardware_ready = true
```

## 3. 首次前后端实车验收

1. 浏览器选择与小车实际位置相同的起点，例如 `A1`。
2. 终点只选择一个相邻节点，例如 `A2`。
3. 不添加途径点，不在首次测试中放动态障碍。
4. 提交后确认页面位置只在真实到达节点后更新。
5. 再次从相邻节点测试运行中“取消行程”，确认小车刹车且进度不再变化。
6. 相邻节点和取消都通过后，再测试包含转向的两条边路线。

## 4. 当前实测导航基线

手动工具和网页实车模式使用同一组默认值：

```text
forward speed = 20
line turn speed = 80
left correction = 80
right correction = 100
search speed = 5
spin speed = 30
90° left  = 0.6 秒
90° right = 0.5 秒
180° left = 1.2 秒
180° right = 1.1 秒
edge timeout = 20 秒
recovery timeout = 8 秒
ultrasonic threshold = 20 cm
```

当前掉头实现固定左旋，因此运行时使用 `180° left = 1.2 秒`。完整事实记录见 `docs/test-records.md`。

## 5. 本地假模式

未设置环境变量时默认使用 `fake`，不会创建 GPIO 对象：

```bash
python3 -m uvicorn src.server.app:app --host 127.0.0.1 --port 8000 --workers 1
```

假模式只用于前端/API 回归和无硬件演示，不用于证明实车已经行驶。
