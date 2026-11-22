"""Bundle the pinned desktop OCR models; no runtime download is needed."""

import hashlib
import json
from pathlib import Path
import shutil
import sys

from rapidocr import RapidOCR


def prepare(destination):
    engine = RapidOCR()
    from rapidocr.ch_ppocr_cls import TextClassifier
    from rapidocr.ch_ppocr_det import TextDetector
    from rapidocr.ch_ppocr_rec import TextRecognizer

    destination.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, factory in (("Det", TextDetector), ("Cls", TextClassifier), ("Rec", TextRecognizer)):
        config = getattr(engine.cfg, name)
        config.engine_cfg = engine.cfg.EngineConfig[config.engine_type.value]
        config.model_root_dir = engine.cfg.Global.model_root_dir
        config.font_path = None
        model = factory(config)
        source = Path(model.session.session._model_path)
        target = destination / f"{name}.onnx"
        shutil.copyfile(source, target)
        manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
