# Project Agent Guide

本项目是计算机工程实践项目，硬件为 Yahboom 4WD 树莓派智能小车。# Project Overview

开发方式：

- Windows 本地 VS Code 写代码。

- WinSCP 上传文件到树莓派。

- PowerShell SSH 登录树莓派运行代码。

树莓派项目目录：`/home/pi/4wd_project`

已使用过的 SSH 信息：

- IP：`192.168.50.1`

- 用户：`root`

- 常用密码：`yahboom`

注意：树莓派上 `python` 指向 Python 2.7。

# Working Principles

- 优先快速形成可验证闭环：电机、传感器、摄像头等硬件先做最小实测，再做复杂功能。
- 优先使用 `docs/` 中已经整理过的结论；原始资料用于核对，不直接当成当前项目事实。
- 涉及 GPIO、接口编号、传感器接线时，必须以 `环境说明/硬件接口速查手册.xlsx` 为首要来源。
- 涉及参考项目功能迁移时，先看 `docs/参考项目模块分析.md`，再读 `参考项目/源代码/`。
- `参考项目/` 默认只读，不要直接复制粘贴整段源码到当前项目。
- 不要把 IP、密码、邮箱授权码、API Key、微信密钥等敏感信息写入代码、文档、提交信息或公开说明。

# Source Selection Guide

## 1.  `docs/`

`docs/` 是当前项目的加工后知识，优先级最高，适合快速决策。

- `docs/reference-replica-plan.md`
  
  - 用途：查总体目标、复刻范围、阶段计划、推荐目录结构、模块边界、四人分工、验收标准。

- `docs/参考项目模块分析.md`
  
  - 用途：查参考项目每个模块的功能、源码位置、依赖、硬编码配置、迁移风险、是否适合优先迁移。
  - 适合问题：参考项目里循迹、避障、A*、人脸识别、全景拍摄、摩斯电码等功能在哪里；哪些模块适合先复刻。

## 2.  `环境说明/`

`环境说明/` 是 Yahboom 小车的厂商资料和本车硬件环境资料，适合确认硬件事实。

- `环境说明/硬件接口速查手册.xlsx`
  
  - 用途：查各模块接口编号。
  - 表结构：`Sheet1` 包含 `分类`、`功能`、`原理图编号`、`Arduino`、`STM32`、`51`、`树莓派`、`wiringPi`、`BCM`、`备注`。
  - 当前项目使用 Python `RPi.GPIO` 时，优先看 `BCM` 列。
  - 不要把 `wiringPi` 编号当成 `BCM` 编号。

- `环境说明/程序源码/树莓派wifi智能小车python版本源代码/`
  
  - 用途：查 Yahboom 官方 Python 示例，比如电机、循迹、红外避障、超声波避障、蓝牙、TCP 控制。
  - 适合问题：某个硬件模块原厂如何初始化、哪些引脚参与、基本控制流程是什么。
  - 注意：示例代码是教学代码，不代表当前项目架构；迁移时要拆成 `hardware/`、`algorithms/`、`tasks/` 等边界。

- `环境说明/程序源码/树莓派wifi智能小车C语言_wiringPi库函数版本源代码/`
  
  - 用途：查 C/wiringPi 版本的原理和对照实现。
  - 适合问题：Python 示例不清楚时，用 C 版本辅助理解硬件动作。
  - 注意：wiringPi 编号不能直接填入 Python `RPi.GPIO` 的 BCM 配置。

- `环境说明/编程教学文档/编程教学文档/`
  
  - 用途：查厂商实验说明和教学步骤。
  - 适合问题：第一次验证某个硬件模块时，应该按什么实验顺序测试。
  - 注意：教学文档偏操作说明，最终代码结构仍以本仓库规范为准。

## 3.  `参考项目/`

`参考项目/` 是往年项目原始材料，适合理解要复刻的产品能力和演示方式。

- `参考项目/源代码/`
  
  - 用途：查参考项目真实实现。
  - 适合问题：参考项目具体怎么做人脸识别、路径规划、邮件发送、图片传输、摩斯电码等。
  - 注意：源码可能包含硬编码 IP、邮箱授权码、API Key、微信密钥、绝对路径和过期依赖。读取时要先识别风险，不要直接复制。

- `参考项目/第三组+邵一睿+徐全志+李铭洋+单兵辅助侦察智能车报告.doc`
  
  - 用途：查项目背景、功能描述、报告写法和最终叙事。
  - 适合问题：报告怎么组织、功能怎么解释、演示目标是什么。
  - 注意：报告描述不一定和源码完全一致。

