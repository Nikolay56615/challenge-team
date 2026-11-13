"""Локальный CPU-инференс E5. Модель и токенизатор загружаются только с диска."""

from pathlib import Path
from typing import Any


class Encoder:
    def __init__(self, directory: Path) -> None:
        import numpy as np  # type: ignore[import-not-found]  # noqa: PLC0415
        import onnxruntime as ort  # type: ignore[import-not-found]  # noqa: PLC0415
        from tokenizers import Tokenizer  # type: ignore[import-not-found]  # noqa: PLC0415

        self.np = np
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")  # noqa: S106 — tokenizer symbol
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"])
        self.inputs = {item.name for item in self.session.get_inputs()}

    def encode(self, texts: list[str], *, query: bool = False) -> Any:
        prefix = "query: " if query else "passage: "
        tokens = self.tokenizer.encode_batch([prefix + text for text in texts])
        arrays = {
            "input_ids": self.np.array([item.ids for item in tokens], dtype="int64"),
            "attention_mask": self.np.array([item.attention_mask for item in tokens], dtype="int64"),
            "token_type_ids": self.np.array([item.type_ids for item in tokens], dtype="int64"),
        }
        hidden = self.session.run(["last_hidden_state"], {key: arrays[key] for key in self.inputs})[0]
        mask = arrays["attention_mask"][..., None]
        pooled = (hidden * mask).sum(axis=1, dtype="float32") / mask.sum(axis=1).astype("float32")
        return pooled / self.np.linalg.norm(pooled, axis=1, keepdims=True)
