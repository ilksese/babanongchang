import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from babanongchang.desktop_build import (
    FOOTER_MAGIC,
    attach_payload,
    main,
    packaged_executable,
    read_footer,
    remove_stale_outputs,
    repo_root,
    windows_command,
)
from babanongchang.launch import frozen_home


class DesktopBuildTest(unittest.TestCase):
    def test_windows_command_targets_the_spec(self) -> None:
        root = repo_root()
        command = windows_command(root, distpath=root / "stage" / "dist", workpath=root / "stage" / "work")
        self.assertIn("pyinstaller", command)
        self.assertIn(str(root / "packaging" / "babanongchang.spec"), command)
        self.assertIn(str(root / "stage" / "dist"), command)
        self.assertNotIn(str(root / "dist"), command)

    def test_requires_windows_flag(self) -> None:
        with self.assertRaises(SystemExit):
            main([])

    def test_windows_packages_from_repo_root(self) -> None:
        output = packaged_executable(repo_root())
        with (
            patch("babanongchang.desktop_build.package_windows", return_value=output) as package,
            patch("babanongchang.desktop_build.remove_stale_outputs") as cleanup,
        ):
            main(["--windows"])
        package.assert_called_once_with(repo_root())
        cleanup.assert_called_once_with(repo_root())

    def test_payload_footer_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stub = root / "stub.exe"
            payload = root / "payload.zip"
            output = root / "app.exe"
            stub.write_bytes(b"stub")
            payload.write_bytes(b"zip-bytes")
            attach_payload(stub, payload, output)
            offset, length, digest = read_footer(output)
            self.assertEqual(output.read_bytes()[offset:offset + length], b"zip-bytes")
            self.assertEqual(digest.hex(), __import__("hashlib").sha256(b"zip-bytes").hexdigest())
            self.assertTrue(output.read_bytes().endswith(FOOTER_MAGIC))

    def test_removes_intermediate_directory_but_keeps_single_exe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            incomplete = root / "build" / "babanongchang" / "babanongchang.exe"
            incomplete.parent.mkdir(parents=True)
            incomplete.write_bytes(b"incomplete")
            (root / "build" / "babanongchang.ico").write_bytes(b"icon")
            stale = root / "dist" / "babanongchang"
            stale.mkdir(parents=True)
            (stale / "babanongchang.exe").write_bytes(b"old")
            single = packaged_executable(root)
            single.write_bytes(b"new")
            remove_stale_outputs(root)
            self.assertFalse((root / "build").exists())
            self.assertFalse(stale.exists())
            self.assertEqual(single.read_bytes(), b"new")

    def test_frozen_home_follows_distributed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            with (
                patch("babanongchang.launch.sys") as frozen_sys,
                patch.dict(os.environ, {"BABANONGCHANG_HOME": str(home)}),
            ):
                frozen_sys.executable = str(home / "cache" / "babanongchang.exe")
                self.assertEqual(frozen_home(), home.resolve())

    def test_launcher_contract_matches_packager(self) -> None:
        source = (repo_root() / "packaging" / "launcher.cs").read_text(encoding="utf-8")
        self.assertIn("FooterSize = 44", source)
        self.assertIn("BABANONGCHANG_HOME", source)
        self.assertIn("(byte)'B'", source)


class LauncherSmokeTest(unittest.TestCase):
    def test_single_file_extracts_once_and_starts_beside_distributed_exe(self) -> None:
        from babanongchang.desktop_build import compile_launcher, csc_path

        if not csc_path().is_file():
            self.skipTest("csc missing")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            inner_source = root / "inner.cs"
            inner_source.write_text(
                "using System;\nusing System.IO;\n"
                "internal static class Program {\n"
                "  private static int Main() {\n"
                "    File.WriteAllText(\"marker.txt\", Environment.GetEnvironmentVariable(\"BABANONGCHANG_HOME\") ?? \"\");\n"
                "    return 4;\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )
            inner = root / "inner" / "babanongchang.exe"
            compile_launcher(inner_source, inner)
            payload = root / "payload.zip"
            with zipfile.ZipFile(payload, "w") as archive:
                archive.write(inner, "babanongchang.exe")
            stub = root / "stub.exe"
            compile_launcher(repo_root() / "packaging" / "launcher.cs", stub)
            distributed = root / "share" / "babanongchang.exe"
            attach_payload(stub, payload, distributed)
            runtime = root / "runtime"
            old = runtime / "old-version"
            old.mkdir(parents=True)
            (old / "ready").write_text("old", encoding="ascii")
            (runtime / "old-version.partial").mkdir()
            env = os.environ.copy()
            env["BABANONGCHANG_RUNTIME"] = str(runtime)
            completed = __import__("subprocess").run(
                [str(distributed)], cwd=distributed.parent, env=env, check=False, timeout=30,
            )
            self.assertEqual(completed.returncode, 4)
            self.assertEqual((distributed.parent / "marker.txt").read_text(encoding="utf-8"), str(distributed.parent))
            self.assertFalse(old.exists())
            self.assertFalse((runtime / "old-version.partial").exists())
            self.assertEqual(len(list(runtime.iterdir())), 1)
            completed = __import__("subprocess").run(
                [str(distributed)], cwd=distributed.parent, env=env, check=False, timeout=30,
            )
            self.assertEqual(completed.returncode, 4)
            self.assertEqual(len(list(runtime.iterdir())), 1)
