# 网格导航走线与避障源码对照说明

本文目标是帮你看懂三套逻辑之间的关系：

- 当前项目：已经模块化后的网格点到点导航代码。
- 厂商示例：Yahboom 原厂的独立寻迹/避障实验。
- 旧项目：往年项目里的网格路径执行、巡线和避障整合代码。

先给结论：当前 A* 和网格状态机方向基本正确，实车跑偏的重点不在 A*，而在“单条边巡线闭环”和“超声检测是否阻塞巡线循环”。旧项目和厂商代码能提供参数和行为参考，但不能原样搬过来。

## 1. 三套源码各自解决什么问题

| 来源 | 主要文件 | 解决的问题 | 不能直接等同于 |
| --- | --- | --- | --- |
| 当前项目 | `src/tasks/line_follow.py`、`src/tasks/edge_follow.py`、`src/tasks/grid_navigation.py` | 把“网格路径”拆成“一条边一条边巡线”，并支持当前边障碍封锁重规划 | 厂商的连续寻迹小车 |
| 厂商寻迹示例 | `环境说明/程序源码/树莓派wifi智能小车python版本源代码/9.寻迹实验/tracking.py` | 独立沿黑线跑，处理普通弯、锐角/直角 | 网格点到点导航 |
| 厂商超声示例 | `环境说明/程序源码/树莓派wifi智能小车python版本源代码/10.超声波避障/avoid_ultrasonic.py` | 独立根据距离前进/转弯避障 | A* 地图重规划 |
| 旧项目 | `参考项目/源代码/SDC.py` | A* 路径、巡线到节点、超声线程检测、遇障碍后回节点 | 当前项目的模块化实现 |

重要区别：

- 厂商示例是硬件实验，重点是“某个传感器和电机能不能工作”。
- 旧项目是功能整合，能说明演示口径，但耦合重、含敏感配置和历史遗留问题。
- 当前项目是模块化重写，目标是把硬件、算法、任务编排分开，便于测试和修改。

## 2. 当前项目的走线逻辑

当前走线链路如下：

```text
LineSensor.read()
-> LineReading.from_gpio_values()
-> decide_line_action()
-> LineFollower.step()
-> EdgeFollower.follow_edge()
-> GridNavigator.navigate()
```

### 2.1 引脚和黑线电平

配置在 `src/config.py`：

- 电机引脚：`MOTOR_IN1=20`、`MOTOR_IN2=21`、`MOTOR_IN3=19`、`MOTOR_IN4=26`、`MOTOR_ENA=16`、`MOTOR_ENB=13`。
- 四路巡线：`LINE_SENSOR_LEFT_OUTER_PIN=3`、`LINE_SENSOR_LEFT_INNER_PIN=5`、`LINE_SENSOR_RIGHT_INNER_PIN=4`、`LINE_SENSOR_RIGHT_OUTER_PIN=18`。
- 黑线电平：`LINE_SENSOR_BLACK_VALUE=False`。

这和厂商 Python 示例、旧项目 `SDC.py` 的引脚基本一致。黑线为 LOW/False 也一致。

### 2.2 `LineSensor` 只负责读取硬件

文件：`src/hardware/line_sensor.py`

核心职责：

- `LineReading.from_gpio_values(...)`：把四路 GPIO 原始电平转换成四个布尔值。
- `LineSensor.read()`：按左外、左内、右内、右外的顺序读取四路传感器。
- `LineSensor.close()`：只释放巡线传感器自己的 pins。

这里不判断小车该左转、右转、前进还是停车。这个边界是对的：硬件层只读数据，不做业务决策。

### 2.3 当前节点判断

文件：`src/tasks/line_follow.py`

当前 `is_at_node(reading)` 的条件是：

```text
left_inner == black
and right_inner == black
and (left_outer == black or right_outer == black)
```

含义：

- 普通直线中心通常是内侧两路压黑线，外侧不压线。
- 节点/十字附近通常会让内侧两路和至少一路外侧都压到黑线。
- 所以当前项目没有要求四路全部黑，而是“内侧两路 + 至少一个外侧”。