- `参考项目/第三组+邵一睿+徐全志+李铭洋+单兵辅助侦察智能车.pptx`
  
  - 用途：查演示结构、展示顺序、答辩表达。
  - 适合问题：PPT 怎么讲项目亮点、最终演示应该呈现哪些能力。
  - 注意：PPT 不是实现依据，不能用它确认代码细节。

# Common Lookup Paths

查硬件引脚：

```text
环境说明/硬件接口速查手册.xlsx
-> 环境说明/程序源码/树莓派wifi智能小车python版本源代码/
-> 当前 src/config.py
```

查某个参考功能怎么迁移：

```text
docs/参考项目模块分析.md
-> 参考项目/源代码/
-> docs/reference-replica-plan.md
-> 当前 src/ 对应模块
```

查下一阶段开发安排：

```text
docs/reference-replica-plan.md
-> 当前 src/ 目录
-> 实机验证结果
```

查厂商原始实验：

```text
环境说明/编程教学文档/编程教学文档/
-> 环境说明/程序源码/树莓派wifi智能小车python版本源代码/
-> 环境说明/硬件接口速查手册.xlsx
```

# Search Tips

优先用 `rg` 搜索文本和源码：

```powershell
rg -n "GPIO|BCM|wiringPi|ENA|ENB|IN1|IN2|TRIG|ECHO" 环境说明 参考项目 src docs
rg -n "A\\*|astar|path|路径|寻迹|循迹|tracking" docs 参考项目
rg -n "camera|cv2|face|人脸|全景|stitch|morse|邮件|smtp" docs 参考项目
```

查文件列表时用：

```powershell
rg --files docs 环境说明 参考项目 src
```

遇到二进制文档：

- `.xlsx`：用表格工具或 Python `openpyxl` 只读检查 sheet、列名和单元格。
- `.doc`、`.docx`、`.pptx`：优先看文件名和已有 Markdown 分析；只有需要报告/PPT内容时再打开。

# Implementation Rules

- 修改代码前，先确认当前目标、本质需求、已知事实、假设和验证方式。
- 对多步骤任务，先给短计划，再执行。
- 每次只改当前任务需要的文件，不顺手重构无关代码。
- 硬件访问集中放在 `src/hardware/`，上层任务不要直接操作 GPIO。
- 配置集中放在 `src/config.py`，但敏感信息不得写入仓库。
- 参考源码有问题时，应该删除重写或重构迁移，不要保留错误历史兼容层。
- 实机测试必须有明确停车路径；电机、舵机、GPIO 相关代码要确保异常时也能停止或释放资源。

# Architecture Rules

## 1. 分层职责

- `src/config.py`
  
  - 只放已确认的非敏感配置，例如 GPIO BCM 编号、PWM 频率、阈值、默认路径。
  - 引脚来源必须能追溯到 `环境说明/硬件接口速查手册.xlsx`、厂商示例或实机验证结论。
  - 不在业务代码里为同一硬件写多套引脚兜底；引脚不确定时先查证或实测。

- `src/hardware/`
  
  - 只封装单个硬件能力，例如电机转动、传感器读数、蜂鸣器发声、LED 亮灭、摄像头拍照。
  - 可以 import `RPi.GPIO`、`cv2` 等硬件相关库。
  - 不写业务流程，不判断“为什么现在要倒车/报警/拍照/循迹”。
  - 不直接调用其它无关硬件。例如 `MotorController` 不应该知道蜂鸣器，`Buzzer` 不应该知道小车是否在倒车。

- `src/algorithms/`
  
  - 放纯算法，例如 A*、摩斯码转换、路径格式化。
  - 默认不 import `RPi.GPIO`、`cv2`、网络库或真实硬件模块。
  - 能在 Windows 本地用单元测试验证。

- `src/tasks/`
  
  - 放逻辑编排，例如循迹到节点、倒车雷达、播放摩斯码、巡逻流程。
  - 可以组合 `hardware` 和 `algorithms`，但不要直接操作 GPIO。
  - 优先通过构造参数传入硬件对象，便于测试和复用。只有非常小的手动演示任务可以临时创建硬件对象，但要在注释中说明原因。
  - 默认不负责最终资源释放；资源生命周期由入口层统一管理。若 task 自己创建了硬件对象，必须明确说明它拥有这些对象，并在 `close()` 中释放。

