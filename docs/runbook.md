# 运行手册

本文档记录从 Windows 本地开发到树莓派运行的最小步骤。

## 1. 上传代码

当前开发方式：

- Windows 本地 VS Code 写代码。
- 使用 WinSCP 上传到树莓派。
- 树莓派项目目录：`/home/pi/4wd_project`。

## 2. 登录树莓派

通过 PowerShell SSH 登录树莓派。登录信息只用于本地实验，不写入正式代码、公开文档或提交记录。

## 3. 阶段一环境检查

在树莓派上手动执行：

```bash
cd /home/pi
ls -la /home/pi/SmartCar /home/pi/python
ps aux | egrep "mjpg|bluetooth|python"
python3 -c "import RPi.GPIO as GPIO; print(GPIO.VERSION)"
python3 -c "import cv2; print(cv2.__version__)"
```

记录结果到 `docs/test-records.md`。

## 4. 阶段一测试顺序

1. 电机低速短时测试，车轮必须离地。
2. 超声波只读测距测试。
3. 循迹传感器只读测试。
4. 摄像头拍照测试。

不要在传感器只读测试阶段控制电机。
