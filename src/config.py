"""Project configuration.

Do not store passwords, API keys, email authorization codes, or private IP
credentials in this file.
"""

# 电机引脚来自“环境说明/硬件接口速查手册.xlsx”的 BCM 列。
# 注意：Python RPi.GPIO 使用 BCM 编号，不要把 wiringPi 编号填到这里。
# 一般调速度和动作时不需要改这里；只有确认硬件接线或接口表不一致时才改。
#
# 方向脚的作用：
# - IN1/IN2 控制左侧电机方向。
# - IN3/IN4 控制右侧电机方向。
# - 同一侧通常一个脚 HIGH、另一个脚 LOW 时电机转动。
# - 同一侧两个脚都 LOW 时该侧电机停止。
MOTOR_IN1 = 20
MOTOR_IN2 = 21
MOTOR_IN3 = 19
MOTOR_IN4 = 26

# ENA/ENB 是两侧电机的 PWM 使能脚。
# PWM 占空比越高，电机转得越快；占空比范围在 motor.py 中限制为 0 到 100。
MOTOR_ENA = 16
MOTOR_ENB = 13

# Yahboom 示例代码中电机 PWM 频率为 2000 Hz。
# 新手优先调 test_motor.py 的 --speed，不要先改 PWM 频率。
MOTOR_PWM_FREQUENCY = 2000

# 超声波引脚来自“环境说明/程序源码/”中 Yahboom 官方 Python 示例。
# EchoPin = 0, TrigPin = 1 是厂商出厂默认接线（BCM 编号）。
ULTRASONIC_TRIG = 1
ULTRASONIC_ECHO = 0

# 超时阈值（秒）：Echo 超过这个时间没反应就算超时。
# 100ms 对应约 17m 最大测距，远超过 HC-SR04 的 4m 有效量程。
ULTRASONIC_TIMEOUT = 0.10

# 障碍判定阈值（厘米）：距离小于此值视为有障碍物。
ULTRASONIC_THRESHOLD = 20

# 每次测距采样次数：多次取中位数可降低单次异常值的干扰。
ULTRASONIC_SAMPLES = 3

# 蜂鸣器引脚：BCM 8。
# 注意：此引脚与按键(key=8)共用同一 GPIO，有源蜂鸣器，LOW 发声、HIGH 静音。
BUZZER_PIN = 8

# 舵机引脚：ServoPin = 23 来自 Yahboom 官方示例”servo_ultrasonic_avoid.py”。
# 舵机 PWM 频率固定为 50 Hz（周期 20ms），这是标准舵机的工作频率。
SERVO_PIN = 23
SERVO_PWM_FREQUENCY = 50

# RGB LED 引脚定义：来自 Yahboom 官方示例，使用 PWM 调色。
# R=22, G=27, B=24（BCM 编号）。PWM 频率 1000Hz。
LED_R_PIN = 22
LED_G_PIN = 27
LED_B_PIN = 24
LED_PWM_FREQUENCY = 1000

# 当前实机 Sanhao Face USB 摄像头的稳定 V4L2 路径。
# 该 by-id 路径不会随 /dev/videoN 编号变化，但仅在系统识别摄像头时存在。
CAMERA_DEVICE_PATH = (
    "/dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0"
)

# 固定摄像头障碍视觉初始参数，实机标定阶段每次只调整一类变量。
OBSTACLE_COLOR_MIN_AREA = 1500.0
OBSTACLE_COLOR_CONFIRM_FRAMES = 3
OBSTACLE_COLOR_TIMEOUT_SECONDS = 15.0
TOLL_QR_TIMEOUT_SECONDS = 15.0
TOLL_CLEARANCE_CONFIRM_SAMPLES = 3
TOLL_CLEARANCE_TIMEOUT_SECONDS = 60.0

# 四路巡线传感器引脚来自“环境说明/硬件接口速查手册.xlsx”的 BCM 列。
# 传感器从小车左侧到右侧依次为：左1、左2、右1、右2。
LINE_SENSOR_LEFT_OUTER_PIN = 3
LINE_SENSOR_LEFT_INNER_PIN = 5
LINE_SENSOR_RIGHT_INNER_PIN = 4
LINE_SENSOR_RIGHT_OUTER_PIN = 18

# 参考源码和 Yahboom 常见模块逻辑：检测到黑线时 GPIO 为 LOW。
# 如果只读测试证明当前传感器电平相反，只改这个配置，不要在业务代码里写双套判断。
LINE_SENSOR_BLACK_VALUE = False