这比旧项目 `SDC.py` 的 `track_node_check()` 更宽松。`SDC.py` 要求四路全部为 False/黑线；如果地面十字贴线比较窄，四路全黑可能不稳定。

旧项目 `All.py` / `Rescue.py` 里也出现过类似“内侧两路 + 至少一个外侧”的节点判断思路，所以当前节点判断不是凭空来的。

### 2.4 当前巡线动作判断

文件：`src/tasks/line_follow.py`

`decide_line_action(reading)` 当前规则是：

| 读数情况 | 当前动作 | 最终电机动作 |
| --- | --- | --- |
| 满足节点条件 | `ACTION_NODE` | `motor.brake()` |
| 左内黑右内白，或左外黑 | `ACTION_LEFT` | `motor.left(0, turn_speed)` |
| 左内白右内黑，或右外黑 | `ACTION_RIGHT` | `motor.right(turn_speed, 0)` |
| 左内黑且右内黑 | `ACTION_FORWARD` | `motor.forward(forward_speed, forward_speed)` |
| 其它情况 | `ACTION_SEARCH_LEFT` | `motor.spin_left(search_speed, search_speed)` |

默认入口参数在 `src/tools/test_grid_navigation.py`：

- `--forward-speed` 默认 20。
- `--line-turn-speed` 默认 80。
- `--search-speed` 默认 8。
- 你实测时传过 `--forward-speed 15 --line-turn-speed 50 --search-speed 6`。

注意：当前实现的左右修正共用一个 `line-turn-speed`。旧项目不是这样，旧项目有不对称补偿：左修正 `left(0,80)`，右修正 `right(100,0)`。

### 2.5 `LineFollower.step()` 的职责

文件：`src/tasks/line_follow.py`

`LineFollower.step()` 执行一次闭环：

```text
读取传感器
-> 判断动作
-> 调用电机动作
-> 返回动作字符串
```

它不知道当前坐标，也不知道终点在哪里。这样设计是为了保持边界清楚：

- 巡线层只管“沿黑线走”。
- 网格导航层才管“A1 到 C5、下一节点、A*、障碍边”。

## 3. 当前项目的一条边执行逻辑

文件：`src/tasks/edge_follow.py`

`EdgeFollower.follow_edge(max_seconds)` 负责执行“从当前节点到相邻节点”的一条网格边。

### 3.1 状态返回值

| 返回值 | 含义 |
| --- | --- |
| `reached_node` | 成功到达下一个节点 |
| `blocked_before_entering` | 进入边前发现障碍 |
| `blocked_mid_edge` | 边中途发现障碍 |
| `timeout` | 超时未到达下个节点 |

### 3.2 执行顺序

```text
1. 进入边前调用 _is_obstructed()
2. 如果有障碍：停车，返回 blocked_before_entering
3. 调用 _leave_current_node()，先离开起点节点
4. 循环：
   4.1 检查障碍
   4.2 执行 line_follower.step()
   4.3 如果 step 返回 ACTION_NODE，说明到达下一个节点
   4.4 超时则停车并返回 timeout
```

### 3.3 和旧项目“先前进 0.2 秒”的关系

旧项目 `SDC.py` 的 `run_track()` 开头是：

```text
run(20,20)
time.sleep(0.2)
```

目的：让车从当前节点中心先驶出一点，避免一开始就把起点识别成“已经到达节点”。

当前项目没有固定写 0.2 秒，而是用 `_leave_current_node()`：

```text
只要传感器还识别为节点，就继续 forward；
直到不再识别为节点，才开始寻找下一个节点。
```

这是更通用的做法，但它依赖节点判断稳定。如果节点判断太宽松，车会多走一段才认为离开节点；如果节点判断太严格，又可能一开始就认为已经离开。

## 4. 当前项目的避障逻辑

当前避障链路如下：

```text
UltrasonicSensor.read_distance()
-> UltrasonicSensor.read_filtered()
-> UltrasonicSensor.is_obstructed()
-> EdgeFollower.follow_edge()
-> GridNavigator.navigate()
```

### 4.1 超声波测距

文件：`src/hardware/ultrasonic.py`

核心函数：

