from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from babanongchang.android import AndroidOcr, AndroidScreenReader


class AndroidOcrTest(unittest.TestCase):
    def test_uses_shared_rapidocr_with_packaged_models_and_unmodified_pixels(self):
        image = np.zeros((60, 100, 3), np.uint8)
        bridge = Mock()
        result = SimpleNamespace(txts=("施肥",), boxes=np.zeros((1, 4, 2)), scores=(.98,))
        engine = Mock(return_value=result)
        engine.text_det = engine.text_cls = engine.text_rec = None
        factory = Mock(return_value=engine)
        with tempfile.TemporaryDirectory() as directory:
            models = SimpleNamespace(__file__=str(Path(directory) / "__init__.py"))
            with patch.dict(sys.modules, babanongchang_ocr_models=models,
                            rapidocr=SimpleNamespace(RapidOCR=factory)):
                ocr = AndroidOcr(bridge)
                self.assertIs(ocr(image), result)
                self.assertIs(ocr(image), result)
                factory.assert_called_once_with(params={
                    f"{name}.model_path": str(Path(directory) / f"{name}.onnx")
                    for name in ("Det", "Cls", "Rec")
                })
        self.assertIs(engine.call_args.args[0], image)
        self.assertEqual(bridge.checkpoint.call_count, 4)
        bridge.recognize.assert_not_called()

    def test_cancellation_does_not_start_model_or_inference(self):
        bridge = Mock()
        bridge.checkpoint.side_effect = RuntimeError("stopped")
        ocr = AndroidOcr(bridge)
        with patch.object(ocr, "_load_engine") as loader:
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                ocr(np.zeros((60, 100, 3), np.uint8))
            loader.assert_not_called()

    def test_close_releases_loaded_native_sessions_and_is_idempotent(self):
        ocr = AndroidOcr(Mock())
        ocr.engine = SimpleNamespace(text_det=Mock(), text_cls=None, text_rec=Mock())
        detector, recognizer = ocr.engine.text_det, ocr.engine.text_rec
        ocr.close()
        ocr.close()
        detector.session.session.close.assert_called_once()
        recognizer.session.session.close.assert_called_once()
        self.assertIsNone(ocr.engine)

    def test_game_reader_accepts_rapidocr_empty_result(self):
        reader = AndroidScreenReader(Mock(return_value=SimpleNamespace(txts=None)))
        self.assertEqual(reader.read(np.zeros((60, 100, 3), np.uint8)), [])


if __name__ == "__main__":
    unittest.main()
