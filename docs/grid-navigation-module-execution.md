# 网格导航新状态机设计说明

本文定义网格导航、巡线入点、动态障碍封边和回节点恢复的目标设计。后续代码和实机验收以本文为准。

## 1. 目标与边界

目标场景是正交黑线网格上的点到点导航：

- 节点是十字交叉点，边是两个相邻节点之间的一条黑线。
- 当前位置、起点和终点都用节点坐标表示，例如 `A1`、`A2`、`B2`。
- A* 只规划网格路径，不直接控制车。
- 障碍只表示“当前计划边不可通行”，不表示某个节点永久不可走。
- 不做视觉定位、SLAM、任意障碍识别或真实坐标测量。
- 实车没有编码器和节点编号识别能力，因此只有“稳定进入可信节点”时，软件坐标才可信。

核心原则：

```text
只有在可信节点上才能选边。
只有稳定进入下一个节点后才能更新 current_node。
只有边中稳定巡线时才能把 planned_edge 封锁。
转向、出点、找线、恢复期间都不能根据超声封新边。
```

## 2. 模块职责

### 2.1 不改职责的模块

`src/config.py`

- 保存 GPIO BCM 编号、PWM 频率、阈值等非敏感配置。
- 不写路径规划、巡线动作或障碍处理流程。

`src/algorithms/astar.py`

- 继续负责矩形网格 A*。
- 输入：`grid`、`start`、`end`、`blocked_edges`。
- 输出：节点路径，例如 `[(0, 1), (1, 1), (1, 2), (0, 2)]`。
- `blocked_edges` 仍使用无向边：`frozenset({A2, A3})`。

`src/hardware/line_sensor.py`

- 只负责读取四路巡线传感器并返回 `LineReading`。
- 不判断坐标、不封边、不控制电机。

`src/hardware/motor.py`

- 只封装 `forward`、`left`、`right`、`spin_left`、`spin_right`、`brake`、`close`。
- 不知道网格、节点、障碍或 A*。

`src/hardware/ultrasonic.py`

- 只负责测距和后台更新 `obstacle_detected`、`last_distance`。
- 超声模块本身不知道障碍属于哪条边。
- 是否相信缓存、什么时候封边，由边执行状态机决定。

### 2.2 需要按新口径调整的模块

`src/tasks/line_follow.py`

- 继续提供基础巡线动作判断。
- 需要把“读数、动作、是否节点、是否看到线”一起返回给上层。
- 不决定坐标、不决定封边、不决定 A*。

建议结果对象：

```python
class LineStepResult:
    reading: LineReading
    action: str
    is_node: bool
    line_seen: bool
    centered_line: bool
```

`src/tasks/edge_follow.py`

- `follow_edge()` / `recover_to_start_node()` 的目标语义由边执行器状态机承载。
- 可以保留文件名和对外类名以减少迁移成本，但内部必须按新状态机组织。
- 边执行器只执行“从当前可信节点尝试走向计划相邻节点”。
- 边执行器不调用 A*，不修改全局地图。

建议核心接口：

```python
class EdgeExecutor:
    def execute_planned_edge(self, target_heading, max_seconds):
        ...

    def recover_to_start_node(self, return_heading, max_seconds):
        ...
```

`src/tasks/grid_navigation.py`

- 只维护地图状态：`current_node`、`target_node`、`current_heading`、`dynamic_blocked_edges`。
- 只在可信节点上调用 A* 选边。
- 只根据边执行结果更新坐标、朝向和封锁边。

## 3. 关键概念

### 3.1 可信节点

可信节点是软件允许认为“车就在这个网格点”的唯一状态。

满足条件：

- 已经完成入点确认。
- 车在节点附近停车。
- 上一次边执行结果明确返回“到达计划节点”或“恢复回起点节点”。

不可信状态：

- 转向中。
- 出点中。
- 边中巡线。
- 找线中。
- 遇障碍后恢复中。
- 超时、丢线或转向失败后。

### 3.2 计划边

计划边由导航层在可信节点上确定：

```text
planned_edge = frozenset({current_node, next_node})
```

超声只产生“车头前方近距离有物体”的事实，不知道 `A2-A3`、`A2-B2` 这些边名。封哪条边完全由当前 `planned_edge` 决定。

因此必须保证：只有当车辆已经稳定进入 `planned_edge` 的边中巡线阶段时，才能相信超声并封这条边。

