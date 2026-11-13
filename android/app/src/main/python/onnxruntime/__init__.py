"""The pinned RapidOCR CPU interface, backed by Android's ONNX Runtime AAR.

Only tensor transport lives here; desktop Python uses the real onnxruntime.
"""

import json
from types import SimpleNamespace

import numpy as np
from java import jclass


class GraphOptimizationLevel:
    ORT_ENABLE_ALL = 99


class SessionOptions:
    pass


def get_available_providers():
    return ["CPUExecutionProvider"]


def get_device():
    return "CPU"


class InferenceSession:
    def __init__(self, path, sess_options=None, providers=None):
        self.native = jclass("com.babanongchang.android.OnnxSession")(str(path))

    def get_inputs(self):
        return [SimpleNamespace(name=str(self.native.inputName()))]

    def get_outputs(self):
        return [SimpleNamespace(name=str(self.native.outputName()))]

    def get_providers(self):
        return get_available_providers()

    def get_modelmeta(self):
        return SimpleNamespace(custom_metadata_map=json.loads(str(self.native.metadata())))

    def run(self, output_names, inputs):
        image = np.ascontiguousarray(inputs[self.get_inputs()[0].name], dtype="<f4")
        result = self.native.run(image.tobytes(), list(image.shape))
        return [np.frombuffer(bytes(result.getData()), dtype="<f4").reshape(tuple(result.getShape()))]

    def close(self):
        self.native.close()
