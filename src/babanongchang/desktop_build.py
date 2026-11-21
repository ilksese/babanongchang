"""Package the desktop app. Invoked as `uv run build --windows`."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Sequence

FOOTER_MAGIC = b"BBNC"
FOOTER_SIZE = 44
DISTRIBUTED_HOME = "BABANONGCHANG_HOME"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def packaged_executable(root: Path) -> Path:
    return root / "dist" / "babanongchang.exe"


def csc_path() -> Path:
    compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not compiler.is_file():
        raise SystemExit("找不到 C# 编译器，无法生成单文件启动器。")
    return compiler


def windows_command(root: Path, *, distpath: Path, workpath: Path) -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("找不到 uv，无法安装打包工具。")
    return [
        uv,
        "run",
        "--with",
        "pyinstaller",
        "pyinstaller",
        str(root / "packaging" / "babanongchang.spec"),
        "--noconfirm",
        "--distpath",
        str(distpath),
        "--workpath",
        str(workpath),
    ]


def write_icon(root: Path, destination: Path) -> None:
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.open(root / "src" / "babanongchang" / "icon.png").save(
        destination, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
    )


def compile_launcher(source: Path, output: Path, icon: Path | None = None) -> None:
    framework = csc_path().parent
    references = [
        framework / "System.Windows.Forms.dll",
        framework / "System.Drawing.dll",
        framework / "System.IO.Compression.dll",
    ]
    missing = [path for path in references if not path.is_file()]
    if missing:
        raise SystemExit(f"找不到启动器依赖：{missing[0]}")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(csc_path()),
        "/nologo",
        "/target:winexe",
        "/optimize+",
        f"/out:{output}",
        *[f"/reference:{path}" for path in references],
    ]
    if icon is not None:
        command.append(f"/win32icon:{icon}")
    command.append(str(source))
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(result.stdout + result.stderr)


def zip_directory(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def attach_payload(stub: Path, payload: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    digest = hashlib.sha256()
    length = 0
    with stub.open("rb") as source, temporary.open("wb") as target, payload.open("rb") as packed:
        shutil.copyfileobj(source, target)
        while True:
            chunk = packed.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            length += len(chunk)
            target.write(chunk)
        target.write(digest.digest())
        target.write(length.to_bytes(8, "little"))
        target.write(FOOTER_MAGIC)
    temporary.replace(output)


def read_footer(path: Path) -> tuple[int, int, bytes]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size < FOOTER_SIZE:
            raise ValueError("缺少单文件载荷")
        handle.seek(size - FOOTER_SIZE)
        footer = handle.read(FOOTER_SIZE)
    digest, length_bytes, magic = footer[:32], footer[32:40], footer[40:]
    if magic != FOOTER_MAGIC:
        raise ValueError("缺少单文件载荷")
    length = int.from_bytes(length_bytes, "little")
    offset = size - FOOTER_SIZE - length
    if offset < 0:
        raise ValueError("单文件载荷长度无效")
    return offset, length, digest


def remove_stale_outputs(root: Path) -> None:
    stale = root / "dist" / "babanongchang"
    if stale.is_dir():
        shutil.rmtree(stale)
    incomplete = root / "build" / "babanongchang" / "babanongchang.exe"
    incomplete.unlink(missing_ok=True)
    icon = root / "build" / "babanongchang.ico"
    icon.unlink(missing_ok=True)
    cache = root / "build" / "babanongchang"
    if cache.is_dir():
        shutil.rmtree(cache)
    build = root / "build"
    if build.is_dir() and not any(build.iterdir()):
        build.rmdir()


def package_windows(root: Path) -> Path:
    spec = root / "packaging" / "babanongchang.spec"
    if not spec.is_file():
        raise SystemExit(f"找不到打包配置：{spec}")
    with tempfile.TemporaryDirectory(prefix="babanongchang-build-") as raw:
        stage = Path(raw)
        icon = stage / "babanongchang.ico"
        write_icon(root, icon)
        environment = os.environ.copy()
        environment["BABANONGCHANG_ICON"] = str(icon)
        subprocess.run(
            windows_command(root, distpath=stage / "dist", workpath=root / "build"),
            cwd=root,
            check=True,
            env=environment,
        )
        (root / "build" / "babanongchang" / "babanongchang.exe").unlink(missing_ok=True)
        onedir = stage / "dist" / "babanongchang"
        inner = onedir / "babanongchang.exe"
        if not inner.is_file():
            raise SystemExit(f"打包未生成完整程序：{inner}")
        payload = stage / "payload.zip"
        print("正在合成单个 exe…")
        zip_directory(onedir, payload)
        stub = stage / "launcher.exe"
        compile_launcher(root / "packaging" / "launcher.cs", stub, icon)
        output = packaged_executable(root)
        attach_payload(stub, payload, output)
        if output.stat().st_size < 50 * 1024 * 1024:
            output.unlink(missing_ok=True)
            raise SystemExit("生成的 exe 不完整，已保留原来的发布目录。")
        return output


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="打包芭芭农场桌面程序")
    parser.add_argument("--windows", action="store_true", help="打包不占用终端的 Windows exe")
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if not args.windows:
        parser.error("请指定 --windows")
    root = repo_root()
    print("正在打包桌面程序…")
    output = package_windows(root)
    try:
        remove_stale_outputs(root)
    except OSError as exc:
        print(f"已生成单文件，但未能清掉旧的打包目录：{exc}")
    print(f"可分发文件：{output}")
    print("把这一个 exe 交给对方即可运行。配置和日志写在 exe 同目录。")
    print("build 不是发布目录，只是打包中间缓存；成功后会清掉。")