- `read_distance()`：发 Trig 脉冲，等待 Echo，返回单次距离；超时返回 `-1`。
- `read_filtered()`：多次读取，过滤异常值，取中位数。
- `is_obstructed(distance=None)`：如果距离小于阈值，返回 True；如果距离为负数，返回 False。
- `start_monitoring()`：启动后台线程持续更新 `obstacle_detected` 和 `last_distance`。

当前默认配置：

- `ULTRASONIC_THRESHOLD = 20` cm。
- `ULTRASONIC_TIMEOUT = 0.10` 秒。
- `ULTRASONIC_SAMPLES = 3`。

### 4.2 当前网格导航怎么使用超声

文件：`src/tools/test_grid_navigation.py`

入口层创建：

```text
ultrasonic = UltrasonicSensor(threshold_cm=args.threshold)
ultrasonic.start_monitoring()
obstacle_sensor = CachedObstacleSensor(ultrasonic)
edge_follower = EdgeFollower(..., obstacle_sensor=obstacle_sensor, ...)
```

文件：`src/tasks/edge_follow.py`

`EdgeFollower.follow_edge()` 在两个位置调用 `_is_obstructed()`：

- 进入边前。
- 边中途每轮巡线前。

当前入口传入的是 `CachedObstacleSensor`，它的 `is_obstructed()` 只读取 `UltrasonicSensor.obstacle_detected` 缓存值，不触发同步测距。`UltrasonicSensor.start_monitoring()` 在后台线程里持续更新这个缓存值。

这意味着：

```text
一次巡线 step 之前
只读取最近一次后台监控结果
然后立刻读巡线传感器和修正方向
```

这样可以避免超声回波不稳定时拖慢巡线闭环。纯巡线测试仍然可以传 `--no-ultrasonic`，让入口完全不创建超声对象。

重要口径：`--threshold` 只改变“多少厘米算障碍”；`--no-ultrasonic` 才是关闭超声障碍检测的开关。

### 4.3 当前遇障碍后的地图处理

文件：`src/tasks/grid_navigation.py`

`GridNavigator.navigate()` 维护：

- `current_node`：当前可信节点。
- `current_heading`：当前车头方向。
- `dynamic_blocked_edges`：运行中发现被挡住的边。

处理规则：

| 边执行结果 | 导航器行为 |
| --- | --- |
| `reached_node` | 更新 `current_node = next_node` |
| `blocked_before_entering` | 把当前边加入 `dynamic_blocked_edges`，重新 A* |
| `blocked_mid_edge` | 掉头回上一节点，成功后封锁当前边并重新 A* |
| `timeout` 或未知失败 | 停车，返回 `failed` |
| A* 找不到路径 | 停车，返回 `no_path` |

关键安全口径：

- 只有到达可信节点后才更新 `current_node`。
- 中途遇障碍不把车的位置更新到下一节点。
- 当前版本回上一节点用“原地掉头 + 正向巡线”，不是倒车。

## 5. 厂商寻迹示例的对应逻辑

文件：

`环境说明/程序源码/树莓派wifi智能小车python版本源代码/9.寻迹实验/tracking.py`

### 5.1 厂商示例的定位

厂商寻迹示例是单独实验，目标是证明：

- 四路巡线传感器能读到黑线。
- 电机能根据黑线位置修正方向。
- 小车能沿一条黑线或简单路线跑。

它没有：

- A*。
- 网格坐标。
- 当前节点/下一节点。
- 当前边障碍封锁。
- 动态重规划。

所以厂商寻迹逻辑只能作为“巡线动作策略”和“速度参数”的参考，不能直接等同于网格导航。

### 5.2 厂商寻迹的核心规则

厂商代码确认：

```text
检测到黑线：GPIO 为 LOW / False
未检测到黑线：GPIO 为 HIGH / True
```

主要动作：

| 厂商读数情况 | 厂商动作 |
| --- | --- |
| 右锐角/右直角 | `spin_right(100,100)` 并短延时 |
| 左锐角/左直角 | `spin_left(100,100)` 并短延时 |
| 最左侧检测到黑线 | `spin_left(80,80)` |
| 最右侧检测到黑线 | `spin_right(80,80)` |
| 左内黑、右内白 | `left(0,90)` |
| 左内白、右内黑 | `right(90,0)` |
| 左内黑、右内黑 | `run(100,100)` |
| 全白 | 保持上一个动作 |