### 3.3 超声缓存门控

后台超声缓存可能滞后，也可能在转向时扫到上一条边附近的障碍。不要直接清空 `ultrasonic.obstacle_detected`，而应在边执行器里做门控。

建议门控对象：

```python
class ObstacleGate:
    def start_edge(self):
        self.hit_count = 0
        self.safe_count = 0
        self.started_at = time.monotonic()

    def check_blocked(self):
        ...
```

新边开始后，障碍门控必须重新计数：

- 转向、出点、找线、恢复阶段不读超声。
- 进入边中后先等待 `arm_delay`。
- 或者先要求连续 `safe_clear_samples` 次读到安全。
- 之后连续 `obstacle_confirm_samples` 次读到障碍，才确认当前计划边被挡。

推荐演示参数：

```text
obstacle_arm_delay = 0.3 ~ 0.5 秒
safe_clear_samples = 1 ~ 2
obstacle_confirm_samples = 2 ~ 3
threshold = 12 ~ 15 cm
```

## 4. 新状态机

网格导航分两层状态机：

- `GridNavigator`：节点级状态机，只管选边和地图。
- `EdgeExecutor`：边级状态机，只管执行当前计划边。

### 4.1 节点级状态机

```text
AT_NODE
  -> 调用 A* 规划 current_node 到 target_node
  -> 取 path[1] 作为 next_node
  -> 生成 planned_edge
  -> 计算 target_heading
  -> 调用 EdgeExecutor.execute_planned_edge()

EDGE_RESULT: reached_next_node
  -> current_node = next_node
  -> current_heading = target_heading
  -> 回到 AT_NODE

EDGE_RESULT: blocked_on_planned_edge
  -> dynamic_blocked_edges.add(planned_edge)
  -> 调用 EdgeExecutor.recover_to_start_node()

RECOVERY_RESULT: recovered_to_start_node
  -> current_node 不变
  -> current_heading = target_heading
  -> 回到 AT_NODE，重新 A*

任意失败
  -> brake()
  -> 返回 failed
```

注意：遇到中途障碍时，`current_node` 不更新为 `next_node`。恢复成功后，车头仍朝向原计划边方向，因为恢复动作使用倒车而不是原地掉头。

### 4.2 边级状态机

```text
ALIGN_TO_EDGE
  粗转到目标方向
  不读超声
  不认节点
  不封边

LEAVE_NODE
  受保护出点
  向目标方向慢速驶出交叉口
  用巡线传感器确认离开节点并进入目标边
  不读超声
  不认下一个节点

EDGE_TRAVEL
  正常巡线
  允许障碍门控检查 current planned_edge
  允许入点确认

EDGE_BLOCKED
  确认障碍后停车
  返回 blocked_on_planned_edge

RECOVER_TO_NODE
  倒车沿原边回原节点
  不根据超声封边
  不封新边
  稳定入点后返回 recovered_to_start_node

FAILED
  超时、丢线、转向失败或恢复失败
```

### 4.3 Mermaid 状态图

```mermaid
flowchart TD
    A["AT_NODE: current_node 可信"] --> B["PLAN_EDGE: A* 选 next_node"]
    B --> C["ALIGN_TO_EDGE: 粗转到目标方向"]
    C --> D["LEAVE_NODE: 受保护出点"]
    D --> E["EDGE_TRAVEL: 边中巡线"]
    E -- "稳定入点" --> F["REACHED_NEXT_NODE: 更新 current_node"]
    F --> A
    E -- "障碍门控确认" --> G["EDGE_BLOCKED: 封 planned_edge"]
    G --> H["RECOVER_TO_NODE: 倒车回原节点"]
    H -- "恢复成功" --> I["BACK_AT_NODE: current_node 不变, heading 保持计划方向"]
    I --> A
    C -- "转向失败" --> Z["FAILED: 停车"]
    D -- "出点失败" --> Z
    E -- "丢线/超时" --> Z
    H -- "恢复失败" --> Z
```

## 5. 转向与目标线确认

### 5.1 为什么不能只靠固定时间

固定时间转向会累积误差。车轮阻力、地面摩擦、电量和左右轮差异都会让 90 度或 180 度转向不稳定。

### 5.2 为什么不能在交叉点中心直接用传感器找线

车停在十字交叉点中心时，四路传感器可能同时压到黑线。此时无论车头朝哪个方向，读数都可能像“节点”，无法可靠区分目标边是哪一条。

