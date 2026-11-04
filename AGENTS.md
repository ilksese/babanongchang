# 开发与验证

- 使用 `uv` 管理锁定为 3.14.x 的 Python 环境；首次安装依赖运行 `uv sync`。
- 全量测试：`uv run python -m unittest discover -s tests`。
- 单项测试使用 dotted test ID，例如 `uv run python -m unittest tests.test_config.LoadProjectConfigTest.test_uses_defaults_when_file_is_missing`。
- 测试通过 fake ADB/OCR 运行，不需要手机。`uv run babanongchang ...` 会唤醒设备并真实操作支付宝或淘宝；仅在用户明确要求且设备已连接、授权、解锁时运行。无设备冒烟检查使用 `uv run babanongchang --help`。

# 代码边界

- `src/babanongchang/cli.py` 是命令入口，也包含 ADB 适配和支付宝的施肥、逛农货、任务流程；淘宝流程在 `taobao.py`，通用 OCR/页面等待在 `handle.py`，返回导航在 `navigation.py`。
- 任务文案与规则归 `task_pool.py`；新增操作类型时必须同时扩展 `TaskOperation`、在 `task_executors.py` 实现执行器并注册到 `TASK_EXECUTORS`。
- UI 跳转保持“一次点击后识别目标页面”：复用 `tap_and_wait`、稳定帧等待和 `back_until`，不要用重复点击或固定坐标替代页面状态判断。

# 容易混淆的运行时约定

- `babanongchang.toml` 在模块导入时从 `Path.cwd()` 读取；从仓库根目录启动才能应用仓库内 OCR 配置。
- `babanongchang.toml`、`TextHandle` 和 `back_until` 的 timeout/interval 单位是毫秒；业务自动化方法的 `timeout`、`duration_seconds` 通常是秒，传给底层等待前需乘以 1000。