和当前项目相比，厂商代码有两个明显差异：

- 外侧传感器触发时会用 `spin_left/spin_right` 强修正，而当前项目把外侧也合并成普通 `left/right`。
- 厂商连续寻迹速度很高，直行 `100`，不适合直接拿来跑网格节点。

## 6. 厂商超声避障示例的对应逻辑

文件：

`环境说明/程序源码/树莓派wifi智能小车python版本源代码/10.超声波避障/avoid_ultrasonic.py`

厂商超声示例是“独立避障小车”，逻辑大致是：

```text
读取距离
距离远：前进
距离中等：慢速前进
距离近：原地转向，再测距，再决定继续转或前进
```

它不做：

- A*。
- 网格地图。
- 封锁边。
- 回节点。

因此当前项目不能照搬厂商避障动作。我们的目标不是“看见障碍就随便绕开”，而是：

```text
障碍只挡住当前准备走的边
-> 标记这条边不可走
-> 用 A* 在网格上重新规划
```

这是两个不同问题。

## 7. 旧项目 SDC 的对应逻辑

文件：

`参考项目/源代码/SDC.py`

### 7.1 旧项目的节点检测

`track_node_check()` 读取四路巡线，返回：

```text
四路全部为 False/黑线
```

这比当前项目严格。优点是误判普通直线为节点的概率低；缺点是如果十字线宽度、车身位置或传感器高度不稳定，可能检测不到节点。

当前项目使用“内侧两路 + 至少一个外侧”，属于更宽松的网格节点判断。

### 7.2 旧项目的巡线到节点

`run_track()` 的结构：

```text
1. run(20,20)
2. sleep(0.2)，先离开当前节点
3. while not track_node_check():
   3.1 如果 obstacle_detected 为 True，停车并返回 False
   3.2 读取四路巡线
   3.3 左偏：left(0,80)
   3.4 右偏：right(100,0)
   3.5 直线：run(20,20)
   3.6 丢线：spin_left(5,5)
4. 到节点后返回 True
```

这和当前项目最关键的差异：

- 旧项目左修正和右修正速度不对称：`left(0,80)`、`right(100,0)`。
- 当前项目 `LineFollower` 只有一个 `turn_speed`，左右修正同速。
- 旧项目一开始固定前进 0.2 秒；当前项目用 `_leave_current_node()` 根据传感器状态判断是否离开节点。

### 7.3 旧项目的避障检测

`avoid_obstacle()` 在后台循环测距：

```text
distance = Distance_test()
if distance < 20:
    obstacle_detected = True
else:
    obstacle_detected = False
```

然后 `run_track()` 只是读取 `obstacle_detected` 这个布尔值。

这点对实车很重要：

- 旧项目巡线循环不直接等待超声测距。
- 当前项目已经改为后台监控，巡线循环只读取缓存的 `obstacle_detected`。

所以当前实现已经吸收了旧项目更适合实车闭环的一点：超声测距在后台进行，边执行只读取缓存状态。

### 7.4 旧项目遇障碍后的恢复

旧项目 `move_to_next_position()`：

```text
update_orientation(next_orientation)
if not run_track():
    调整 current_orientation 为反向
    spin_left(...) 掉头
    run_track_back()
    brake()
    return False
```

`follow_path()` 收到 False 后，会把下一个位置标成障碍并重新规划。

当前项目的对应逻辑：

- 进入边前障碍：封锁当前边。
- 中途障碍：掉头回上一节点，成功后封锁当前边。
- 重新 A*。

当前项目比旧项目更符合我们后来确认的口径：障碍只挡“当前准备走的下一条边”，不应该直接把某个节点永久标成不可走。

## 8. 当前项目、厂商、旧项目的核心差异表

