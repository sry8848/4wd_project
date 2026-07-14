# 二维码识别实机诊断指南

## 1. 测试前释放摄像头

关闭浏览器页面不会停止 MJPEG 预览服务。独立扫码前必须停止实时预览和后端，确认没有其它进程占用摄像头：

```bash
sudo systemctl stop 4wd-camera.service
pgrep -af 'stream_camera_mjpeg|uvicorn|test_qr'
sudo fuser -v /dev/video*
```

使用稳定设备路径确认真正的视频节点：

```bash
ls -l /dev/v4l/by-id/
readlink -f /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0
```

## 2. 先测试固定摄像头扫码

先不要移动舵机，直接把二维码放入画面：

```bash
python3 src/tools/test_qr_detect.py \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --timeout 30 \
  --save-success-photo
```

运行期间每 2 秒输出已处理帧数、耗时和实际分辨率。识别超时会自动把最后一张识别画面保存到：

```text
captures/qr_debug/qr_timeout_时间戳.jpg
```

## 3. 固定扫码成功后再测试双舵机

```bash
python3 src/tools/test_qr_servo_scan.py \
  --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
  --timeout 60 \
  --save-success-photo \
  --enable-servo-motion
```

双舵机扫码会输出扫描位置和帧数；失败时保存 `qr_servo_timeout_时间戳.jpg`。成功图片只有添加 `--save-success-photo` 才会保存。

## 4. 诊断输出怎么判断

终端会输出类似：

```text
path=captures/qr_debug/qr_timeout_20260714_120000.jpg,
resolution=640x480, brightness=73.5/255, sharpness=128.3
```

- `frames=0`：没有画面真正进入识别器，优先检查设备占用、设备路径和摄像头读取阻塞。
- `brightness` 接近 `0`：画面过暗或黑屏；接近 `255`：严重过曝。
- `sharpness` 很低：通常是失焦、运动模糊或二维码距离不合适。该值只适合比较同一摄像头多次测试，不作为固定合格阈值。
- 图片清晰但二维码很小：让二维码占画面宽度约三分之一，并保留完整四周白边。
- 图片清晰且二维码大小合适仍无法识别：在树莓派上直接对保存图片运行 OpenCV 解码，以区分实时读取和解码器兼容问题。

二维码文本必须使用半角冒号和大写 ASCII，例如：

```text
TOLL:GATE1
```
