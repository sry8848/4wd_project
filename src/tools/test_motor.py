"""
【树莓派小车电机测试脚本 - 新手完全指南】

这个脚本的作用是：让你可以通过敲命令，控制小车做一个极其短暂的动作（比如前进、左转），
用来测试电机接线对不对、轮子转的方向对不对。这就是俗称的“冒烟测试”。

⚠️ 终极安全警告 ⚠️
在运行这个脚本之前，【必须把小车底盘垫高，让所有轮子悬空】！！！
千万不要放在桌面上直接测，一旦接线反了，车会直接冲下桌子摔坏。

👉 怎么运行这个脚本？
打开终端（黑框框），输入类似下面的命令：
python -m src.tools.test_motor forward --speed 50 --duration 0.5

👉 调参说明（你怎么改上面的命令）：
1. 动作 (action)：比如 forward (前进), backward (后退), left (左转), spin-left (原地左转)。
   - 这是必填项，不填不让跑。
2. 速度 (--speed)：范围 0 到 100，数字越大跑得越快。
   - 如果设成 30 听到电机嗡嗡响但轮子不转，说明动力不够，可以改大到 50 或 80 试试。
3. 时间 (--duration)：动作持续几秒。
   - 第一次测建议 0.3 秒，最长不能超过 2 秒（代码里做了强制保护，写 3 秒会报错）。
"""

import argparse  # 用来处理你在命令行里敲的那些参数（比如提取出 --speed 后面的数字）
import time      # 用来控制时间（让动作持续零点几秒后停下）

# 导入你自己写的电机控制核心代码
from src.hardware.motor import MotorController


# 【动作字典：你想让车怎么动，就在这里加】
ACTION_TO_METHOD = {
    # 左边是你在命令行里敲的名字，右边是 MotorController 代码里真正的方法名。
    # 如果你以后在 MotorController 里写了新招式（比如写了个 "drift" 漂移），必须来这里登记一下。
    "forward": "forward",          # 前进
    "backward": "backward",        # 后退
    "left": "left",                # 左转
    "right": "right",              # 右转
    "spin-left": "spin_left",      # 原地左转（左轮后退，右轮前进）
    "spin-right": "spin_right",    # 原地右转
}


def parse_args():
    """这个函数专门用来解析你输入的命令行指令"""
    parser = argparse.ArgumentParser(description="运行一个小车电机的简短测试。")
    
    # 必填项：你要做的动作，只能从上面的字典里选，打错字会提示你
    parser.add_argument("action", choices=ACTION_TO_METHOD.keys(), help="要执行的动作名称")
    
    # 选填项：速度，默认是 30
    parser.add_argument(
        "--speed",
        type=int,
        default=30,
        help="占空比（速度），范围 0-100。如果填 30 启动不了，就换 60 或 80 试试。",
    )
    
    # 选填项：时间，默认是 0.3 秒
    parser.add_argument(
        "--duration",
        type=float,
        default=0.3,
        help="动作持续时间（秒）。第一次测试请保持简短！",
    )
    return parser.parse_args()


def main():
    args = parse_args()  # 把你敲的命令解析成程序能看懂的参数字典

    # 【安全锁】强制限制测试时长，防止车子狂奔失控
    if args.duration <= 0 or args.duration > 2:
        # 如果你输入的时间瞎搞（比如负数或者大于2秒），程序会直接报错罢工
        raise ValueError("❌ 为了安全，duration (测试时间) 必须大于 0 且不能超过 2 秒！")

    print(f"🚗 准备执行: {args.action} | 速度={args.speed} | 持续时间={args.duration}秒")
    
    # 启动电机控制器，准备接通硬件
    motor = MotorController()
    
    try:
        # 【核心魔法：动态执行动作】
        # 假设你输入了 "forward"，字典会把它翻译成 "forward"。
        # getattr 会去 motor 里找到名为 "forward" 的函数，并把它打包赋值给 action 变量。
        action = getattr(motor, ACTION_TO_METHOD[args.action])
        
        # 真正开始执行动作，把速度传给左轮和右轮。电机从这一句开始通电转动。
        action(args.speed, args.speed)
        
        # 让程序在这里“睡”一会儿（这时候电机正在疯狂转动）
        time.sleep(args.duration)
        
    finally:
        # 【终极刹车】
        # try...finally 的作用是：不管上面发生了啥（正常跑完、报错崩溃了、或者你手残按了 Ctrl+C 强退），
        # 哪怕天塌下来，最后都一定会执行这段代码。这是保命符！
        motor.close()  # 必须让电机停下，并释放树莓派的引脚控制权
        print("🛑 已经安全停车并清理了 GPIO 引脚，测试结束。")


# 这是 Python 程序的标准入口。如果你是直接运行这个文件，就执行 main() 函数
if __name__ == "__main__":
    main()