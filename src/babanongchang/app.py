"""Tk desktop application for the CLI automation workflows."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
import queue
import re
import subprocess
import threading

from babanongchang.adb_devices import list_adb_devices
from babanongchang.app_core import (
    FEATURES,
    FEATURE_BY_KEY,
    DeviceBoard,
    FieldSpec,
    TaskProcess,
    build_arguments,
    defaults_for,
    effective_parameters,
    nlgj_progress_from_values,
    progress_ratio,
    progress_text,
    load_log_enabled,
    save_log_enabled,
    save_ocr_config,
    validate_settings,
)
from babanongchang.logs import LOG_FILE_NAME
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
        self.board = DeviceBoard()
        self.runners: dict[str, TaskProcess] = {}
        self.stop_timers: dict[str, str] = {}
        self.forced: set[str] = set()
        self.feature_key = "all"
        self.session_values = {item.key: defaults_for(item) for item in FEATURES}
        self.vars: dict[str, object] = {}
        self.rows: dict[str, object] = {}
        self.close_after_stop = False
        self.show_advanced = False
        self.parameter_controls: list[tuple[object, str]] = []
        self.log_enabled = load_log_enabled(self.cwd / CONFIG_FILE_NAME)
        self.run_logging: dict[str, bool] = {}
        self.failure_notes: dict[str, str] = {}
        self._discovering = False
        self._rendering_devices = False
        self._device_poll_ms = 3000
        self._device_poll_timer: str | None = None

        self._style()
        self._build()
        self._select_feature("all")
        self._set_status("检测设备", "正在读取 ADB 设备…")
        self.refresh_devices()
        self._schedule_device_poll()
        self.root.after(80, self._drain_events)

    def _style(self) -> None:
        self.root.title("芭芭农场作业台")
        self._set_window_icon()
        self.root.geometry("1280x760")
        self.root.minsize(1080, 620)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground=self.INK)
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.INK)
        style.configure("Panel.TLabel", background=self.PANEL, foreground=self.INK)
        style.configure("Panel.TCheckbutton", background=self.PANEL, foreground=self.INK)
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
        style.configure(
            "Game.Horizontal.TProgressbar",
            troughcolor="#E4EBE6",
            background=self.GREEN,
            bordercolor=self.LINE,
            lightcolor=self.GREEN,
            darkcolor=self.GREEN,
            thickness=14,
        )
        style.configure(
            "Stopped.Horizontal.TProgressbar",
            troughcolor="#E4EBE6",
            background=self.RICE,
            bordercolor=self.LINE,
            lightcolor=self.RICE,
            darkcolor=self.RICE,
            thickness=14,
        )

    def _set_window_icon(self) -> None:
        try:
            icon = self.tk.PhotoImage(file=str(files("babanongchang").joinpath("icon.png")))
        except (self.tk.TclError, FileNotFoundError, OSError):
            return
        self._window_icon = icon
        self.root.iconphoto(True, icon)

    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        header = tk.Frame(self.root, bg=self.GREEN_DARK, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)
        title = ttk.Frame(header, style="Panel.TFrame")
        title.configure(style="TFrame")
        title.pack(side="left", fill="y", padx=28, pady=14)
        ttk.Label(title, text="芭芭农场作业台", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title, text="选择一台设备开始作业；其他设备可以同时运行。", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        status_bar = tk.Frame(header, bg=self.GREEN_DARK)
        status_bar.pack(side="right", padx=24, pady=14)
        self.status_title = tk.Label(status_bar, text="检测设备", bg=self.GREEN_DARK, fg="white", font=("Microsoft YaHei UI", 12, "bold"))
        self.status_title.pack(anchor="e")
        self.status_detail = tk.Label(status_bar, text="正在读取 ADB 设备…", bg=self.GREEN_DARK, fg="#D8E9E1")
        self.status_detail.pack(anchor="e", pady=(2, 0))

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=20, pady=18)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)

        device_panel = ttk.Frame(body, style="Panel.TFrame", padding=(10, 14))
        device_panel.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        device_panel.rowconfigure(1, weight=1)
        device_header = ttk.Frame(device_panel, style="Panel.TFrame")
        device_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(device_header, text="设备", style="Panel.TLabel", font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        self.refresh_button = ttk.Button(device_header, text="刷新", command=self.refresh_devices)
        self.refresh_button.pack(side="right")
        self.device_list = tk.Listbox(
            device_panel, width=34, activestyle="none", exportselection=False,
            bg=self.PANEL, fg=self.INK, relief="flat", highlightthickness=1, highlightbackground=self.LINE,
            font=("Microsoft YaHei UI", 9), selectbackground=self.GREEN, selectforeground="white",
        )
        self.device_list.grid(row=1, column=0, sticky="ns")
        self.device_list.bind("<<ListboxSelect>>", self._on_device_selected)

        nav = ttk.Frame(body, style="Panel.TFrame", padding=(10, 14))
        nav.grid(row=0, column=1, sticky="ns", padx=(0, 14))
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
        work.grid(row=0, column=2, sticky="nsew")
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
        self.stop_button = ttk.Button(controls, text="停止", style="Stop.TButton", state="disabled", command=self._request_stop_selected)
        self.stop_button.grid(row=0, column=1, sticky="w", padx=10)

        log_panel = ttk.Frame(work, style="Panel.TFrame", padding=(14, 10))
        log_panel.grid(row=3, column=0, sticky="nsew")
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(3, weight=1)
        self.progress_frame = ttk.Frame(log_panel, style="Panel.TFrame")
        self.progress_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.progress_frame.columnconfigure(0, weight=1)
        self.progress_label = ttk.Label(self.progress_frame, style="Panel.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        self.progress_label.grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(self.progress_frame, style="Game.Horizontal.TProgressbar", mode="determinate")
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.progress_frame.grid_remove()
        log_header = ttk.Frame(log_panel, style="Panel.TFrame")
        log_header.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        log_header.columnconfigure(0, weight=1)
        self.log_title = ttk.Label(log_header, text="本次运行日志", style="Panel.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        self.log_title.grid(row=0, column=0, sticky="w")
        self.log_switch = tk.BooleanVar(value=self.log_enabled)
        ttk.Checkbutton(
            log_header, text="记录日志", style="Panel.TCheckbutton",
            variable=self.log_switch, command=self._toggle_log,
        ).grid(row=0, column=1, sticky="e", padx=(12, 8))
        ttk.Button(log_header, text="复制日志", command=self._copy_log).grid(row=0, column=2, sticky="e")
        ttk.Label(
            log_panel,
            text=f"默认关闭。打开后，下一次运行才在这里显示，并追加写入 {LOG_FILE_NAME}。",
            style="Panel.TLabel",
            foreground=self.MUTED,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 7))
        self.log = tk.Text(log_panel, height=9, wrap="word", bg="#17251F", fg="#E7EFEA", insertbackground="white", relief="flat", padx=12, pady=10, font=("Consolas", 9), state="disabled")
        self.log.grid(row=3, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_panel, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=3, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _select_feature(self, key: str) -> None:
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
            if field.kind == "directory":
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
        target_var = self.vars.get("target")
        target = str(target_var.get()).strip() if target_var is not None else ""
        fields = {field.key: field for field in FEATURE_BY_KEY[self.feature_key].fields}
        for key, row in self.rows.items():
            visible = self.show_advanced or not fields[key].advanced
            if self.feature_key == "nlgj" and target and key in ("levels", "max_minutes"):
                visible = False
            if visible:
                row.grid()
            else:
                row.grid_remove()
        self._update_start_state()

    def _choose_path(self, field: FieldSpec) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.vars[field.key].set(str(Path(path).resolve()))
            self._update_dependencies()

    def refresh_devices(self, *, quiet: bool = False) -> None:
        if self._discovering:
            return
        self._discovering = True
        self.refresh_button.configure(state="disabled")
        if not quiet and self.board.selected is None and not self.board.runs:
            self._set_status("检测设备", "正在读取 ADB 设备…")
        threading.Thread(target=self._discover_devices, name="app-adb-discovery", daemon=True).start()

    def _schedule_device_poll(self) -> None:
        self._device_poll_timer = self.root.after(self._device_poll_ms, self._poll_devices)

    def _poll_devices(self) -> None:
        self._device_poll_timer = None
        if not self.close_after_stop:
            self.refresh_devices(quiet=True)
        self._schedule_device_poll()

    def _discover_devices(self) -> None:
        try:
            devices = list_adb_devices()
            self.events.put(("devices", devices))
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            self.events.put(("device_error", exc))

    def _show_devices(self, devices) -> None:
        previous = self.board.selected
        self._discovering = False
        self.refresh_button.configure(state="normal")
        self.board.apply_devices(devices)
        self._render_devices()
        if self.board.selected != previous:
            self._show_selected_log()
        self._set_status(*self.board.header())
        self._update_start_state()

    def _render_devices(self) -> None:
        self._rendering_devices = True
        self.device_list.delete(0, "end")
        for serial in self.board.order:
            self.device_list.insert("end", self.board.row_text(serial))
        if self.board.selected in self.board.order:
            index = self.board.order.index(self.board.selected)
            self.device_list.selection_set(index)
            self.device_list.see(index)
        self.root.after_idle(self._finish_render)

    def _finish_render(self) -> None:
        self._rendering_devices = False

    def _on_device_selected(self, _event=None) -> None:
        if self._rendering_devices:
            return
        selection = self.device_list.curselection()
        if not selection or selection[0] >= len(self.board.order):
            return
        serial = self.board.order[selection[0]]
        if serial == self.board.selected:
            return
        self.board.select(serial)
        self._show_selected_log()
        self._set_status(*self.board.header())
        self._update_start_state()

    def _update_start_state(self) -> None:
        self._collect_values()
        self.start_button.configure(state="normal" if self.board.can_start() else "disabled")
        self.stop_button.configure(state="normal" if self.board.can_stop() else "disabled")

    def _toggle_log(self) -> None:
        enabled = bool(self.log_switch.get())
        try:
            save_log_enabled(self.cwd / CONFIG_FILE_NAME, enabled)
        except Exception as exc:
            from tkinter import messagebox

            self.log_switch.set(self.log_enabled)
            messagebox.showerror("无法保存日志开关", str(exc))
            return
        self.log_enabled = enabled

    def _confirm_start(self) -> None:
        from tkinter import messagebox
        self._collect_values()
        serial = self.board.selected
        if not self.board.can_start(serial):
            messagebox.showerror("无法开始", "请选择一台已授权且空闲的设备。")
            return
        values = self.session_values[self.feature_key]
        errors = validate_settings(self.feature_key, values)
        if errors:
            messagebox.showerror("参数需要修改", "\n".join(dict.fromkeys(errors.values())))
            return
        output = str(values.get("output", "")) if self.feature_key == "nlgj" else None
        conflict = self.board.output_conflict(self.feature_key, output)
        if conflict:
            messagebox.showerror("无法开始", conflict)
            return
        try:
            arguments = build_arguments(self.feature_key, values, serial, log=self.log_enabled)
        except ValueError as exc:
            messagebox.showerror("无法开始", str(exc))
            return
        feature = FEATURE_BY_KEY[self.feature_key]
        target = f"目标设备：{serial}\n将唤醒设备并真实操作支付宝、淘宝或游戏。"
        parameter_text = " ".join(arguments)
        effective = effective_parameters(self.feature_key, values)
        effective_text = "\n".join(f"{label}：{value}" for label, value in effective) or "（无额外参数）"
        log_line = "日志：开启" if self.log_enabled else "日志：关闭"
        if not messagebox.askyesno(
            "确认开始作业",
            f"功能：{feature.title}\n{target}\n\n本次有效参数：\n{effective_text}\n\n{log_line}\n\n确认开始？",
        ):
            return
        if self.feature_key == "nlgj" and output and Path(output).exists() and any(Path(output).iterdir()):
            if not messagebox.askyesno("输出目录已有文件", "现有文件可能被覆盖或与本次结果混合。继续运行？"):
                return
        command = f"$ {self.root.tk.call('info', 'nameofexecutable')} -m babanongchang.cli {parameter_text}\n"
        try:
            self._start_job(serial, arguments, command, output)
        except OSError as exc:
            messagebox.showerror("启动失败", str(exc))

    def _start_job(self, serial: str, arguments: list[str], command: str, output: str | None) -> None:
        source: queue.Queue[tuple[str, object]] = queue.Queue()
        runner = TaskProcess(source)
        runner.start(arguments, self.cwd)
        feature = FEATURE_BY_KEY[self.feature_key]
        logging_on = "--debug" in arguments
        self.run_logging[serial] = logging_on
        progress = nlgj_progress_from_values(self.session_values[self.feature_key]) if self.feature_key == "nlgj" and logging_on else None
        self.runners[serial] = runner
        self.forced.discard(serial)
        self.board.begin(serial, self.feature_key, feature.title, output, progress)
        if logging_on:
            self.board.append_log(serial, command)
        threading.Thread(target=self._bridge, args=(serial, source), name=f"app-cli-{serial}", daemon=True).start()
        self._render_devices()
        self._show_selected_log()
        self._set_status(*self.board.header())
        self._update_start_state()

    def _bridge(self, serial: str, source: queue.Queue) -> None:
        while True:
            kind, payload = source.get()
            if kind == "exit":
                code, stopped = payload
                self.events.put(("exit", (serial, code, stopped)))
                return
            self.events.put((kind, (serial, payload)))

    def _request_stop_selected(self) -> None:
        serial = self.board.selected
        if serial is not None:
            self._request_stop(serial)

    def _request_stop(self, serial: str) -> None:
        runner = self.runners.get(serial)
        if runner is None or not runner.running or not self.board.can_stop(serial):
            return
        runner.request_stop()
        self.board.request_stop(serial)
        timer = self.stop_timers.pop(serial, None)
        if timer is not None:
            self.root.after_cancel(timer)
        self.stop_timers[serial] = self.root.after(10_000, lambda serial=serial: self._stop_timed_out(serial))
        self._render_devices()
        self._set_status(*self.board.header())
        self._update_start_state()

    def _stop_timed_out(self, serial: str) -> None:
        from tkinter import messagebox
        self.stop_timers.pop(serial, None)
        runner = self.runners.get(serial)
        if runner is None or not runner.running:
            return
        force = messagebox.askyesno(
            "任务尚未退出",
            f"设备 {serial} 的任务可能仍在等待 ADB 或 OCR。\n\n强制终止可能导致设备动作结果未确认、屏幕常亮设置未恢复，附属 ADB 操作也可能短暂残留。\n\n是否强制终止？",
        )
        if force:
            self.forced.add(serial)
            runner.force_stop()
            if serial in self.board.runs:
                self.board.runs[serial].status_title = "被强制终止"
                self.board.runs[serial].status_detail = "最后一次设备操作结果可能未确认"
                self._render_devices()
                self._set_status(*self.board.header())
        else:
            self.stop_timers[serial] = self.root.after(10_000, lambda serial=serial: self._stop_timed_out(serial))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    serial, text = payload
                    text = str(text)
                    if not self.run_logging.get(serial, False):
                        stripped = text.strip()
                        if stripped:
                            self.failure_notes[serial] = stripped.splitlines()[-1]
                        continue
                    changed = self.board.append_log(serial, text)
                    if self.board.selected == serial:
                        self._insert_log(text)
                        if changed:
                            self._render_progress()
                    if changed:
                        self._render_devices()
                elif kind == "exit":
                    serial, code, stopped = payload
                    self._handle_exit(serial, code, stopped)
                elif kind == "devices":
                    self._show_devices(payload)
                elif kind == "device_error":
                    self._discovering = False
                    self.refresh_button.configure(state="normal")
                    if self.board.selected is None and not self.board.runs:
                        self._set_status("就绪", "未找到 ADB 或设备查询失败；修复后可重新刷新")
                    self._update_start_state()
        except queue.Empty:
            pass
        if self.close_after_stop and not any(runner.running for runner in self.runners.values()):
            self.root.destroy()
            return
        self.root.after(80, self._drain_events)

    def _handle_exit(self, serial: str, code: int, stopped: bool) -> None:
        timer = self.stop_timers.pop(serial, None)
        if timer is not None:
            self.root.after_cancel(timer)
        forced = serial in self.forced
        self.forced.discard(serial)
        self.runners.pop(serial, None)
        logged = self.run_logging.pop(serial, False)
        note = self.failure_notes.pop(serial, "")
        self.board.finish(serial, code=code, stopped=stopped, forced=forced, logged=logged, note=note)
        self._render_devices()
        if self.board.selected in (serial, None):
            self._show_selected_log()
        self._set_status(*self.board.header())
        self._update_start_state()
        if not self.close_after_stop:
            self.refresh_devices()

    def _set_status(self, title: str, detail: str) -> None:
        self.status_title.configure(text=title)
        self.status_detail.configure(text=detail)

    def _show_selected_log(self) -> None:
        serial = self.board.selected
        title = f"本次运行日志 · {serial}" if serial else "本次运行日志"
        self.log_title.configure(text=title)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        if serial:
            self.log.insert("end", self.board.logs.get(serial, ""))
            self.log.see("end")
        self.log.configure(state="disabled")
        self._render_progress()

    def _render_progress(self) -> None:
        serial = self.board.selected
        progress = self.board.progress.get(serial) if serial else None
        if progress is None:
            self.progress_frame.grid_remove()
            return
        self.progress_frame.grid()
        self.progress_label.configure(text=progress_text(progress))
        ratio = progress_ratio(progress)
        if ratio is None:
            self.progress_bar.grid_remove()
            return
        current, goal = ratio
        self.progress_bar.configure(
            style="Stopped.Horizontal.TProgressbar" if progress.stopped else "Game.Horizontal.TProgressbar",
            maximum=goal,
        )
        self.progress_bar.configure(value=current)
        self.progress_bar.grid()

    def _insert_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _copy_log(self) -> None:
        text = self.log.get("1.0", "end-1c")
        for serial in set(self.board.devices) | set(self.board.runs) | set(self.board.logs) | set(self.board.order):
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
        self.ttk.Label(frame, text="正在运行的任务不会改变；下一次开始的设备会使用这份配置。", foreground=self.MUTED).grid(row=3, column=0, columnspan=2, sticky="w")

        def save() -> None:
            try:
                save_ocr_config(path, int(interval.get()), int(timeout.get()))
            except (ValueError, OSError) as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)
                return
            messagebox.showinfo("配置已保存", f"已保存到：\n{path.resolve()}\n\n下一次开始的设备会使用这份配置。", parent=dialog)
            dialog.destroy()

        self.ttk.Button(frame, text="取消", command=dialog.destroy).grid(row=4, column=0, sticky="e", pady=(18, 0), padx=(0, 8))
        self.ttk.Button(frame, text="保存配置", style="Start.TButton", command=save).grid(row=4, column=1, sticky="e", pady=(18, 0))

    def _close(self) -> None:
        from tkinter import messagebox
        if self.close_after_stop:
            return
        if self._device_poll_timer is not None:
            self.root.after_cancel(self._device_poll_timer)
            self._device_poll_timer = None
        running = [serial for serial, runner in self.runners.items() if runner.running]
        if not running:
            self.root.destroy()
            return
        if messagebox.askyesno("停止任务并关闭？", "窗口关闭前会先请求全部正在运行的任务安全停止。是否继续？"):
            self.close_after_stop = True
            for serial in running:
                self._request_stop(serial)
