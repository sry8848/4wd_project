# 摄像头功能与双舵机扫描实机指南

## 当前功能确认

| 功能 | 当前入口 | 固定视角 | 双舵机搜索 |
| --- | --- | --- | --- |
| 颜色识别 | `src/tools/test_color_detect.py` | 支持 | 支持，识别稳定颜色后停止 |
| 人脸识别 | `src/tools/test_face_recognition.py recognize` | 支持 | 支持，连续确认人脸后停止 |
| 二维码识别 | `src/tools/test_qr_servo_scan.py` | 另有固定扫码入口 | 支持，识别有效 `TYPE:ID` 后停止 |
| 普通拍照 | `src/tools/test_single_photo.py` | 支持 | 支持，每个扫描方向保存一张 |

四个功能统一调用 `src/tasks/camera_servo_scan.py`。公共扫描顺序是“上下角度为外层、左右角度为内层”，默认先看中心，再交替查看两侧：

- 左右：`90,70,110,50,130`
- 上下：`90,75,105`
- 左右舵机：BCM 11 / J2
- 上下舵机：BCM 9 / J3

任何入口只有显式添加 `--enable-servo-motion` 才会初始化和转动舵机。角度命令行参数限制在 20 到 160 度，异常或 `Ctrl+C` 退出时会释放摄像头和两个舵机各自拥有的资源。

## 实机测试前准备

1. 停止后端、实时预览或其他占用摄像头的程序。同一时刻只能有一个程序读取 USB 摄像头。
2. 核对稳定设备路径：

   ```bash
   readlink -f /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0
   ```

3. 将最新的本地 `src/` 覆盖到树莓派的 `/home/pi/4wd_project/src/`。
4. 抬起小车或确保云台周围没有线材、车壳等阻挡物，再允许舵机动作。

以下命令都在树莓派 `/home/pi/4wd_project` 下运行。不要使用 `python`，因为它指向 Python 2.7；统一使用 `python3`。

## 颜色识别并自动寻找

```bash
python3 src/tools/test_color_detect.py \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --enable-servo-motion
```

在某个方向连续达到稳定帧数后停止，并输出颜色、结果图片和最终 `pan/tilt` 角度。未加 `--enable-servo-motion` 时仍按原来的固定视角识别。

## 人脸识别并自动寻找

先按原流程在固定视角完成人脸录入，然后运行：

```bash
python3 src/tools/test_face_recognition.py recognize \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --enable-servo-motion
```

连续确认同一已录入人员后停止，并输出姓名和最终 `pan/tilt` 角度。每次转到新方向都会清空连续帧计数，避免把不同方向的单帧误判拼成一次成功结果。人脸录入本身不转动摄像头，便于被录入人员保持标准正脸和固定距离。

## 二维码识别并自动寻找

```bash
python3 src/tools/test_qr_servo_scan.py \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --enable-servo-motion
```

二维码内容应为 `TYPE:ID`，例如 `TOLL:GATE1`。识别成功后停止并输出内容和最终角度；超时会保存最后一帧诊断照片。

## 转动摄像头并逐方向拍照

```bash
python3 src/tools/test_single_photo.py \
  --backend opencv \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --output-dir captures/servo_scan \
  --enable-servo-motion
```

拍照没有“识别成功”的目标，因此默认完整走过 5 × 3 共 15 个方向，每个方向保存一张带扫描序号、左右角度和上下角度的照片。若使用 `--output captures/photo.jpg`，程序仍会自动在文件名后附加位置和角度，避免 15 张照片互相覆盖。

## 缩小首次实机测试范围

第一次建议只测试三个温和角度，确认上下、左右方向和机械范围正确：

```bash
python3 src/tools/test_single_photo.py \
  --backend opencv \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --pan-angles 90,80,100 \
  --tilt-angles 90 \
  --output-dir captures/servo_smoke_test \
  --enable-servo-motion
```

确认没有撞限位或方向接反后，再使用默认 15 个方向。若默认扫描因每次舵机稳定等待而超过时限，拍照入口可增加 `--servo-scan-timeout 90`；识别入口可增加对应的 `--timeout`。
