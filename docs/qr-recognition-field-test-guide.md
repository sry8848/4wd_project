# 二维码独立识别实机测试与排错指南

## 1. 目标与边界

本指南只验证以下最小链路：

```text
USB 摄像头被 Linux 识别
-> OpenCV 持续读取图像帧
-> OpenCV QRCodeDetector 检测二维码角点
-> 解码出二维码文本
-> 项目校验 TYPE:ID 格式
```

本阶段不启动电机、不移动舵机、不执行导航，也不把二维码结果接入其它任务。只有独立识别通过后，才能继续验证舵机搜索或导航集成。

成功标准不是“画面能打开”，而是终端在限定时间内明确输出：

```text
DIAG summary result=success ...
Valid QR code detected.
Raw text: TOLL:GATE1
Type: TOLL
Identifier: GATE1
```

## 2. 测试输入契约

基准二维码必须只包含以下纯文本：

```text
TOLL:GATE1
```

- 使用英文半角冒号 `:`，不能使用中文冒号。
- 不带引号、空格、换行或网址前缀。
- 二维码必须黑底模块配白色背景，并保留完整白边。
- 摄像头尽量正对二维码；二维码占画面宽度约三分之一到三分之二。

手机能够扫码只能证明二维码基本有效，不能代替树莓派测试；但手机也不能扫码时，应先修正二维码图片，不要修改项目代码。

## 3. 当前实机已知事实

当前 Sanhao Face USB 摄像头的稳定路径是：

```text
/dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0
```

本次实测该路径指向 `/dev/video0`。数字编号可能在重启或重新插拔后变化，因此测试命令优先使用稳定路径，不把 `/dev/video0` 永久写成硬件事实。

同一摄像头还暴露了 `/dev/video2`；没有证据证明它是本项目需要的采集接口，不要用轮流尝试编号代替设备识别。`/dev/video10` 到 `/dev/video18` 已由 `v4l2-ctl` 识别为树莓派编解码器和 ISP 节点，也不是本测试的目标摄像头。

本车还出现过：

```text
vcgencmd get_throttled
throttled=0x50005
```

这表示当时正在欠压并发生降频。欠压状态下即使偶尔识别成功，也不能作为稳定性验收结果。

## 4. 测试前检查

进入项目目录：

```bash
cd /home/pi/4wd_project
```

### 4.1 检查供电状态

```bash
vcgencmd get_throttled
```

理想结果是：

```text
throttled=0x0
```

如果当前值仍包含 `0x1`，说明当前正在欠压。此时应先处理供电，不要把摄像头掉线或解码不稳定归因于二维码算法。

### 4.2 确认系统识别到目标摄像头

```bash
lsusb
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
readlink -f /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0
```

最低要求：

1. `lsusb` 中存在 USB 摄像头，而不只是 USB Hub。
2. `v4l2-ctl` 把目标节点列在 `Sanhao Face` 下。
3. 稳定路径存在，并解析到实际的 `/dev/videoN` 字符设备。

如果稳定路径不存在，停止本轮测试，转到第 8.1 节。不要继续猜 `--device 0` 或 `--device 1`。

### 4.3 释放摄像头

网页预览和二维码工具不能同时持有同一个摄像头。执行：

```bash
systemctl is-active 4wd-camera
sudo systemctl stop 4wd-camera
sudo fuser -v "$(readlink -f /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0)"
```

`systemctl` 应返回 `inactive`，`fuser` 应没有占用进程。实际节点不是 `/dev/video0` 时，以 `readlink -f` 的结果为准。

## 5. 执行基准测试

优先整行复制，避免 shell 变量为空或反斜杠换行错误：

```bash
python3 -m src.tools.test_qr_detect --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 --width 640 --height 480 --timeout 30
```

程序每 5 秒输出一次进度，不逐帧刷屏。失败时只保存一张最新诊断图片，并覆盖上一次文件：

```text
/home/pi/4wd_project/captures/qr_debug/latest.jpg
```

如果 640×480 的实际帧清晰但无法识别，可以再做一次 1280×720 对照：

```bash
python3 -m src.tools.test_qr_detect --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 --width 1280 --height 720 --timeout 30
```

只有程序输出的 `DIAG frame width=... height=...` 才是摄像头实际返回的尺寸；命令行里的宽高只是请求值。

## 6. `DIAG` 信息含义

| 字段 | 含义 | 能排除什么 |
| --- | --- | --- |
| `device input` | 命令收到的设备参数 | 是否误传了空变量或 `.` |
| `device resolved` | 稳定路径当前解析到的真实节点 | 当前编号到底是 `/dev/video0` 还是其它节点 |
| `decoder version` | 实际使用的 OpenCV 版本 | 是否仍在使用旧版 `QRCodeDetector` |
| `frame width/height/channels` | 第一帧的真实尺寸与通道数 | 请求分辨率是否真正生效 |
| `frames_read` | 成功读取的帧数 | 摄像头是否持续提供画面 |
| `corner_frames` | OpenCV 返回二维码角点的帧数 | 检测阶段是否看到疑似二维码 |
| `decoded_frames` | 成功解出任意文本的帧数 | 解码阶段是否成功 |
| `invalid_payloads` | 解码成功但不满足 `TYPE:ID` 的唯一文本数 | 是否只是二维码内容格式错误 |
| `artifact` | 失败证据图片的保存位置 | AI 实际检查的画面证据 |

