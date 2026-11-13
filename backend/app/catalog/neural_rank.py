"""Локальные модели для GPU-поиска и оценки пары запрос — карточка."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any

QWEN_INSTRUCTION = "Retrieve a learning material that directly helps a small business complete the requested task."


class LocalModel:
    def __init__(self, directory: Path, kind: str) -> None:
        import torch  # type: ignore[import-not-found]  # noqa: PLC0415
        from transformers import (  # type: ignore[import-not-found]  # noqa: PLC0415
            AutoModel,
            AutoModelForCausalLM,
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        self.torch = torch
        self.kind = kind
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, padding_side="left" if kind.startswith("qwen") else "right"
        )
        factory = {
            "qwen": AutoModelForCausalLM,
            "bge": AutoModelForSequenceClassification,
            "qwen-embedding": AutoModel,
        }[kind]
        self.model = (
            factory.from_pretrained(
                directory,
                local_files_only=True,
                use_safetensors=True,
                torch_dtype=torch.float16,
                attn_implementation="sdpa",
            )
            .to("cuda")
            .eval()
        )
        self.model.config.use_cache = False
        if kind == "qwen":
            self.prefix = self.tokenizer.encode(
                "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the "
                'Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n',
                add_special_tokens=False,
            )
            self.suffix = self.tokenizer.encode(
                "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n", add_special_tokens=False
            )
            self.yes = self.tokenizer.convert_tokens_to_ids("yes")
            self.no = self.tokenizer.convert_tokens_to_ids("no")

    def encode(self, texts: list[str], *, query: bool = False) -> Any:
        if query:
            texts = [f"Instruct: {QWEN_INSTRUCTION}\nQuery: {text}" for text in texts]
        inputs = self.tokenizer(texts, max_length=256, truncation=True, padding=True, return_tensors="pt").to("cuda")
        with self.torch.inference_mode():
            hidden = self.model(**inputs, use_cache=False).last_hidden_state[:, -1].float()
            return self.torch.nn.functional.normalize(hidden, dim=-1).cpu().numpy()

    def score(self, query: str, cards: list[str], *, deadline: float | None = None) -> list[float]:
        scores = []
        query_ids = self.tokenizer.encode(query, add_special_tokens=False, truncation=True, max_length=128)
        bounded_query = self.tokenizer.decode(query_ids, skip_special_tokens=True)
        with self.torch.inference_mode():
            for start in range(0, len(cards), 8):
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError("GPU deadline")
                batch = cards[start : start + 8]
                if self.kind == "qwen":
                    text = self.tokenizer(
                        [
                            f"<Instruct>: {QWEN_INSTRUCTION}\n<Query>: {bounded_query}\n<Document>: {card}"
                            for card in batch
                        ],
                        add_special_tokens=False,
                        truncation=True,
                        max_length=384 - len(self.prefix) - len(self.suffix),
                    )["input_ids"]
                    inputs = self.tokenizer.pad(
                        {"input_ids": [self.prefix + ids + self.suffix for ids in text]},
                        padding=True,
                        return_tensors="pt",
                    ).to("cuda")
                    logits = self.model(**inputs, use_cache=False, logits_to_keep=1).logits[:, -1].float()
                    values = logits[:, self.yes] - logits[:, self.no]
                else:
                    documents = self.tokenizer(batch, add_special_tokens=False, truncation=True, max_length=248)[
                        "input_ids"
                    ]
                    pairs = [self.tokenizer.build_inputs_with_special_tokens(query_ids, doc) for doc in documents]
                    inputs = self.tokenizer.pad({"input_ids": pairs}, padding=True, return_tensors="pt").to("cuda")
                    values = self.model(**inputs).logits.flatten().float()
                scores.extend(values.sigmoid().cpu().tolist())
        return scores
