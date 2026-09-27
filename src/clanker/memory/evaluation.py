"""Offline, deterministic evaluation of memory retrieval quality."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from clanker.memory.memories import MemoryStore


def evaluate(dataset: Path, top_k: int = 5) -> dict[str, Any]:
    """Score recall, irrelevant results, stale leakage, latency, and context size.

    The fixture is loaded into a temporary workspace. Production memories are
    never read or modified, and the evaluator requires no model/API access.
    """
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="clanker-memory-eval-") as directory:
        store = MemoryStore(directory, include_global=False)
        ids = {}
        for item in cases["memories"]:
            memory = store.add(
                item["content"], tags=item.get("tags", []),
                kind=item.get("kind", "fact"), pinned=item.get("pinned", False),
            )
            ids[item["key"]] = memory.id
            if item.get("status") == "stale":
                store.update(memory.id, status="stale")
        names = {memory_id: key for key, memory_id in ids.items()}

        measured = []
        for case in cases["queries"]:
            started = time.perf_counter()
            results = store.search(case["query"], n_results=top_k)
            elapsed_ms = (time.perf_counter() - started) * 1000
            actual = {memory.id for memory in results}
            expected = {ids[key] for key in case.get("relevant", [])}
            context = store.get_relevant_context(case["query"], max_memories=top_k)
            measured.append({
                "query": case["query"],
                "returned": [names.get(memory.id, memory.id) for memory in results],
                "recall": len(actual & expected) / len(expected) if expected else 1.0,
                "precision": len(actual & expected) / len(actual) if actual else (1.0 if not expected else 0.0),
                "stale_leakage": sum(memory.status != "active" for memory in results),
                "latency_ms": round(elapsed_ms, 2),
                "context_tokens_estimate": len(context) // 4,
            })
        n = len(measured) or 1
        return {
            "cases": len(measured), "top_k": top_k,
            "mean_recall": round(sum(row["recall"] for row in measured) / n, 3),
            "mean_precision": round(sum(row["precision"] for row in measured) / n, 3),
            "stale_leakage": sum(row["stale_leakage"] for row in measured),
            "mean_latency_ms": round(sum(row["latency_ms"] for row in measured) / n, 2),
            "mean_context_tokens_estimate": round(sum(row["context_tokens_estimate"] for row in measured) / n),
            "details": measured,
        }
