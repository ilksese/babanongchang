"""Tk desktop application for the CLI automation workflows."""

from __future__ import annotations

from pathlib import Path
import queue
import re
import subprocess
import threading

from babanongchang.adb_devices import AdbDevice, list_adb_devices
from babanongchang.app_core import (
    FEATURES,
    FEATURE_BY_KEY,
    FieldSpec,
    TaskProcess,
    build_arguments,
    defaults_for,
    effective_parameters,
    requires_device,
    save_ocr_config,
    validate_settings,
)
from babanongchang.config import CONFIG_FILE_NAME, load_project_config


def run_app() -> None:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise SystemExit(
            "无法启动桌面界面：当前 Python 未安装 Tk。请安装系统的 Tk 支持后重试。"
        ) from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"无法启动桌面界面：{exc}") from exc
    FarmApp(root, tk, ttk)
    root.mainloop()


class FarmApp:
    BG = "#F2F5F0"
    PANEL = "#FFFFFF"
    INK = "#17251F"
    MUTED = "#627068"
    GREEN = "#176B4D"
    GREEN_DARK = "#0F4D38"
    RICE = "#D7A72F"
    DANGER = "#A43D32"
    LINE = "#D5DDD7"

    def __init__(self, root, tk, ttk) -> None:
        self.root, self.tk, self.ttk = root, tk, ttk
        self.cwd = Path.cwd()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.runner = TaskProcess(self.events)
        self.devices: dict[str, AdbDevice] = {}
        self.feature_key = "all"
        self.session_values = {item.key: defaults_for(item) for item in FEATURES}
        self.vars: dict[str, object] = {}
        self.rows: dict[str, object] = {}
        self.stop_timer = None
        self.close_after_stop = False
        self.forced = False
        self.show_advanced = False
        self.parameter_controls: list[tuple[object, str]] = []
        self.preserve_status_on_refresh = False

        self._style()
        self._build()
        self._select_feature("all")
        self._set_status("检测设备", "正在读取 ADB 设备…")
        self.refresh_devices()
        self.root.after(80, self._drain_events)

    def _style(self) -> None:
        self.root.title("芭芭农场作业台")
        self.root.geometry("1120x760")
        self.root.minsize(900, 620)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground=self.INK)
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.INK)
        style.configure("Panel.TLabel", background=self.PANEL, foreground=self.INK)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"), background=self.GREEN_DARK, foreground="white")
        style.configure("Subtitle.TLabel", background=self.GREEN_DARK, foreground="#D8E9E1")
        style.configure("Feature.TButton", anchor="w", padding=(14, 11), background=self.PANEL, borderwidth=0)
        style.map("Feature.TButton", background=[("active", "#E5EEE8")])
        style.configure("Selected.TButton", anchor="w", padding=(14, 11), background="#DCEBE3", foreground=self.GREEN_DARK, borderwidth=0)
        style.configure("Start.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(24, 10), background=self.RICE, foreground="#2C2514")
        style.map("Start.TButton", background=[("active", "#E7BA43"), ("disabled", "#D8D8D0")])
        style.configure("Stop.TButton", padding=(18, 10), background="#EADBD8", foreground=self.DANGER)
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)

    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        header = tk.Frame(self.root, bg=self.GREEN_DARK, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)
        title = ttk.Frame(header, style="Panel.TFrame")
        title.configure(style="TFrame")
        title.pack(side="left", fill="y", padx=28, pady=14)
        ttk.Label(title, text="芭芭农场作业台", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title, text="选择设备，安排一次农场作业，再从日志确认结果。", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        device_bar = tk.Frame(header, bg=self.GREEN_DARK)
        device_bar.pack(side="right", padx=24, pady=18)
        tk.Label(device_bar, text="目标设备", bg=self.GREEN_DARK, fg="#D8E9E1").grid(row=0, column=0, sticky="w")
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(device_bar, textvariable=self.device_var, state="readonly", width=31)
        self.device_box.grid(row=1, column=0, padx=(0, 8), pady=(3, 0))
        self.device_box.bind("<<ComboboxSelected>>", lambda event: self._update_start_state())
        self.refresh_button = ttk.Button(device_bar, text="刷新设备", command=self.refresh_devices)
        self.refresh_button.grid(row=1, column=1, pady=(3, 0))

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=20, pady=18)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        nav = ttk.Frame(body, style="Panel.TFrame", padding=(10, 14))
        nav.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        ttk.Label(nav, text="本次作业", style="Panel.TLabel", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=(0, 10))
        self.feature_buttons = {}
        for feature in FEATURES:
            button = ttk.Button(nav, text=feature.title, style="Feature.TButton", width=19, command=lambda key=feature.key: self._select_feature(key))
            button.pack(fill="x", pady=1)
            self.feature_buttons[feature.key] = button
        ttk.Separator(nav).pack(fill="x", padx=10, pady=14)
        self.config_button = ttk.Button(nav, text="OCR 配置", command=self._open_config)
        self.config_button.pack(fill="x", padx=8)

        work = ttk.Frame(body)
        work.grid(row=0, column=1, sticky="nsew")
        work.columnconfigure(0, weight=1)
        work.rowconfigure(1, weight=3)
        work.rowconfigure(3, weight=2)

        top = ttk.Frame(work, style="Panel.TFrame", padding=18)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.feature_title = ttk.Label(top, style="Panel.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        self.feature_title.grid(row=0, column=0, sticky="w")
        self.feature_description = ttk.Label(top, style="Panel.TLabel", foreground=self.MUTED)
        self.feature_description.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.advanced_button = ttk.Button(top, text="显示高级参数", command=self._toggle_advanced)
        self.advanced_button.grid(row=0, column=1, rowspan=2, padx=(8, 6))
        self.reset_button = ttk.Button(top, text="恢复默认值", command=self._reset_current)
        self.reset_button.grid(row=0, column=2, rowspan=2)

        parameter_shell = ttk.Frame(work, style="Panel.TFrame")
        parameter_shell.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        parameter_shell.rowconfigure(0, weight=1)
        parameter_shell.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(parameter_shell, bg=self.PANEL, highlightthickness=0)
        scroll = ttk.Scrollbar(parameter_shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.form = ttk.Frame(self.canvas, style="Panel.TFrame", padding=18)
        self.form_window = self.canvas.create_window((0, 0), window=self.form, anchor="nw")
        self.form.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.form_window, width=event.width))

        controls = ttk.Frame(work, padding=(0, 12, 0, 10))
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(controls, text="开始作业", style="Start.TButton", command=self._confirm_start)
        self.start_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(controls, text="停止", style="Stop.TButton", state="disabled", command=self._request_stop)
        self.stop_button.grid(row=0, column=1, sticky="w", padx=10)
        self.status_title = ttk.Label(controls, font=("Microsoft YaHei UI", 10, "bold"), foreground=self.GREEN)
        self.status_title.grid(row=0, column=2, sticky="e")
        self.status_detail = ttk.Label(controls, foreground=self.MUTED)
        self.status_detail.grid(row=1, column=0, columnspan=3, sticky="e")

        log_panel = ttk.Frame(work, style="Panel.TFrame", padding=(14, 10))
        log_panel.grid(row=3, column=0, sticky="nsew")
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        ttk.Label(log_panel, text="本次运行日志", style="Panel.TLabel", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 7))
        ttk.Button(log_panel, text="复制日志", command=self._copy_log).grid(row=0, column=1, sticky="e")
        self.log = tk.Text(log_panel, height=9, wrap="word", bg="#17251F", fg="#E7EFEA", insertbackground="white", relief="flat", padx=12, pady=10, font=("Consolas", 9), state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_panel, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _select_feature(self, key: str) -> None:
        if self.runner.running:
            return
        self._collect_values()
        self.feature_key = key
        self.show_advanced = False
        self.advanced_button.configure(text="显示高级参数")
        feature = FEATURE_BY_KEY[key]
        for name, button in self.feature_buttons.items():
            button.configure(style="Selected.TButton" if name == key else "Feature.TButton")
        self.feature_title.configure(text=feature.title)
        self.feature_description.configure(text=feature.description)
        for child in self.form.winfo_children():
            child.destroy()
        self.vars, self.rows, self.parameter_controls = {}, {}, []
        values = self.session_values[key]
        for row_index, field in enumerate(feature.fields):
            row = self.ttk.Frame(self.form, style="Panel.TFrame")
            row.grid(row=row_index, column=0, sticky="ew", pady=5)
            row.columnconfigure(1, weight=1)
            self.ttk.Label(row, text=field.label, style="Panel.TLabel", width=25).grid(row=0, column=0, sticky="w")
            var = self.tk.BooleanVar(value=bool(values[field.key])) if field.kind == "bool" else self.tk.StringVar(value=str(values[field.key]))
            self.vars[field.key] = var
            self.rows[field.key] = row
            if field.kind == "bool":
                control = self.ttk.Checkbutton(row, variable=var, command=self._update_dependencies)
            elif field.kind == "choice":
                control = self.ttk.Combobox(row, textvariable=var, values=field.options, state="readonly")
            else:
                control = self.ttk.Entry(row, textvariable=var)
            control.grid(row=0, column=1, sticky="ew")
            self.parameter_controls.append((control, "readonly" if field.kind == "choice" else "normal"))
            if field.kind in ("file", "directory"):
                chooser = self.ttk.Button(row, text="选择…", command=lambda item=field: self._choose_path(item))
                chooser.grid(row=0, column=2, padx=(7, 0))
                self.parameter_controls.append((chooser, "normal"))
            var.trace_add("write", lambda *_args: self._update_dependencies())
        self.form.columnconfigure(0, weight=1)
        self._update_dependencies()
        self._update_start_state()

    def _collect_values(self) -> None:
        if not self.vars:
            return
        self.session_values[self.feature_key] = {key: var.get() for key, var in self.vars.items()}

    def _reset_current(self) -> None:
        defaults = defaults_for(FEATURE_BY_KEY[self.feature_key])
        self.session_values[self.feature_key] = defaults
        for key, value in defaults.items():
            self.vars[key].set(value)

    def _toggle_advanced(self) -> None:
        self.show_advanced = not self.show_advanced
        self.advanced_button.configure(text="隐藏高级参数" if self.show_advanced else "显示高级参数")
        self._update_dependencies()

    def _update_dependencies(self, *_args) -> None:
        screenshot_var = self.vars.get("screenshot")
        target_var = self.vars.get("target")
        screenshot = str(screenshot_var.get()).strip() if screenshot_var is not None else ""
        target = str(target_var.get()).strip() if target_var is not None else ""
        offline_allowed = {"screenshot", "ocr", "output", "board_top", "board_bottom"}
        fields = {field.key: field for field in FEATURE_BY_KEY[self.feature_key].fields}
        for key, row in self.rows.items():
            visible = self.show_advanced or not fields[key].advanced
            if self.feature_key == "nlgj" and screenshot and key not in offline_allowed:
                visible = False
            if self.feature_key == "nlgj" and target and key in ("levels", "max_minutes"):
                visible = False
            if visible:
                row.grid()
            else:
                row.grid_remove()
        self._update_start_state()

    def _choose_path(self, field: FieldSpec) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择离线截图") if field.kind == "file" else filedialog.askdirectory(title="选择输出目录")
        if path:
            self.vars[field.key].set(str(Path(path).resolve()))
            self._update_dependencies()

    def refresh_devices(self) -> None:
        if self.runner.running:
            return
        self.refresh_button.configure(state="disabled")
        if not self.preserve_status_on_refresh:
            self._set_status("检测设备", "正在读取 ADB 设备…")
        threading.Thread(target=self._discover_devices, name="app-adb-discovery", daemon=True).start()

    def _discover_devices(self) -> None:
        try:
            devices = list_adb_devices()
            self.events.put(("devices", devices))
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            self.events.put(("device_error", exc))

    def _show_devices(self, devices: tuple[AdbDevice, ...]) -> None:
        self.devices = {device.serial: device for device in devices}
        labels = []
        authorized = []
        for device in devices:
            model = f" · {device.model}" if device.model else ""
            state = "已授权" if device.state == "device" else device.state
            label = f"{device.serial}{model} · {state}"
            labels.append(label)
            if device.state == "device":
                authorized.append(label)
        self.device_box.configure(values=labels)
        if len(authorized) == 1:
            self.device_var.set(authorized[0])
        elif self.device_var.get() not in labels:
            self.device_var.set("")
        self.refresh_button.configure(state="normal")
        detail = f"发现 {len(authorized)} 台可用设备" if authorized else "未发现已授权设备；可检查连接后刷新"
        if self.preserve_status_on_refresh:
            self.preserve_status_on_refresh = False
        else:
            self._set_status("就绪", detail)
        self._update_start_state()

    def _selected_serial(self) -> str | None:
        label = self.device_var.get()
        serial = label.split(" · ", 1)[0] if label else None
        device = self.devices.get(serial or "")
        return serial if device and device.state == "device" else None

    def _update_start_state(self) -> None:
        self._collect_values()
        values = self.session_values[self.feature_key]
        enabled = not self.runner.running and (not requires_device(self.feature_key, values) or self._selected_serial() is not None)
        self.start_button.configure(state="normal" if enabled else "disabled")

    def _confirm_start(self) -> None:
        from tkinter import messagebox
        self._collect_values()
        values = self.session_values[self.feature_key]
        errors = validate_settings(self.feature_key, values)
        if errors:
            messagebox.showerror("参数需要修改", "\n".join(dict.fromkeys(errors.values())))
            return
        serial = self._selected_serial()
        try:
            arguments = build_arguments(self.feature_key, values, serial)
        except ValueError as exc:
            messagebox.showerror("无法开始", str(exc))
            return
        feature = FEATURE_BY_KEY[self.feature_key]
        offline = not requires_device(self.feature_key, values)
        target = "仅分析本地截图，不操作手机" if offline else f"目标设备：{serial}\n将唤醒设备并真实操作支付宝、淘宝或游戏。"
        parameter_text = " ".join(arguments)
        effective = effective_parameters(self.feature_key, values)
        effective_text = "\n".join(f"{label}：{value}" for label, value in effective) or "（无额外参数）"
        if not messagebox.askyesno("确认开始作业", f"功能：{feature.title}\n{target}\n\n本次有效参数：\n{effective_text}\n\n确认开始？"):
            return
        output = str(values.get("output", ""))
        if self.feature_key == "nlgj" and output and Path(output).exists() and any(Path(output).iterdir()):
            if not messagebox.askyesno("输出目录已有文件", "现有文件可能被覆盖或与本次结果混合。继续运行？"):
                return
        self._clear_log()
        self._append_log(f"$ {self.root.tk.call('info', 'nameofexecutable')} -m babanongchang.cli {parameter_text}\n")
        try:
            self.runner.start(arguments, self.cwd)
        except OSError as exc:
            messagebox.showerror("启动失败", str(exc))
            return
        self.forced = False
        self._lock_running(True)
        self._set_status("运行中", f"正在执行：{feature.title}")

    def _lock_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.device_box.configure(state="disabled" if running else "readonly")
        self.refresh_button.configure(state="disabled" if running else "normal")
        for button in self.feature_buttons.values():
            button.configure(state="disabled" if running else "normal")
        self.advanced_button.configure(state="disabled" if running else "normal")
        self.reset_button.configure(state="disabled" if running else "normal")
        self.config_button.configure(state="disabled" if running else "normal")
        for control, normal_state in self.parameter_controls:
            control.configure(state="disabled" if running else normal_state)

    def _request_stop(self) -> None:
        if not self.runner.running:
            return
        self.runner.request_stop()
        self.stop_button.configure(state="disabled")
        self._set_status("正在停止", "已请求安全停止；正在等待当前设备操作结束…")
        self.stop_timer = self.root.after(10_000, self._stop_timed_out)

    def _stop_timed_out(self) -> None:
        from tkinter import messagebox
        if not self.runner.running:
            return
        force = messagebox.askyesno(
            "任务尚未退出",
            "任务可能仍在等待 ADB 或 OCR。\n\n强制终止可能导致设备动作结果未确认、屏幕常亮设置未恢复，附属 ADB 操作也可能短暂残留。\n\n是否强制终止？",
        )
        if force:
            self.forced = True
            self.runner.force_stop()
            self._set_status("被强制终止", "最后一次设备操作结果可能未确认")
        else:
            self.stop_timer = self.root.after(10_000, self._stop_timed_out)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload), echo=True)
                elif kind == "exit":
                    self._handle_exit(payload)
                elif kind == "devices":
                    self._show_devices(payload)
                elif kind == "device_error":
                    self.refresh_button.configure(state="normal")
                    self.device_box.configure(values=())
                    self.device_var.set("")
                    if self.preserve_status_on_refresh:
                        self.preserve_status_on_refresh = False
                    else:
                        self._set_status("就绪", "未找到 ADB 或设备查询失败；修复后可重新刷新")
                    self._update_start_state()
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _handle_exit(self, payload) -> None:
        code, stopped = payload
        if self.stop_timer is not None:
            self.root.after_cancel(self.stop_timer)
            self.stop_timer = None
        if self.forced:
            self._set_status("被强制终止", "最后一次设备操作结果可能未确认")
        elif stopped:
            self._set_status("已由用户停止", "任务已完成清理")
        elif code == 0:
            self._set_status("已完成", "流程正常结束；业务结果请以日志为准")
        else:
            self._set_status("运行失败", f"子进程退出码：{code}")
        self._lock_running(False)
        self._update_start_state()
        if self.close_after_stop:
            self.root.destroy()
        else:
            self.preserve_status_on_refresh = True
            self.refresh_devices()

    def _set_status(self, title: str, detail: str) -> None:
        self.status_title.configure(text=title)
        self.status_detail.configure(text=detail)

    def _append_log(self, text: str, *, echo: bool = False) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")
        if echo:
            print(text, end="", flush=True)

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _copy_log(self) -> None:
        text = self.log.get("1.0", "end-1c")
        for serial in self.devices:
            text = text.replace(serial, self._mask_serial(serial))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    @staticmethod
    def _mask_serial(serial: str) -> str:
        if len(serial) <= 6:
            return "***"
        return f"{serial[:3]}***{serial[-3:]}"

    def _open_config(self) -> None:
        from tkinter import messagebox
        path = self.cwd / CONFIG_FILE_NAME
        try:
            config = load_project_config(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法读取配置", str(exc))
            return
        dialog = self.tk.Toplevel(self.root)
        dialog.title("OCR 配置")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = self.ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        interval = self.tk.StringVar(value=str(config.screenshot_interval_ms))
        timeout = self.tk.StringVar(value=str(config.recognition_timeout_ms))
        self.ttk.Label(frame, text="截图间隔（毫秒）").grid(row=0, column=0, sticky="w", pady=6)
        self.ttk.Entry(frame, textvariable=interval, width=24).grid(row=0, column=1, pady=6)
        self.ttk.Label(frame, text="识别超时（毫秒）").grid(row=1, column=0, sticky="w", pady=6)
        self.ttk.Entry(frame, textvariable=timeout, width=24).grid(row=1, column=1, pady=6)
        self.ttk.Label(frame, text=str(path.resolve()), foreground=self.MUTED, wraplength=430).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.ttk.Label(frame, text="保存后需重启 GUI 才会生效。", foreground=self.MUTED).grid(row=3, column=0, columnspan=2, sticky="w")

        def save() -> None:
            try:
                save_ocr_config(path, int(interval.get()), int(timeout.get()))
            except (ValueError, OSError) as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)
                return
            messagebox.showinfo("配置已保存", f"已保存到：\n{path.resolve()}\n\n重启 GUI 后生效。", parent=dialog)
            dialog.destroy()

        self.ttk.Button(frame, text="取消", command=dialog.destroy).grid(row=4, column=0, sticky="e", pady=(18, 0), padx=(0, 8))
        self.ttk.Button(frame, text="保存配置", style="Start.TButton", command=save).grid(row=4, column=1, sticky="e", pady=(18, 0))

    def _close(self) -> None:
        from tkinter import messagebox
        if not self.runner.running:
            self.root.destroy()
            return
        if messagebox.askyesno("停止任务并关闭？", "窗口关闭前会先请求当前任务安全停止。是否继续？"):
            self.close_after_stop = True
            self._request_stop()
