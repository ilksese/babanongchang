# 项目版本

- 桌面用 ADB 操作手机。CLI：`uv run babanongchang ...`；桌面界面：`uv run babanongchang app`。打包：`uv run build --windows`，产物是 `dist/babanongchang.exe`。`build/` 是 PyInstaller 中间缓存，不能当程序运行。
- Android APK 在 `android/`。它用 Kotlin 原生实现农场和挪了个箭流程，经无障碍服务在本机截图、识别和操作，不嵌入 Python，也不把参数转给 Python CLI。OCR 使用包内 ONNX 模型、ONNX Runtime 和 OpenCV。构建和验证见 `android/README.md`。
- 桌面 CLI 使用 Python 3.14。配置读取用 `tomllib`，缺失时回退 `tomli`。
- 用户要求安装本项目 APK 时用 Android 版。没有 APK 时，先在 `android/` 执行 `./gradlew assembleDebug`，再 ADB 安装 `android/app/build/outputs/apk/debug/app-debug.apk`。安装不代表授权启动自动化。

# 开发与验证

- Python 环境由 `uv` 锁定为 3.14.x。首次安装依赖：`uv sync`。
- 无设备冒烟：`uv run babanongchang --help`。`uv run babanongchang ...` 会唤醒设备并真实操作支付宝或淘宝；仅在用户明确要求且设备已连接、授权、解锁时运行。
- Android 验证在 `android/` 执行 `./gradlew assembleDebug lintDebug`。构建依赖 JDK 17、Android SDK 36，以及 `prepareOcr` 通过 `uv` 准备的模型。

# 代码边界

- CLI（`cli.py`）负责桌面设备、OCR、配置、时钟和日志。APK 的对应入口是 `NativeAutomation.runNative`，不再调用 `android.py`。农场运行入口在桌面是 `workflow.run_farm`，在 APK 是同名的 Kotlin 实现。支付宝、淘宝、挪了个箭各自维护流程。共享流程不导入入口或具体设备适配。
- 支付宝任务文案与规则在 `farm/alipay/task_pool.py`。新增操作类型时扩展 `TaskOperation`，并在同目录 `task_executors.py` 的 `TASK_EXECUTORS` 注册执行器。
- UI 跳转保持“一次点击后识别目标页面”：复用 `tap_and_wait`、稳定帧等待和 `back_until`。不要用重复点击或固定坐标代替页面状态判断。

# 容易混淆的运行时约定

- OCR 配置每次运行时读取：CLI 从工作目录加载 `babanongchang.toml`，APK 从应用私有目录 `files/cli-output/babanongchang.toml` 加载。业务流程使用传入的时钟等待，以保留 Android 暂停时间与桌面取消语义。
- `babanongchang.toml`、`TextHandle` 和 `back_until` 的 timeout/interval 单位是毫秒。业务自动化方法的 `timeout`、`duration_seconds` 通常是秒，传给底层等待前要乘以 1000。
- 各模块默认不打印、不写运行日志。CLI 只在 `--debug` 时打印并追加当前目录的 `babanongchang.log`；桌面和 APK 用“记录日志”开关控制，默认关闭，下次运行生效。挪了个箭的诊断截图和报告仍按输出目录保存，事件日志跟随上述开关。
