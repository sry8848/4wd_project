# 网格导航实地测试指南

本文用于指导 2x4 格黑线网格的实车测试。2x4 格表示有 3x5 个节点，共 15 个点，命令行参数应写成 `--rows 3 --cols 5`。

坐标约定：

```text
A1 -- A2 -- A3 -- A4 -- A5
|     |     |     |     |
B1 -- B2 -- B3 -- B4 -- B5
|     |     |     |     |
C1 -- C2 -- C3 -- C4 -- C5
```

## 当前待验证转向基线

以下参数是本轮准备验证的统一运行值；代码默认值、手动工具和网页实车模式必须保持一致：

```text
forward-speed = 5
line-turn-speed = 80
line-left-turn-speed = 80
line-right-turn-speed = 100
search-speed = 5
spin-speed = 30
left-turn-rough-seconds = 0.4
right-turn-rough-seconds = 0.3
uturn-rough-seconds = 0.8（当前固定左旋）
turn-acquire-timeout = 5.0
leave-node-min-seconds = 0.10
node-clear-samples = 1
node-confirm-samples = 1
node-center-speed = 20
node-center-seconds = 0.10
obstacle-confirm-samples = 2
line-acquire-timeout = 3.0
line-lost-timeout = 5.0
reverse-speed = 5
reverse-turn-speed = 20
edge-timeout = 20
recovery-timeout = 8
delay = 0.02
threshold = 20
```

实测完整转向仍是左90°约 `0.6` 秒、右90°约 `0.5` 秒、左180°约 `1.2` 秒、右180°约 `1.1` 秒。当前运行值故意缩短为预转向，随后以速度5沿计划方向精细找线；这些新运行值必须通过本轮实机验证，不能写成已经验证的事实。

## 1. 测试总原则

实地测试按最小风险顺序推进：

1. 只读传感器，不让车动。
2. 架空车轮，短时间测试电机方向。
3. 关闭超声，先跑 `A1 -> A2` 纯巡线。
4. 打开 `--line-debug`，根据四路读数和动作调巡线参数。
5. `A1 -> A2` 稳定后，再跑多边路径。
6. 基础巡线稳定后，再测试超声障碍和 A* 重规划。

任何阶段只要小车冲出线、持续丢线、误判节点或方向明显反了，先停在当前阶段排查，不要继续测更复杂的避障。

## 2. 准备工作

在树莓派项目目录执行：

使用 WinSCP 将本地最新 `src/` 覆盖到 `/home/pi/4wd_project/src/`，树莓派上不执行 Git 命令。随后进入项目目录：

```bash
cd /home/pi/4wd_project
```

测试前确认：

