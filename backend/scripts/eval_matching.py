"""SM-1 (Story 4.2): the precision of certain matches by text, measured on aliases whose answer is
known.

Run from backend/ (or in the api container: docker compose exec api python -m ...):
  uv run python -m scripts.eval_matching [--limit 500] [--seed 42] [--allow-prod]

Samples up to --limit certain aliases that have a barcode (matched by it, Story 4.1), skips those
whose text is their product's name, scores each other by its text only, as match() would (no
barcode, no price), and checks the product chosen against the barcode's. Also prints, for each
threshold from 0.50 to 0.95, how many would be certain, their precision and their coverage.

Prints JSON to stdout. Writes nothing: the transaction is rolled back. Refuses to
run when the database cannot be reached, and with ENV=prod unless --allow-prod is given.

Calibration: MATCH_CERTAIN_THRESHOLD is set to the lowest value that gives a precision of at
least 0.9 here.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import make_engine
from app.modules.catalog import service as catalog_service
from app.modules.matching import service as matching_service

DEFAULT_LIMIT = 500
DEFAULT_SEED = 42


# The sweep of MATCH_CERTAIN_THRESHOLD: 0.50, 0.55, ..., 0.95.
SWEEP = tuple(round(0.50 + 0.05 * step, 2) for step in range(10))


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def evaluate(session: Session, limit: int, seed: int) -> dict[str, Any]:
    """The report: how many aliases were evaluated, how many came out certain, uncertain or a new
    product, the precision of the certain ones, recall@3 (the right product among the top 3
    candidates), and a table of certain, precision and coverage for each threshold in SWEEP.

    A sampled alias whose text is its product's name (normalized) is skipped and counted: the
    product was named after it, so it would give the answer away. Writes nothing."""
    limits = matching_service.thresholds()
    samples = catalog_service.sample_certain_barcode_aliases(session, limit, str(seed))
    evaluated = [s for s in samples if s.alias_norm != s.product_name_norm]
    certain = certain_right = uncertain = proposals = in_top_3 = 0
    # Per sample: its scored candidates, the proposed ones among them, and the right product.
    runs: list[tuple[list[matching_service.Candidate], frozenset[Any], Any]] = []
    for sample in evaluated:
        products = catalog_service.product_candidates(session, sample.alias_norm)
        scored = matching_service.score_candidates(sample.alias_norm, products)
        proposed = matching_service.proposed_ids(products)
        runs.append((scored, proposed, sample.product_id))
        decision = matching_service.decide(scored, limits, proposed)
        if decision == "certain":
            certain += 1
            certain_right += scored[0].product_id == sample.product_id
        elif decision == "uncertain":
            uncertain += 1
        else:
            proposals += 1
        in_top_3 += any(c.product_id == sample.product_id for c in scored[:3])
    session.rollback()

    table = []
    for theta in SWEEP:
        at = matching_service.Thresholds(theta, limits.min_gap, limits.new_product_below)
        chosen = [
            scored[0].product_id == right
            for scored, proposed, right in runs
            if matching_service.decide(scored, at, proposed) == "certain"
        ]
        table.append(
            {
                "threshold": theta,
                "certain": len(chosen),
                "precision": _ratio(sum(chosen), len(chosen)),
                "coverage": _ratio(len(chosen), len(runs)),
            }
        )
    return {
        "samples": len(evaluated),
        "skipped_same_name": len(samples) - len(evaluated),
        "certain": certain,
        "certain_correct": certain_right,
        "precision": _ratio(certain_right, certain),
        "uncertain": uncertain,
        "new_product_proposals": proposals,
        "recall_at_3": _ratio(in_top_3, len(evaluated)),
        "settings": {
            "certain": limits.certain,
            "min_gap": limits.min_gap,
            "new_product_below": limits.new_product_below,
        },
        "thresholds": table,
        "seed": seed,
        "limit": limit,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_matching")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="aliases to sample")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="picks the sample")
    parser.add_argument("--allow-prod", action="store_true", help="run with ENV=prod")
    return parser


def run(argv: Sequence[str], session_factory: Callable[[], Session]) -> int:
    args = _parser().parse_args(argv)
    if args.limit < 1:
        print("eval_matching: --limit must be at least 1", file=sys.stderr)
        return 2
    with session_factory() as session:
        report = evaluate(session, args.limit, args.seed)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    if settings.ENV == "prod" and not args.allow_prod:
        print("eval_matching: refusing to run with ENV=prod without --allow-prod", file=sys.stderr)
        return 1
    engine = make_engine(settings.DATABASE_URL)
    try:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            print(
                f"eval_matching: no database ({type(exc).__name__}); set DATABASE_URL",
                file=sys.stderr,
            )
            return 1
        return run(argv, lambda: Session(engine))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