所以新版转向不是“原地一直转到看到线”，而是：

```text
时间粗转
-> 受保护出点
-> 在离开十字中心后，用传感器确认进入目标边
```

### 5.3 推荐转向流程

`ALIGN_TO_EDGE`：

1. 根据 `current_heading` 和 `target_heading` 计算左转、右转或掉头。
2. 按对应方向粗转一小段时间。
3. 粗转期间不读超声、不封边、不认节点。
4. 粗转完成后停车，进入 `LEAVE_NODE`。

`LEAVE_NODE`：

1. 慢速前进驶出当前十字口。
2. 如果仍然是节点读数，继续出点，不允许入点。
3. 连续 `node_clear_samples` 次不是节点，才认为离开当前节点。
4. 离开节点后要求看到目标边的线形态，例如内侧至少一路看到线，最好逐步收敛到内侧两路居中。
5. 如果全白丢线，进入受限找线；找线阶段仍不读超声。

当前小车在 `spin_speed = 30` 下的实测参数：

```text
left_turn_rough_seconds = 0.6 秒
right_turn_rough_seconds = 0.5 秒
uturn_rough_seconds = 1.2 秒（当前固定左旋）
leave_node_min_seconds = 0.20 ~ 0.40 秒
node_clear_samples = 3
line_acquire_timeout = 2 ~ 4 秒
```

## 6. 出点逻辑

出点是从可信节点进入计划边的保护阶段。

出点阶段禁止：

- 根据超声封边。
- 把任何节点读数当作下一节点。
- 更新 `current_node`。

出点成功条件：

```text
已经执行最短出点时间
并且连续 node_clear_samples 次读数不是节点
并且巡线传感器看到可跟踪的线
```

如果出点时仍然全白，应短时间按目标方向小幅找线。找线成功后继续；找线超时则返回失败，不更新坐标。

## 7. 边中巡线逻辑

边中巡线是唯一允许动态超声封边的阶段。

每轮循环：

1. 读取巡线传感器。
2. 执行基础巡线动作。
3. 如果处于稳定跟线状态，调用障碍门控。
4. 如果障碍门控确认，返回 `blocked_on_planned_edge`。
5. 如果稳定检测到节点，返回 `reached_next_node`。
6. 如果丢线超过 `line_lost_timeout`，返回失败。

找线期间不封边。原因是找线时车头方向不可信，超声看到的物体不一定属于当前计划边。

## 8. 入点逻辑

入点是坐标更新的唯一依据。

当前节点判断仍可沿用：

```text
LI = 1
RI = 1
并且 LO = 1 或 RO = 1
```

也就是：

```python
left_inner and right_inner and (left_outer or right_outer)
```

但新版不能“一次 node=1 就到点”。必须满足：

```text
已经完成出点
已经处于 EDGE_TRAVEL
不是找线状态
连续 node_confirm_samples 次检测到节点
```

确认后可以轻推居中：

```text
node_center_seconds = 0.05 ~ 0.15 秒
```

然后停车并返回 `reached_next_node`。只有这时 `GridNavigator` 才能执行：

```python
current_node = next_node
current_heading = target_heading
```

## 9. 障碍封边逻辑

新版不使用“进入边前超声封边”作为默认动态障碍逻辑。进入边前只由 A* 避开已知 `blocked_edges`。

动态障碍封边只发生在：

```text
EDGE_TRAVEL
且 planned_edge 已确定
且出点已经完成
且障碍门控已 armed
且连续确认障碍
```

封边流程：

```text
确认障碍
-> brake()
-> dynamic_blocked_edges.add(planned_edge)
-> 返回 blocked_on_planned_edge
-> 进入恢复
```

如果 `dynamic_blocked_edges=3`，说明程序在三条不同的计划边上都确认过障碍。新版通过“出点后才 armed、先清安全缓存、连续确认”降低误封概率。

## 10. 恢复回节点逻辑

中途确认障碍后，恢复目标是回到障碍边的起点节点，而不是继续探索。

恢复阶段：

1. 停车。
2. 沿当前计划边直接倒车。
3. 按倒车巡线规则修正左右轮。
4. 沿原线退回起点节点。
5. 稳定入点确认。
6. 停车。
7. 返回 `recovered_to_start_node`。

恢复阶段禁止：