| 维度 | 当前项目 | 厂商寻迹 | 旧项目 SDC |
| --- | --- | --- | --- |
| 黑线电平 | False/LOW | False/LOW | False/LOW |
| 巡线引脚 | 3/5/4/18 | 3/5/4/18 | 3/5/4/18 |
| 电机引脚 | 20/21/19/26/16/13 | 20/21/19/26/16/13 | 20/21/19/26/16/13 |
| 直行速度 | CLI 参数，默认 20 | `run(100,100)` | `run(20,20)` |
| 小弯修正 | 左右共用 `turn_speed` | `left(0,90)`、`right(90,0)` | `left(0,80)`、`right(100,0)` |
| 外侧传感器 | 普通左右修正 | 强制原地修正 | 合并进左右修正 |
| 节点判断 | 内侧两路 + 至少一个外侧 | 无网格节点概念 | 四路全黑 |
| 离开起点节点 | 根据传感器状态离开 | 无 | 固定前进 0.2 秒 |
| 超声避障 | 后台线程更新缓存，边执行读取缓存 | 独立避障动作 | 后台线程更新布尔值 |
| 障碍更新地图 | 封锁当前边 | 无地图 | 多数场景标记下一个节点 |
| 中途障碍恢复 | 掉头 + 正向巡线回上一节点 | 无 | 掉头 + `run_track_back()` |

## 9. 对当前实车问题的源码级判断

你看到的现象：

```text
小车在线上歪歪扭扭，然后慢慢扭出线外
```

从源码对照看，最可疑的不是 A*，而是这两点：

### 9.1 超声测距已改为后台监控

当前 `EdgeFollower.follow_edge()` 每轮先 `_is_obstructed()`，再 `line_follower.step()`。

入口层传给 `EdgeFollower` 的是 `CachedObstacleSensor`。它只读取后台线程维护的 `obstacle_detected`，不调用 `read_filtered()`，所以不会在每个巡线 step 前等待超声测距。

如果继续出现“歪歪扭扭然后慢慢出线”，下一步应优先看左右修正速度、外侧传感器强修正和电机左右动力差异，而不是继续怀疑同步超声测距。

### 9.2 左右修正缺少旧项目的不对称补偿

当前：

```text
left -> motor.left(0, turn_speed)
right -> motor.right(turn_speed, 0)
```

你传的 `turn_speed=50`，左右同速。

旧项目：

```text
left(0, 80)
right(100, 0)
```

这说明旧项目实车很可能存在左右轮动力差异，或者右修正需要更强。当前对称参数可能不足以把车拉回黑线。

## 10. 阅读源码建议顺序

如果你想自己看代码，按这个顺序读：

1. `src/config.py`
   先确认引脚、电平、阈值。

2. `src/hardware/line_sensor.py`
   看四路 GPIO 如何变成 `LineReading`。

3. `src/tasks/line_follow.py`
   看 `is_at_node()` 和 `decide_line_action()`，这是走线的核心判断。

4. `src/tasks/edge_follow.py`
   看一条边如何执行，重点看 `follow_edge()`、`_leave_current_node()`、`recover_to_start_node()`。

5. `src/hardware/ultrasonic.py`
   看 `read_filtered()`、`is_obstructed()`、`start_monitoring()`。

6. `src/tasks/grid_navigation.py`
   看遇到边执行结果后如何更新坐标、封锁边、重新 A*。

7. `环境说明/.../9.寻迹实验/tracking.py`
   对照厂商连续寻迹策略。

8. `参考项目/源代码/SDC.py`
   只看巡线、节点、避障线程、路径执行相关函数，不复制里面的敏感配置。

## 11. 后续修改方向

基于这次对照，后续建议按优先级改：

1. 给网格导航实机入口增加“纯巡线模式”或 `--no-ultrasonic`。（已完成）
   目的：先让 `A1 -> A2` 不受超声测距阻塞影响。

2. 把网格导航里的超声障碍检测改成后台监控。（已完成）
   目的：边执行循环只读取缓存的 `obstacle_detected`，不要每轮同步测距。

3. 让左右修正速度分开配置。
   目的：支持旧项目的 `left(0,80)`、`right(100,0)` 这种实车补偿。

4. 增加巡线调试输出模式。
   目的：打印每轮四路读数和动作，定位是传感器判断错、修正方向错、速度不合适，还是节点判断错。

5. 再测试动态障碍重规划。
   目的：基础巡线不稳定时，测避障和 A* 重规划没有意义。
