"""Materialise the synthetic dataset to disk.

The servers generate the dataset in memory on first use, so nothing *needs* this.
It exists so a person can look at the data: open a JSON file, read a few orders,
check that a planted pattern looks the way the eval label claims it does.

Output goes to ``seed-data/generated/``, which is gitignored - it is derived from
the seed and reproducible at any time.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backstop_domain.generator import DEFAULT_SEED, Dataset, GeneratorConfig, generate
from backstop_domain.policy import load_corpus

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPOSITORY_ROOT / "seed-data" / "generated"
POLICY_DIR = REPOSITORY_ROOT / "seed-data" / "policies"


def _dump(records: Sequence[BaseModel]) -> list[dict[str, Any]]:
    return [record.model_dump(mode="json") for record in records]


def write_dataset(data: Dataset, destination: Path) -> dict[str, Path]:
    destination.mkdir(parents=True, exist_ok=True)

    files = {
        "products": _dump(data.products),
        "customers": _dump(data.customers),
        "orders": _dump(data.orders),
        "shipments": _dump(data.shipments),
        "returns": _dump(data.returns),
        # Ground truth. Written for the eval harness and for a human reading the
        # data; never served by a tool.
        "fraud_annotations": _dump(data.fraud_annotations),
    }

    written: dict[str, Path] = {}
    for name, payload in files.items():
        path = destination / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        written[name] = path
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--customers", type=int, default=500)
    parser.add_argument("--orders", type=int, default=2000)
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    config = replace(
        GeneratorConfig(), seed=args.seed, customers=args.customers, orders=args.orders
    )
    data = generate(config)
    written = write_dataset(data, args.out)

    corpus = load_corpus(POLICY_DIR)

    print(f"Dataset written to {args.out.relative_to(REPOSITORY_ROOT)}  (seed {args.seed})")
    for name, path in written.items():
        count = len(json.loads(path.read_text(encoding="utf-8")))
        print(f"  {name:<20} {count:>6}  {path.name}")

    print("\nPolicy corpus")
    for document in corpus.documents:
        print(
            f"  {document.document_id:<20} {len(document.clauses):>6}  "
            f"clauses, version {document.version}"
        )
    print(f"  {'ambiguities':<20} {len(corpus.ambiguities):>6}  planted contradictions")

    print("\nPlanted patterns (ground truth, never served by a tool)")
    by_pattern: dict[str, int] = {}
    for annotation in data.fraud_annotations:
        by_pattern[annotation.pattern.value] = by_pattern.get(annotation.pattern.value, 0) + 1
    for pattern, count in sorted(by_pattern.items()):
        print(f"  {pattern:<24} {count:>3}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
