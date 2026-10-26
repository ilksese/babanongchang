import tempfile
import unittest
from pathlib import Path

from babanongchang.config import ProjectConfig, load_project_config


class LoadProjectConfigTest(unittest.TestCase):
    def test_uses_defaults_when_file_is_missing(self) -> None:
        config = load_project_config(Path("missing-babanongchang.toml"))
        self.assertEqual(config, ProjectConfig())

    def test_loads_ocr_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "babanongchang.toml"
            path.write_text(
                "[ocr]\n"
                "screenshot_interval_ms = 350\n"
                "recognition_timeout_ms = 12000\n",
                encoding="utf-8",
            )
            config = load_project_config(path)

        self.assertEqual(config.screenshot_interval_ms, 350)
        self.assertEqual(config.screenshot_interval_seconds, 0.35)
        self.assertEqual(config.recognition_timeout_ms, 12000)

    def test_rejects_non_positive_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "babanongchang.toml"
            path.write_text(
                "[ocr]\nscreenshot_interval_ms = 0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "screenshot_interval_ms"):
                load_project_config(path)
