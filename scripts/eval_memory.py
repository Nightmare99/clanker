"""Run the memory retrieval fixture without touching a live workspace."""

import argparse
import json
from pathlib import Path

from clanker.memory.evaluation import evaluate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", nargs="?", type=Path, default=Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "memory_eval.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.dataset, args.top_k), indent=2))


if __name__ == "__main__":
    main()