- `src/network/`
  
  - 放网络通信能力，例如图片 TCP 发送/接收、协议编解码、连接超时和传输错误。
  - 不直接操作 GPIO、电机、摄像头等硬件。
  - 不保存 IP、密码、邮箱授权码、API Key、微信密钥等敏感信息；地址和端口由入口参数传入。
  - 协议必须有明确的数据边界，例如长度头、文件大小、超时和错误返回。

- `src/tools/` 或未来 `main.py`
  
  - 只做入口层：解析命令行参数、创建硬件对象、调用 task、打印结果、在最外层 `finally` 中统一停止和释放资源。
  - 不把复杂流程全部堆在 `main()` 里。超过一个简单硬件动作的流程，应下沉到 `src/tasks/`。

## 2. GPIO 生命周期与资源所有权

- 每个硬件类只能清理自己初始化并拥有的 GPIO 引脚。

- 硬件类应保存自己的 `pins`，`close()` 中使用 `GPIO.cleanup(self.pins)`，不要在可复用硬件类里调用无参数 `GPIO.cleanup()`。

- `close()` 必须先把硬件置于安全状态，再释放资源：
  
  - 电机：先 `brake()`，再停止 PWM，再 cleanup 电机 pins。
  - 蜂鸣器：先 `off()`，再 cleanup 蜂鸣器 pin。
  - LED：先熄灭，再 cleanup LED pins。
  - 后台线程：先停止线程并 join，再 cleanup。

- 组合功能中不要中途调用某个硬件的 `close()`。例如“倒车 + 蜂鸣器报警”应先完成任务，再在入口层统一关闭蜂鸣器和电机。

- 如果两个硬件声明使用同一个物理 GPIO，例如蜂鸣器和按键都使用 BCM 8，必须报告为引脚冲突；不要写兼容分支把同一引脚同时当输入和输出。

- 顶层入口可以在程序最终退出时统一关闭所有硬件对象，但不应依赖某个硬件类的全局 cleanup 去顺便清理其它模块。

## 3. 组合动作示例

“倒车时蜂鸣器报警”的正确边界：

```text
src/hardware/motor.py       -> 只提供 backward()/brake()/close()
src/hardware/buzzer.py      -> 只提供 beep()/on()/off()/close()
src/tasks/reverse_warning.py -> 编排“倒车期间间歇蜂鸣”
src/tools/test_reverse_warning.py 或 main.py -> 创建对象、调用 task、finally 中统一 close
```

不要把倒车报警直接写进 `MotorController.backward()`，否则电机层会依赖蜂鸣器，后续单独测试电机、替换提示方式或关闭声音都会变复杂。

## 4. 测试与验证边界

- 优先实机测试而非TDD,不要写无意义的test
- 实机工具放在 `src/tools/`，每个工具只验证一个硬件或一个小任务。
- 电机、舵机、蜂鸣器等会产生物理动作的测试必须限制时长，并确保 `finally` 中停止动作。
- 不能为了测试暴露测试专用字段、测试分支或测试 hook。优先通过构造参数注入假对象。

# Known Risks

- 参考源码可能存在硬编码 IP、邮箱授权码、API Key、微信密钥等敏感信息。
- 参考源码可能与当前 Yahboom 4WD 小车的 GPIO、摄像头编号、路径和依赖不一致。
- 厂商代码可能混用 wiringPi、BCM、BOARD 等不同编号体系，必须确认后再写入当前配置。
- 参考源码中可能存在 `GPIO.cleanup` 少写括号的问题，正确写法应为 `GPIO.cleanup()`。
- 报告、PPT、源码和实机现象可能互相不一致；最终以当前仓库代码和实机验证为准。

注释添加说明：需要标记方法的功能描述和参数说明，以及简单分步逻辑

标准操作流程
开始修改前：

git status
git pull --rebase origin main
修改完成后：

git status
git add .
git commit -m "简要说明本次修改"
git pull --rebase origin main
git push origin main
如果 rebase 过程中出现冲突：

git status
然后打开冲突文件，删除冲突标记：

保留最终正确代码，解决后继续：

git add .
git rebase --continue
如果冲突处理混乱，取消本次 rebase：

git rebase --abort
禁止操作
禁止执行：

git push --force origin main
除非用户明确要求，否则也不要执行：

git push --force-with-lease origin main
