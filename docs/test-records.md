# 实机测试记录

## 网格导航转向校准

- 记录日期：2026-07-13。
- 事实来源：用户确认此前当前小车实测结果；原始终端输出未保留。
- 原地转速度：`spin_speed = 30`。
- 90° 左转粗转时间：`0.6` 秒。
- 90° 右转粗转时间：`0.5` 秒。
- 180° 左转粗转时间：`1.2` 秒。
- 180° 右转粗转时间：`1.1` 秒。

当前 `GridNavigator` 的 180° 掉头固定使用左旋，因此运行参数采用左转
`1.2` 秒。右转 `1.1` 秒作为已确认硬件事实保留，当前执行路径不使用。

这些时间只与 `spin_speed = 30` 配套，改变速度、电池状态、轮胎或场地后
必须重新校准，不能单独复制时间值。

## 网格导航历史成功基线

- 事实来源：用户确认此前当前小车使用本组参数导航无异常。
- `forward_speed = 20`
- `line_turn_speed = 80`
- `line_left_turn_speed = 80`
- `line_right_turn_speed = 100`
- `search_speed = 5`
- `spin_speed = 30`
- `edge_max_seconds = 20`
- `recovery_max_seconds = 8`
- `ultrasonic_threshold_cm = 20`

本组参数与上面的左右完整粗转时间是当时确认过的实车事实，作为历史对照保留，不代表当前网页运行参数。

## 当前网页运行配置（待完整实车验收）

- `forward_speed = 5`
- `line_turn_speed = 60`
- `line_left_turn_speed = 60`
- `line_right_turn_speed = 80`
- `search_speed = 5`
- `spin_speed = 25`
- `left_turn_rough_seconds = 0.4`
- `right_turn_rough_seconds = 0.3`
- `uturn_rough_seconds = 0.8`
- `turn_acquire_timeout = 5.0`
- `leave_node_min_seconds = 0.10`
- `node_clear_samples = 1`
- `node_confirm_samples = 1`
- `node_center_speed = 30`
- `node_center_seconds = 0.10`
- `obstacle_confirm_samples = 2`
- `line_acquire_timeout = 5.0`
- `line_lost_timeout = 8.0`
- `reverse_speed = 5`
- `reverse_turn_speed = 20`
- `edge_max_seconds = 20`
- `recovery_max_seconds = 8`
- `ultrasonic_threshold_cm = 20`
- `delay_seconds = 0.02`

这组数值与 `src/server/hardware_factory.py` 和 `src/tools/test_grid_navigation.py` 当前默认值一致。只有完成实车验收后，才能将“待验收”更新为“已通过”。
