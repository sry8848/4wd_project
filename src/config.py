"""Project configuration.

Do not store passwords, API keys, email authorization codes, or private IP
credentials in this file.
"""

# 电机引脚来自“环境说明/硬件接口速查手册.xlsx”的 BCM 列。
# Python RPi.GPIO 使用 BCM 编号，不要混用 wiringPi 编号。
MOTOR_IN1 = 20
MOTOR_IN2 = 21
MOTOR_IN3 = 19
MOTOR_IN4 = 26
MOTOR_ENA = 16
MOTOR_ENB = 13

# Yahboom 示例代码中电机 PWM 频率为 2000 Hz。
MOTOR_PWM_FREQUENCY = 2000