- 根据超声封边。
- 把中途擦到的线当成新节点。
- 调用 A*。
- 成功后再掉头。

倒车阶段可以用缓存式倒车雷达蜂鸣提示，但只读后台 `last_distance` 缓存，不同步测距，也不把距离远近作为恢复成功或失败的依据。

恢复成功后：

```text
current_node 不变
current_heading = target_heading
```

例如当前计划是 `A2 -> A3`，目标朝向是 east。中途障碍后倒车回到 `A2`，车头仍朝 east。导航层下一轮从 `A2`、heading=east 重新 A*。

## 11. 建议返回值

边执行器建议返回结构化结果，而不是只返回字符串：

```python
class EdgeExecutionResult:
    status: str
    final_heading: str | None
    reason: str | None
```

推荐状态：

```text
reached_next_node
blocked_on_planned_edge
recovered_to_start_node
turn_failed
leave_node_failed
line_lost
timeout
recovery_failed
```

这样 `GridNavigator` 不需要猜测失败发生在哪个阶段。

## 12. 命令行参数建议

`src/tools/test_grid_navigation.py` 应暴露调参入口：

```text
--left-turn-rough-seconds
--right-turn-rough-seconds
--uturn-rough-seconds
--line-acquire-timeout
--leave-node-min-seconds
--node-clear-samples
--node-confirm-samples
--node-center-seconds
--obstacle-arm-delay
--obstacle-clear-samples
--obstacle-confirm-samples
--line-lost-timeout
--reverse-speed
--reverse-turn-speed
--no-reverse-radar
```

演示优先默认值：

```text
node_clear_samples = 3
node_confirm_samples = 3
node_center_seconds = 0.08
obstacle_arm_delay = 0.3
obstacle_clear_samples = 1
obstacle_confirm_samples = 2
reverse_speed = 15
reverse_turn_speed = 20
```

## 13. 视频演示建议

为了稳定录制动态障碍演示：

1. 先用 `--blocked-edge A2-A3 --no-ultrasonic` 录静态封边绕路，验证 A* 和转向路线。
2. 再录动态障碍，固定路线 `A1 -> A3`。
3. 障碍放在 `A2-A3` 边中后段，不要贴近 `A2` 节点。
4. 在 `A2` 节点中心面对 `A3` 时，超声读数应大于阈值。
5. 小车出点后，超声读数再进入阈值内。
6. 阈值建议从 `12 ~ 15 cm` 调起。

期望表现：

```text
A1 -> A2
-> 出 A2 后在 A2-A3 边中确认障碍
-> 封 A2-A3
-> 倒车回 A2
-> A* 重新选择 A2 -> B2 -> B3 -> A3
```

## 14. 单元测试重点

`LineFollower`：

- 节点读数能被识别。
- 普通居中线不会被识别为节点。
- 单步结果包含读数、动作、节点标记和是否看到线。

`EdgeExecutor`：

- 转向阶段不读取超声。
- 出点阶段不读取超声，也不允许入点。
- 连续 `node_clear_samples` 次非节点后才进入边中。
- 找线阶段不封边。
- 边中连续 `obstacle_confirm_samples` 次障碍才返回 `blocked_on_planned_edge`。
- 一次节点读数不算入点，连续 `node_confirm_samples` 次才算。
- 恢复阶段直接倒车，不执行原地掉头。

`GridNavigator`：

- 只在 `reached_next_node` 后更新 `current_node`。
- `blocked_on_planned_edge` 后封锁 `planned_edge`，但不更新 `current_node`。
- `recovered_to_start_node` 后 `current_node` 不变，`current_heading` 保持目标边方向。
- A* 使用 `dynamic_blocked_edges` 重新规划。

## 15. 实机验收顺序

1. 只读巡线传感器，确认白底、普通直线、交叉点读数。
2. 架空测试电机方向和左右动力。
3. 只测转向粗转参数，不跑完整导航。
4. 测 `A1 -> A2` 无超声出点和入点。
5. 测静态封边 `A2-A3` 绕路。
6. 测动态障碍，只允许边中封 `A2-A3`。
7. 测恢复回 `A2` 后重新走 `A2 -> B2 -> B3 -> A3`。

成功标准：

- 坐标只在稳定入点后更新。
- 障碍只在边中确认后封当前计划边。
- 转向、出点、找线、恢复阶段不会误封边。
- 任何失败都停车，不继续假装自己在某个节点。
