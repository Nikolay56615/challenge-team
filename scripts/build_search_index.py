"""Собрать локальный индекс карточек рядом с подготовленным каталогом."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.catalog.global_search import build
from app.catalog.sqlite_source import load_sqlite_catalog, search_cards


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mapping", type=Path)
    args = parser.parse_args()
    output = args.output_dir or args.catalog.parent / "search"
    if output.exists() or output.is_symlink():
        parser.error("Укажите новый каталог индекса")
    try:
        catalog = load_sqlite_catalog(args.catalog, mapping_path=args.mapping)
        cards = search_cards(args.catalog, catalog)
        with TemporaryDirectory(dir=output.parent) as temporary:
            staging = Path(temporary) / "search"
            staging.mkdir()
            build(staging, cards, args.model_dir)
            staging.rename(output)
    except Exception as error:
        parser.exit(1, f"Не удалось собрать поисковый индекс ({type(error).__name__})\n")
    print(f"Карточек в индексе: {len(cards)}")


if __name__ == "__main__":
    main()
