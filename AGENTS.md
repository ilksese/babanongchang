# 项目版本

- 桌面用 ADB 操作手机。CLI 使用 `uv run babanongchang ...`，桌面界面使用 `uv run babanongchang app`。
- Android APK 位于 `android/`，通过无障碍服务在本机调用共享 Python 流程。构建和验证见 `android/README.md`；共用代码须兼容 APK 的 Python 3.10 和桌面的 Python 3.14。
- 用户要求安装本项目 APK 时，使用 Android 版；若尚无 APK，先在 `android/` 执行 `./gradlew assembleDebug`，再通过 ADB 安装 `android/app/build/outputs/apk/debug/app-debug.apk`。安装不代表授权启动自动化流程。

# 开发与验证

- 使用 `uv` 管理锁定为 3.14.x 的 Python 环境；首次安装依赖运行 `uv sync`。
- 全量测试：`uv run python -m unittest discover -s tests`。
- 单项测试使用 dotted test ID，例如 `uv run python -m unittest tests.test_config.LoadProjectConfigTest.test_uses_defaults_when_file_is_missing`。
- 测试通过 fake ADB/OCR 运行，不需要手机。`uv run babanongchang ...` 会唤醒设备并真实操作支付宝或淘宝；仅在用户明确要求且设备已连接、授权、解锁时运行。无设备冒烟检查使用 `uv run babanongchang --help`。

# 代码边界

- CLI 和 Android 入口负责提供设备、OCR、配置、时钟和日志。农场运行入口在 `workflow.py`；支付宝、淘宝和挪了个箭各自维护流程。共享流程不导入入口或具体设备适配。
- 支付宝任务文案与规则归 `farm/alipay/task_pool.py`；新增操作类型时扩展 `TaskOperation` 并在同目录的 `task_executors.py` 注册执行器。
- UI 跳转保持“一次点击后识别目标页面”：复用 `tap_and_wait`、稳定帧等待和 `back_until`，不要用重复点击或固定坐标替代页面状态判断。

# 容易混淆的运行时约定

- 每次运行时读取 OCR 配置：CLI 从工作目录加载 `babanongchang.toml`，APK 从应用私有诊断目录加载。业务流程通过传入的时钟等待，以保留 Android 暂停时间与桌面取消语义。
- `babanongchang.toml`、`TextHandle` 和 `back_until` 的 timeout/interval 单位是毫秒；业务自动化方法的 `timeout`、`duration_seconds` 通常是秒，传给底层等待前需乘以 1000。

## Agent skills

### Issue tracker

创建、读取或更新规格与任务时，使用 GitHub Issues；规则见 `docs/agents/issue-tracker.md`。

### Triage labels

分类或更新任务状态时，使用 `docs/agents/triage-labels.md` 中的五种标准标签。

### Domain docs

讨论领域概念、编写规格或修改代码前，按 `docs/agents/domain.md` 读取术语表和相关 ADR；采用单上下文布局。