- 小车电量足够，地面黑线边缘清楚。
- 起点必须放在可信节点中心，例如 A1。
- 第一次电机测试必须架空车轮。
- 所有电机运行命令都准备好 `Ctrl+C`，程序会走 `finally` 停车和释放 GPIO。
- Bash 多行命令用反斜杠 `\`，不要用 Windows 的 `^`。

## 3. 测试 1：只读巡线传感器

命令：

```bash
python3 -m src.tools.test_line_sensor --count 20 --interval 0.2
```

观察重点：

| 场景         | 期望输出                                                                    |
| ---------- | ----------------------------------------------------------------------- |
| 四路都在白底     | `left_outer=white left_inner=white right_inner=white right_outer=white` |
| 小车居中压在普通直线 | `left_outer=white left_inner=black right_inner=black right_outer=white` |
| 小车在十字节点    | 内侧两路为 `black`，至少一路外侧为 `black`；四路全黑也可以                                   |

如果黑线输出成 `white`，先检查传感器高度、接线和黑线材质。不要直接改导航代码，因为后续所有判断都依赖这里的读数事实。

## 4. 测试 2：架空车轮测试电机方向

命令：

```bash
python3 -m src.tools.test_motor forward --speed 30 --duration 0.5
python3 -m src.tools.test_motor spin-left --speed 30 --duration 0.5
python3 -m src.tools.test_motor spin-right --speed 30 --duration 0.5
```

观察重点：

| 命令           | 期望现象      |
| ------------ | --------- |
| `forward`    | 左右轮都让车向前走 |
| `spin-left`  | 小车原地左旋    |
| `spin-right` | 小车原地右旋    |

如果 `spin-left` 实际向右转，或者 `forward` 有一侧反转，先修电机方向。巡线参数无法修复电机方向错误。

## 5. 测试 3：A1 到 A2 纯巡线调试

先关闭超声，用最短的一条边测试基础巡线：

```bash
python3 -m src.tools.test_grid_navigation \
  --rows 3 --cols 5 \
  --start A1 --end A2 \
  --heading east \
  --forward-speed 5 \
  --line-turn-speed 80 \
  --line-left-turn-speed 80 \
  --line-right-turn-speed 100 \
  --search-speed 5 \
  --spin-speed 30 \
  --left-turn-rough-seconds 0.4 \
  --right-turn-rough-seconds 0.3 \
  --uturn-rough-seconds 0.8 \
  --turn-acquire-timeout 5 \
  --leave-node-min-seconds 0.10 \
  --node-clear-samples 1 \
  --node-confirm-samples 1 \
  --node-center-speed 20 \
  --node-center-seconds 0.10 \
  --obstacle-confirm-samples 2 \
  --line-acquire-timeout 3.0 \
  --line-lost-timeout 5.0 \
  --reverse-speed 5 \
  --reverse-turn-speed 20 \
  --edge-timeout 20 \
  --recovery-timeout 8 \
  --delay 0.02 \
  --no-ultrasonic \
  --line-debug
```

`--line-debug` 每轮输出一行，例如：

```text
line_debug LO=0 LI=1 RI=1 RO=0 node=0 action=forward motor=forward(5,5)
line_debug LO=0 LI=1 RI=0 RO=0 node=0 action=left motor=left(0,80)
line_debug LO=0 LI=0 RI=1 RO=0 node=0 action=right motor=right(100,0)
line_debug LO=1 LI=1 RI=1 RO=0 node=1 action=node motor=brake()
```

字段含义：

| 字段       | 含义                                                 |
| -------- | -------------------------------------------------- |
| `LO`     | left outer，左外传感器；`1` 表示看到黑线                        |
| `LI`     | left inner，左内传感器；`1` 表示看到黑线                        |
| `RI`     | right inner，右内传感器；`1` 表示看到黑线                       |
| `RO`     | right outer，右外传感器；`1` 表示看到黑线                       |
| `node`   | 当前读数是否被判为节点                                        |
| `action` | 巡线决策：`forward`、`left`、`right`、`search_left`、`node` |
| `motor`  | 实际发给电机的动作和速度                                       |

结束时应看到：

```text
navigation result: arrived
final node: A2
dynamic blocked edges: 0
```

## 6. 如何根据调试输出判断问题

| 现象                            | 优先判断                   | 下一步                                  |
| ----------------------------- | ---------------------- | ------------------------------------ |
| 小车在黑线上，但 `LI/RI` 经常是 `0`      | 传感器没稳定看到黑线             | 调整传感器高度、黑线宽度、环境光                     |
| 输出一直 `action=search_left`     | 小车已经丢线或起点没放准           | 手动摆正到黑线中心，降低 `--forward-speed`       |
| 输出 `action=left`，但小车实际往右偏     | 电机方向或 `left()` 动作语义有问题 | 回到电机方向测试，不要先调速度                      |
| 输出 `action=right`，但车拉不回线      | 右修正力度不足                | 增大 `--line-right-turn-speed` 或降低直行速度 |
| 很快出现 `node=1` 并停车在 A1 附近      | 起点节点离开逻辑或节点判断过早触发      | 起点摆正，观察离开节点期间四路读数                    |
| 到 A2 十字口仍没有 `node=1`          | 节点读数不满足“内侧两路 + 至少一路外侧” | 用只读巡线命令检查十字口实际读数                     |
| `motor=forward(5,5)` 时车明显跑弯 | 左右电机动力不一致              | 检查左右电机、供电和机械阻力，不继续降低当前直行速度              |

核心原则：先相信调试输出。调试输出里的读数错误，先查硬件和摆放；读数正确但动作错误，再查 `decide_line_action()`；动作正确但车身动作不对，再查电机方向和速度参数。

## 7. 测试 4：纯巡线多边路径

`A1 -> A2` 稳定后，再跑完整路径，仍先关闭超声：

```bash
python3 -m src.tools.test_grid_navigation \
  --rows 3 --cols 5 \
  --start A1 --end C5 \
  --heading east \
  --forward-speed 5 \
  --line-turn-speed 80 \
  --line-left-turn-speed 80 \
  --line-right-turn-speed 100 \
  --search-speed 5 \
  --spin-speed 30 \
  --left-turn-rough-seconds 0.4 \
  --right-turn-rough-seconds 0.3 \
  --uturn-rough-seconds 0.8 \
  --turn-acquire-timeout 5 \
  --leave-node-min-seconds 0.10 \
  --node-clear-samples 1 \
  --node-confirm-samples 1 \
  --node-center-speed 20 \
  --node-center-seconds 0.10 \
  --obstacle-confirm-samples 2 \
  --line-acquire-timeout 3.0 \
  --line-lost-timeout 5.0 \
  --reverse-speed 5 \
  --reverse-turn-speed 20 \
  --edge-timeout 20 \
  --recovery-timeout 8 \
  --delay 0.02 \
  --no-ultrasonic \
  --line-debug
