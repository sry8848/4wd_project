# 本地人脸识别实机验证指南

## 1. 功能边界

本功能使用 OpenCV Haar 级联检测正面人脸，再用本项目实现的 LBPH 特征与本地登记照片比对。

- 全程离线，不使用百度云，也不需要 API Key。
- 人脸照片默认保存在 `captures/faces/<姓名>/`，该目录已被 `.gitignore` 忽略，不会随常规提交上传。
- 当前适合课程演示环境下的少量人员识别，不应作为门禁或身份鉴权依据。
- 摄像头只由 `OpenCVCameraSession` 持有，正常结束、异常和 `Ctrl+C` 都会释放设备。

## 2. 树莓派依赖

项目必须使用 Python 3；树莓派上的 `python` 指向 Python 2.7，因此命令统一写成 `python3`。

```bash
sudo apt update
sudo apt install python3-opencv python3-numpy
cd /home/pi/4wd_project
```

本实现使用 OpenCV 自带的 `haarcascade_frontalface_default.xml`，不需要从参考项目复制 XML，也不依赖 `opencv-contrib` 的 `cv2.face`。

## 3. 登记人员

先单独验证摄像头设备编号，再采集 10 张正面照片：

```bash
python3 src/tools/test_camera.py --backend opencv --device 0
python3 src/tools/test_face_recognition.py enroll Alice --device 0
```

如果设备 0 无法打开，停止占用摄像头的视频服务后尝试 `--device 1`。采集时保证画面中只有一张脸，并轻微改变表情和头部角度。姓名只允许 1 至 32 个中英文字符、数字、下划线或连字符。

## 4. 限时识别

```bash
python3 src/tools/test_face_recognition.py recognize --device 0 --timeout 20
```

默认需要同一身份连续出现 3 帧才成功。成功输出 `Recognized: <姓名>` 并返回退出码 0；超时、只有陌生人或没有检测到人脸时返回退出码 1。

## 5. 阈值校准

距离越小代表越相似，默认阈值为 `0.30`：

```bash
python3 src/tools/test_face_recognition.py recognize --device 0 --threshold 0.25
```

- 把陌生人误认为已登记人员：降低阈值，例如从 `0.30` 改为 `0.25`。
- 本人经常被判定为陌生人：先补充当前光照下的登记照片，再小幅提高阈值。
- 不要只用本人测试。验收至少包括“登记人员成功”和“未登记人员超时”两个场景。

建议把最终现场阈值记录在 `docs/test-records.md`，不要在没有实测数据时修改全局配置。

## 6. 验收记录建议

记录设备编号、分辨率、样本数、阈值、环境光照以及以下结果：

1. 登记过程中只有检测到恰好一张正面人脸时才保存图片。
2. 登记人员在 20 秒内连续 3 帧识别成功。
3. 未登记人员在相同阈值下不会输出已登记姓名。
4. 正常退出和按 `Ctrl+C` 后，摄像头可立即被下一次命令打开。
