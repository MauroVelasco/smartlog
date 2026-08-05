"""
End-to-end pipeline runner: walks the full architecture from Log Sources
through the Relationship Store, i.e. everything up to — but not
including — starting the Visualization UI server (run that separately
with `uvicorn visualization.app:app --reload`, see README).

Usage:
    python main.py --since 1h                 # CloudWatch primary, hybrid correlation
    python main.py --since 2026-08-01T00:00:00Z --until 2026-08-01T06:00:00Z
    python main.py --since 1h --no-llm         # deterministic-only, no LLM cost
    python main.py --since 1h --init-schema    # first run: create Postgres tables
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timedelta, timezone

from correlation.pipeline import run_correlation
from extraction.registry import build_extractors
from normalization.normalizer import normalize
from storage.relationship_store import RelationshipStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

_RELATIVE_PATTERN = re.compile(r"^(\d+)(m|h|d)$")


def parse_time(value: str) -> datetime:
    match = _RELATIVE_PATTERN.match(value)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
        return datetime.now(timezone.utc) - delta
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run(start_time: datetime, end_time: datetime, use_llm: bool, init_schema: bool) -> None:
    store = RelationshipStore()
    if init_schema:
        logger.info("Creating Relationship Store schema (if not exists)...")
        store.create_schema()

    logger.info("Stage 1/4 — Log Sources: extracting %s -> %s", start_time.isoformat(), end_time.isoformat())
    extractors = build_extractors()
    raw_records = []
    for extractor in extractors:
        records = extractor.extract(start_time, end_time)
        logger.info("  %s: %d raw records", extractor, len(records))
        raw_records.extend(records)

    logger.info("Stage 2/4 — Ingestion & Normalization")
    events = normalize(raw_records, start_time=start_time, end_time=end_time)
    logger.info("  %d normalized LogEvents", len(events))

    logger.info("Stage 3/4 — LangChain Correlation Agents (use_llm=%s)", use_llm)
    edges, stats = run_correlation(events, use_llm=use_llm)
    logger.info("  %s", stats)

    logger.info("Stage 4/4 — Relationship Store: persisting to Postgres")
    store.save_events(events)
    store.save_edges(edges)

    incidents = store.list_incidents()
    logger.info(
        "Done. %d incidents in the store. Start the Visualization UI with:\n"
        "    uvicorn visualization.app:app --reload\n"
        "then open http://localhost:8000",
        len(incidents),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", required=True, help="Start of extraction window: '1h', '30m', or ISO8601 UTC")
    parser.add_argument("--until", default=None, help="End of extraction window (default: now)")
    parser.add_argument("--no-llm", action="store_true", help="Skip the LangChain semantic fallback")
    parser.add_argument("--init-schema", action="store_true", help="Create Postgres tables if they don't exist")
    args = parser.parse_args()

    start_time = parse_time(args.since)
    end_time = parse_time(args.until) if args.until else datetime.now(timezone.utc)

    if start_time >= end_time:
        logger.error("--since must be before --until")
        sys.exit(1)

    run(start_time, end_time, use_llm=not args.no_llm, init_schema=args.init_schema)


if __name__ == "__main__":
    main()