```

预期结果：

```text
navigation result: arrived
final node: C5
dynamic blocked edges: 0
```

如果单边稳定、多边不稳定，重点看转向后第一条边是否摆正。应重新校准左右粗转时间和 `--spin-speed`，不能只改巡线速度。

## 8. 测试 5：只读超声后台监控

基础巡线稳定后，再测超声：

```bash
python3 -m src.tools.test_ultrasonic --monitor --threshold 20
```

观察重点：

- 前方 20 cm 内放障碍，应切换到 `OBSTACLE`。
- 移开障碍，应回到 `safe`。
- 如果持续 timeout，先查超声接线和 Trig/Echo 引脚。

这个测试不控制电机，适合单独确认超声阈值。

## 9. 测试 6：静态封边模拟 A* 绕路

不用真实障碍，先用 `--blocked-edge` 模拟 A1-A2 这条边不可走：

```bash
python3 -m src.tools.test_grid_navigation \
  --rows 3 --cols 5 \
  --start A1 --end A2 \
  --heading east \
  --blocked-edge A1-A2 \
  --forward-speed 5 \
  --line-turn-speed 80 \
  --line-left-turn-speed 80 \
  --line-right-turn-speed 100 \
  --search-speed 5 \
  --spin-speed 30 \
  --left-turn-rough-seconds 0.4 \
  --right-turn-rough-seconds 0.3 \
  --uturn-rough-seconds 0.8 \
  --turn-acquire-timeout 5 \
  --leave-node-min-seconds 0.10 \
  --node-clear-samples 1 \
  --node-confirm-samples 1 \
  --node-center-speed 20 \
  --node-center-seconds 0.10 \
  --obstacle-confirm-samples 2 \
  --line-acquire-timeout 3.0 \
  --line-lost-timeout 5.0 \
  --reverse-speed 5 \
  --reverse-turn-speed 20 \
  --edge-timeout 20 \
  --recovery-timeout 8 \
  --delay 0.02 \
  --no-ultrasonic \
  --line-debug
