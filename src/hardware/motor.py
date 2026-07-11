"""
【小车电机控制底层驱动 - 新手修改指南】

这个文件是小车运动的“总控中心”。
所有上层功能（比如循迹、避障）都应该调用这里的 forward()、backward() 等方法，
绝对不要在上层代码里直接写 GPIO.output 控制引脚！

🛠️ 给新手的排坑与修改原则：
1. 嫌车跑得太快或太慢？
   - ❌ 不要改这里的代码。
   - ✅ 去改调用这些方法的上层代码里的速度参数。
2. 某个动作（比如前进）方向反了？
   - ✅ 就在这里改！找到对应的动作方法，互换 HIGH 和 LOW。
   - 提示：IN1 和 IN2 控制左轮（一个负责正转，一个负责反转）。
          IN3 和 IN4 控制右轮。
"""

from src import config


class MotorController:
    """通过树莓派的 RPi.GPIO 库来控制左右两路电机的类。"""

    def __init__(self, gpio=None):
        # 【为什么这里要用 try...except？】
        # 有时候我们想在电脑（Windows/Mac）上写代码并测试逻辑，但电脑上没有 RPi.GPIO 这个库。
        # 这样写可以在实机上自动加载库，如果找不到库，会给出清晰的报错，而不是报一堆看不懂的错。
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError("❌ RPi.GPIO 库只能在树莓派真机上运行！请在树莓派上执行此代码。") from exc

        self.gpio = gpio
        # 这两个变量用来保存左右轮的“油门”（PWM调速器），先占个位置
        self._pwm_left = None
        self._pwm_right = None
        
        # 初始化引脚（接通电源，准备就绪）
        self._setup_gpio()

    def forward(self, left_speed, right_speed):
        """前进：左右电机都向前转。
        
        【修改指南】如果输入前进命令，车子却后退了，说明你的电机线接反了。
        不用重新拔插线，只要把下面的 HIGH 和 LOW 对调即可！
        比如把 HIGH, LOW, HIGH, LOW 变成 LOW, HIGH, LOW, HIGH。
        """
        self._drive(
            self.gpio.HIGH,  # IN1 (左轮前进引脚) 供电
            self.gpio.LOW,   # IN2 (左轮后退引脚) 断电
            self.gpio.HIGH,  # IN3 (右轮前进引脚) 供电
            self.gpio.LOW,   # IN4 (右轮后退引脚) 断电
            left_speed,
            right_speed,
        )

    def backward(self, left_speed, right_speed):
        """后退：左右电机都反向转。"""
        self._drive(
            self.gpio.LOW,   # IN1 断电
            self.gpio.HIGH,  # IN2 供电，左轮后退
            self.gpio.LOW,   # IN3 断电
            self.gpio.HIGH,  # IN4 供电，右轮后退
            left_speed,
            right_speed,
        )

    def left(self, left_speed, right_speed):
        """左转：左电机停（或慢速），右电机向前转。
        注意：这是普通转弯（画圆弧），小车会一边前进一边向左偏。
        """
        self._drive(
            self.gpio.LOW,   # 左轮不给前进动力
            self.gpio.LOW,   # 左轮也不给后退动力 -> 左轮停止
            self.gpio.HIGH,  # 右轮前进
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def right(self, left_speed, right_speed):
        """右转：左电机向前转，右电机停。"""
        self._drive(
            self.gpio.HIGH,  # 左轮前进
            self.gpio.LOW,
            self.gpio.LOW,   # 右轮停止
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def spin_left(self, left_speed, right_speed):
        """原地左旋（像坦克一样）：左电机往后倒，右电机往前开。"""
        self._drive(
            self.gpio.LOW,
            self.gpio.HIGH,  # 左轮后退
            self.gpio.HIGH,  # 右轮前进
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def spin_right(self, left_speed, right_speed):
        """原地右旋：左电机往前开，右电机往后倒。"""
        self._drive(
            self.gpio.HIGH,  # 左轮前进
            self.gpio.LOW,
            self.gpio.LOW,
            self.gpio.HIGH,  # 右轮后退
            left_speed,
            right_speed,
        )

    def brake(self):
        """【紧急刹车】
        不仅要把方向引脚全部拉低，还要把占空比（油门）松开，双管齐下确保停车。
        """
        # 切断所有方向的逻辑信号
        self.gpio.output(config.MOTOR_IN1, self.gpio.LOW)
        self.gpio.output(config.MOTOR_IN2, self.gpio.LOW)
        self.gpio.output(config.MOTOR_IN3, self.gpio.LOW)
        self.gpio.output(config.MOTOR_IN4, self.gpio.LOW)
        # 松开“油门”
        self._pwm_left.ChangeDutyCycle(0)
        self._pwm_right.ChangeDutyCycle(0)

    def close(self):
        """【清理战场，安全退出】
        这个方法极其重要！程序结束前必须调用。
        如果不释放 GPIO，引脚会一直保持最后的通电状态，车子可能会一直跑下去或者烧坏电机驱动板。
        """
        try:
            self.brake() # 先踩死刹车
        finally:
            # 停止 PWM 输出
            self._pwm_left.stop()
            self._pwm_right.stop()
            # 让树莓派把所有用过的引脚恢复成安全的默认状态
            self.gpio.cleanup()

    def _setup_gpio(self):
        """【幕后准备工作】初始化引脚。
        方法名前面带下划线 `_`，意思是“这是内部使用的方法，外部代码不要乱叫”。
        """
        # 告诉树莓派：我们用的是芯片针脚编号（BCM），而不是板子上的物理针脚排号
        self.gpio.setmode(self.gpio.BCM)
        # 屏蔽烦人的系统警告
        self.gpio.setwarnings(False)

        # 【安全第一】设置引脚为输出模式时，立刻把初始状态设为 LOW（低电平/断电）。
        # 防止代码刚启动，车子就抽风动一下。
        self.gpio.setup(config.MOTOR_ENA, self.gpio.OUT, initial=self.gpio.HIGH) # 使能端口A (控制左轮速度)
        self.gpio.setup(config.MOTOR_IN1, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_IN2, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_ENB, self.gpio.OUT, initial=self.gpio.HIGH) # 使能端口B (控制右轮速度)
        self.gpio.setup(config.MOTOR_IN3, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_IN4, self.gpio.OUT, initial=self.gpio.LOW)

        # 【设置 PWM (脉冲宽度调制)】
        # PWM 就是通过极其快速地“开关开关开关”来控制平均电流，从而控制速度。
        self._pwm_left = self.gpio.PWM(config.MOTOR_ENA, config.MOTOR_PWM_FREQUENCY)
        self._pwm_right = self.gpio.PWM(config.MOTOR_ENB, config.MOTOR_PWM_FREQUENCY)
        
        # 启动 PWM，但先把占空比设为 0 (意思是开局不给油)
        self._pwm_left.start(0)
        self._pwm_right.start(0)

    def _drive(
        self,
        left_forward_pin_value,
        left_backward_pin_value,
        right_forward_pin_value,
        right_backward_pin_value,
        left_speed,
        right_speed,
    ):
        """【核心驱动引擎】
        所有前进、后退、转弯的方法，最后都在使唤这个方法。
        把所有控制硬件的代码集中在这里，一旦底层逻辑要改，只改这里就行，不用去每个动作里挨个改。
        """
        # 1. 检查速度是否合法
        self._validate_speed("left_speed", left_speed)
        self._validate_speed("right_speed", right_speed)

        # 2. 设置电机方向 (给 IN1 到 IN4 通电或断电)
        self.gpio.output(config.MOTOR_IN1, left_forward_pin_value)
        self.gpio.output(config.MOTOR_IN2, left_backward_pin_value)
        self.gpio.output(config.MOTOR_IN3, right_forward_pin_value)
        self.gpio.output(config.MOTOR_IN4, right_backward_pin_value)
        
        # 3. 踩下油门 (改变 PWM 占空比，范围 0-100)
        self._pwm_left.ChangeDutyCycle(left_speed)
        self._pwm_right.ChangeDutyCycle(right_speed)

    @staticmethod
    def _validate_speed(name, speed):
        """【参数检查站】防止有人乱填速度把程序搞崩"""
        # 占空比只能是 0% 到 100%，给个 150 或者 -50 硬件会直接报错
        if speed < 0 or speed > 100:
            raise ValueError(f"❌ 速度参数错误: {name} 必须在 0 到 100 之间，你填了 {speed}")