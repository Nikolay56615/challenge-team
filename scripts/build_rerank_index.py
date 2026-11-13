"""Подготовить корпус и GPU-индекс. Чтение бэкапа выполняется отдельной локальной командой."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from import_alfa_backup import read_article_paragraphs, read_public_descriptions

from app.catalog.global_search import build, digest, fingerprint, model_checksums
from app.catalog.reranked_search import corpus_cards, write_passages
from app.catalog.sqlite_source import load_sqlite_catalog, search_cards


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--extra-descriptions", action="store_true")
    parser.add_argument("--passages", action="store_true")
    parser.add_argument("--encoder", choices=("e5", "qwen-embedding"), default="e5")
    parser.add_argument("--encoder-dir", type=Path)
    parser.add_argument("--model", choices=("qwen", "bge"), default="bge")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--budget", type=int, choices=(30, 50, 80), default=30)
    parser.add_argument("--mapping", type=Path)
    args = parser.parse_args()
    catalog = load_sqlite_catalog(args.catalog, mapping_path=args.mapping)
    base = search_cards(args.catalog, catalog)
    snapshot = digest(args.catalog)
    if args.output.exists():
        parser.error("Укажите новый путь назначения")
    if args.extract_only:
        if not args.backup:
            parser.error("Для подготовки корпуса нужен --backup")
        descriptions = read_public_descriptions(args.backup, catalog)
        sections = read_article_paragraphs(args.backup, catalog, sections=True)
        with args.output.open("x", encoding="utf-8") as target:
            json.dump({"snapshot": snapshot, "descriptions": descriptions, "sections": sections}, target,
                      ensure_ascii=False)
        print(json.dumps({"descriptions": len(descriptions), "articles": len(sections)}))
        return
    if not args.encoder_dir or ((args.extra_descriptions or args.passages) and not args.corpus):
        parser.error("Укажите папку модели поиска и корпус для дополнительных полей")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8")) if args.corpus else {}
    if corpus and corpus["snapshot"] != snapshot:
        parser.error("Корпус относится к другому снимку каталога")
    with TemporaryDirectory(dir=args.output.parent) as temporary:
        output = Path(temporary) / "index"
        output.mkdir()
        descriptions = output / "descriptions.json"
        descriptions.write_text(json.dumps(corpus.get("descriptions", {}) if args.extra_descriptions else {}),
                                encoding="utf-8")
        cards = corpus_cards(base, output, catalog)
        build(output, cards, args.encoder_dir, encoder_kind=args.encoder)
        passages = output / "passages.sqlite3"
        count = 0
        if args.passages:
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(args.encoder_dir / "tokenizer.json"))
            sections = {m.id: corpus["sections"][m.id] for m in catalog.materials.values()
                        if m.available and m.format == "article" and m.access == "open" and m.id in corpus["sections"]}
            count = write_passages(passages, sections, tokenizer)
        policy = {
            "catalog": fingerprint(base), "snapshot": snapshot, "index": digest(output / "manifest.json"),
            "descriptions": digest(descriptions), "passages": digest(passages) if count else None,
            "model": args.model, "weights": model_checksums(args.model_dir, args.model) if args.model_dir else None,
            "budget": args.budget, "thresholds": [0.35, 0.85], "protect_exact": True, "calibrated": False,
        }
        (output / "rerank.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
        output.rename(args.output)
    print(json.dumps({"cards": len(cards), "passages": count}))


if __name__ == "__main__":
    main()