```

预期现象：小车不应直接走 A1-A2，而应绕行，例如从 A1 先转向 B1，再经 B2 到 A2。最终应到达 A2。

这个测试用于确认 A* 和转向状态机，不涉及超声。

## 10. 测试 7：进入边前障碍重规划

把障碍物放在 A1 到 A2 的前方，打开超声：

```bash
python3 -m src.tools.test_grid_navigation \
  --rows 3 --cols 5 \
  --start A1 --end A2 \
  --heading east \
  --forward-speed 5 \
  --line-turn-speed 80 \
  --line-left-turn-speed 80 \
  --line-right-turn-speed 100 \
  --search-speed 5 \
  --spin-speed 30 \
  --left-turn-rough-seconds 0.4 \
  --right-turn-rough-seconds 0.3 \
  --uturn-rough-seconds 0.8 \
  --turn-acquire-timeout 5 \
  --leave-node-min-seconds 0.10 \
  --node-clear-samples 1 \
  --node-confirm-samples 1 \
  --node-center-speed 20 \
  --node-center-seconds 0.10 \
  --obstacle-confirm-samples 2 \
  --line-acquire-timeout 3.0 \
  --line-lost-timeout 5.0 \
  --reverse-speed 5 \
  --reverse-turn-speed 20 \
  --edge-timeout 20 \
  --recovery-timeout 8 \
  --delay 0.02 \
  --threshold 20 \
  --line-debug
```

预期：

- 小车不应撞向障碍。
- 当前边 A1-A2 会被动态封锁。
- 如果存在绕路，最终应到达 A2。
- 结束输出中 `dynamic blocked edges` 应大于 0。

如果一启动就报告障碍但前方没有东西，说明阈值过大、超声朝向不对或环境反射异常。先回到超声只读测试。

## 11. 测试 8：边中途障碍恢复

先让小车从 A1 向 A2 行驶，中途把障碍放到前方：

```bash
python3 -m src.tools.test_grid_navigation \
  --rows 3 --cols 5 \
  --start A1 --end A2 \
  --heading east \
  --forward-speed 5 \
  --line-turn-speed 80 \
  --line-left-turn-speed 80 \
  --line-right-turn-speed 100 \
  --search-speed 5 \
  --spin-speed 30 \
  --left-turn-rough-seconds 0.4 \
  --right-turn-rough-seconds 0.3 \
  --uturn-rough-seconds 0.8 \
  --turn-acquire-timeout 5 \
  --leave-node-min-seconds 0.10 \
  --node-clear-samples 1 \
  --node-confirm-samples 1 \
  --node-center-speed 20 \
  --node-center-seconds 0.10 \
  --obstacle-confirm-samples 2 \
  --line-acquire-timeout 3.0 \
  --line-lost-timeout 5.0 \
  --reverse-speed 5 \
  --reverse-turn-speed 20 \
  --edge-timeout 20 \
  --recovery-timeout 8 \
  --delay 0.02 \
  --threshold 20 \
  --line-debug \
  --debug
```

预期：

1. 小车刹车。
2. 直接倒车沿 A1-A2 原边退回 A1。
3. 倒车期间蜂鸣器按超声缓存距离提示，但距离不决定恢复成败。
4. 稳定识别 A1 后停车，封锁 A1-A2。
5. 小车车头仍朝 east，重新规划绕路。

如果恢复失败，正确结果是停车并报告 `navigation result: failed`。恢复失败时不能继续假装自己在 A1 或 A2。

## 12. 建议记录表

每次实测建议记录：

| 项目                   | 填写内容                                                     |
| -------------------- | -------------------------------------------------------- |
| 日期和场地                | 例如 2026-07-09 实验室地面                                      |
| 命令                   | 完整命令，不要只记参数片段                                            |
| 起点/终点/朝向             | 例如 A1 -> A2，east                                         |
| 是否 `--no-ultrasonic` | 是/否                                                      |
| 是否 `--line-debug`    | 是/否                                                      |
| 最终输出                 | `navigation result`、`final node`、`dynamic blocked edges` |
| 典型调试行                | 复制 3 到 5 行最能说明问题的 `line_debug`                           |
| 实车现象                 | 直行、偏左、偏右、丢线、误判节点、撞障碍、恢复失败                                |
| 下一步动作                | 调速度、查传感器、查电机方向、查超声或查导航状态机                                |

不要只记录“失败了”。没有调试行和实车现象，就无法判断是读数、决策、速度还是导航状态机的问题。