`corner_frames=0` 不等于画面里绝对没有二维码；它只表示当前 OpenCV 检测器没有返回角点。必须结合失败图片判断。

## 7. 输出到排错路径的映射

| 关键输出 | 已确定事实 | 下一步最小动作 |
| --- | --- | --- |
| `--device-path does not exist` | Linux 当前没有这个稳定路径 | 执行第 8.1 节 |
| `must point to a V4L2 character device, got: .` | shell 传入了空变量，`Path('')` 变成当前目录 | 使用第 5 节的完整单行命令 |
| `result=runtime_error frames_read=0` | 摄像头没有成功进入稳定读帧阶段 | 检查占用、设备节点和供电 |
| `result=timeout` 且 `corner_frames=0` | 有画面，但 OpenCV 没有检测到二维码角点 | 打开 `latest.jpg`，检查距离、白边、反光、倾斜和二维码是否在画面内 |
| `corner_frames>0` 且 `decoded_frames=0` | 检测到二维码形状，但 OpenCV 没有解出文本 | 转到第 8.3 节，判断解码器能力，不继续猜设备编号 |
| `decoded_frames>0` 且 `invalid_payloads>0` | 二维码已经解码，但内容不符合项目契约 | 重新生成严格等于 `TOLL:GATE1` 的二维码 |
| `result=success` | 独立识别链路通过 | 完成第 9 节验收后再进入舵机或导航集成 |

## 8. 分支排查

### 8.1 USB 摄像头或稳定路径消失

保持下面命令运行，再物理重新插拔摄像头：

```bash
sudo dmesg -w
```

判断：

- 没有任何 USB 新日志：优先检查摄像头、线缆、接口和供电。
- 反复出现 `disconnect`、`reset`：优先检查供电不足或接触不良。
- `lsusb` 有摄像头，但没有 `/dev/videoN`：检查 `uvcvideo` 驱动。
- 稳定路径恢复：返回第 4.3 节，不要直接启动多个摄像头程序。

### 8.2 读到帧但没有检测到角点

通过 WinSCP 打开或复制：

```text
/home/pi/4wd_project/captures/qr_debug/latest.jpg
```

只检查会改变结论的项目：

1. 二维码是否完整进入画面，四周是否保留白边。
2. 小方格边缘是否清晰，而不是只看大轮廓是否清楚。
3. 摄像头是否过度倾斜，屏幕是否反光或出现摩尔纹。
4. 二维码是否占画面宽度三分之一到三分之二。
5. 手机能否从同一张 `latest.jpg` 解出 `TOLL:GATE1`。

调整一项后只重测一次。不要同时修改分辨率、距离、曝光、焦距和二维码内容，否则无法知道哪个变化有效。

### 8.3 检测到角点但没有解码文本

这说明设备选择和基本取景已经不是主要矛盾。当前项目使用树莓派上的 OpenCV 4.1.2；OpenCV 官方问题记录中也存在基础 `QRCodeDetector` 无法解码、而 pyzbar 能解码同一图像的案例：

- <https://github.com/opencv/opencv/issues/22976>
- <https://github.com/opencv/opencv/issues/27783>

此时用手机或 Windows 上的 ZXing 解码同一张 `latest.jpg`：

- 其它解码器也失败：回到第 8.2 节处理图片质量。
- 其它解码器成功得到 `TOLL:GATE1`：证据指向 OpenCV 解码器能力，应单独安排“替换二维码解码器”任务。

替换前先收集树莓派依赖事实：

```bash
cat /etc/os-release
apt-cache policy python3-pyzbar libzbar0
python3 -c "import pyzbar; from pyzbar.pyzbar import decode; print(pyzbar.__version__)"
```

把完整输出交给 AI，再决定安装方式。不要同时保留“OpenCV 失败后再尝试 pyzbar”的双解码兜底；确认新解码器可用后，应保持单一解码来源，原有 `TYPE:ID` 校验继续复用。

## 9. 独立识别验收

必须在同一套供电、摄像头和摆放条件下完成：

1. 有效二维码 `TOLL:GATE1` 在 30 秒内输出 `result=success`。
2. 成功结果中 `Raw text`、`Type`、`Identifier` 与输入完全一致。
3. 程序正常结束后，再次运行能够立即打开摄像头。
4. 执行 `Ctrl+C` 后，再次运行也能够立即打开摄像头。
5. `vcgencmd get_throttled` 当前欠压位没有置位；否则只记录为临时功能现象。

完成以上五项，才能把独立二维码识别标记为通过。暂时不要求不同距离、不同角度、暗光或运动状态全部成功。

## 10. 交给 AI 的最小材料

不要只描述“扫不出来”。一次性提供：

```text
1. 实际执行的完整命令
2. 从 QR-code scan started 到结束的完整终端输出
3. captures/qr_debug/latest.jpg
4. v4l2-ctl --list-devices 输出
5. readlink -f 稳定路径的输出
6. vcgencmd get_throttled 输出
```

AI 应先依据第 7 节选择唯一排错分支，再要求补充信息；不能同时让用户更换编号、升级 OpenCV、调整焦距并重做二维码。

## 11. 测试结束后恢复网页预览

独立测试结束并释放摄像头后执行：

```bash
sudo systemctl start 4wd-camera
systemctl status 4wd-camera --no-pager
```

网页预览恢复不代表二维码识别通过，它只验证摄像头推流链路。
