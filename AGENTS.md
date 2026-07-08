# Project Overview

本项目是计算机工程实践项目，硬件为 Yahboom 4WD 树莓派智能小车。

# Environment

开发方式：

- Windows 本地 VS Code 写代码。
- WinSCP 上传文件到树莓派。
- PowerShell SSH 登录树莓派运行代码。

树莓派项目目录：`/home/pi/4wd_project`

Yahboom 出厂示例源码可能位于 `/home/pi/SmartCar`（wiringPi）和 `/home/pi/python`（Python），不要等同于当前项目目录。

已使用过的 SSH 信息：

- IP：`192.168.50.1`
- 用户：`root`
- 常用密码：`yahboom`

注意：这些登录信息只用于本地实验说明，不得写入正式代码、公开文档或提交记录。

# Reference Project Policy

仓库中有 `参考项目/` 目录，里面包含往年项目的报告、PPT 和源代码。

参考项目主题为“单兵辅助侦察智能车”，包含循迹、避障、A* 路径规划、邮件、人脸识别、全景拍摄、摩斯电码等功能。

`参考项目/` 默认只读，作为理解和迁移参考用。

# Known Risks

参考源码可能存在：

- 硬编码 IP、邮箱授权码、API Key、微信密钥等敏感信息。
- 与当前小车不匹配的 GPIO 引脚、摄像头编号、路径和依赖。
- 出厂系统可能自启动 `mjpg` 视频服务和 `bluetooth_control`，占用摄像头、GPIO 等临界资源。
- `GPIO.cleanup` 少写括号的问题，正确写法应为 `GPIO.cleanup()`。
- 报告/PPT 描述和源码实现不完全一致的情况。

不要默认参考源码可以直接运行。
