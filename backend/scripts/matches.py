"""The match admin tool (Story 4.5) from the command line: the same services as /v1/admin.

Run from backend/ (or in the api container: docker compose exec api python -m ...):
  uv run python -m scripts.matches disputed --operator <firebase_uid> [--limit N] [--offset N]
  uv run python -m scripts.matches uncertain --operator <firebase_uid> [--limit N] [--offset N]
  uv run python -m scripts.matches proposed --operator <firebase_uid> [--limit N] [--offset N]
  uv run python -m scripts.matches approve <alias_id> [<product_id>] --operator <firebase_uid>
  uv run python -m scripts.matches approve-product <product_id> --operator <firebase_uid>
  uv run python -m scripts.matches merge <keep_id> <remove_id> --operator <firebase_uid>

--operator is the Firebase UID of a registered user that is in OPERATOR_FIREBASE_UIDS. Lists are
printed one tab-separated line per item, with the total on stderr. Refuses to run when the
database cannot be reached.
"""

import argparse
import io
import sys
import uuid
from collections.abc import Callable, Sequence

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import make_engine
from app.core.errors import AppError
from app.modules.catalog import service as catalog_service
from app.modules.identity import service as identity_service
from app.modules.matching import service as matching_service

PROG = "matches"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class NotOperatorError(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"python -m scripts.{PROG}")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name)
        sub.add_argument("--operator", required=True, help="the operator's Firebase UID")
        return sub

    for name in ("disputed", "uncertain", "proposed"):
        sub = command(name)
        sub.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
        sub.add_argument("--offset", type=int, default=0)
    approve = command("approve")
    approve.add_argument("alias_id", type=uuid.UUID)
    approve.add_argument("product_id", type=uuid.UUID, nargs="?")
    approve_product = command("approve-product")
    approve_product.add_argument("product_id", type=uuid.UUID)
    merge = command("merge")
    merge.add_argument("keep_id", type=uuid.UUID)
    merge.add_argument("remove_id", type=uuid.UUID)
    return parser


def operator_user_id(session: Session, firebase_uid: str, settings: Settings) -> uuid.UUID:
    """The user_id of the operator with this Firebase UID: in OPERATOR_FIREBASE_UIDS, registered
    and not deleted. Raises NotOperatorError otherwise."""
    uid = firebase_uid.strip()
    if uid not in settings.operator_firebase_uids:
        raise NotOperatorError("not an operator (the UID is not in OPERATOR_FIREBASE_UIDS)")
    user = identity_service.user_for_firebase_uid(session, uid)
    if user is None or user.deleted:
        raise NotOperatorError("not an operator (no registered user with this UID)")
    return user.id


def _cell(value: object) -> str:
    # One line per item: a tab or newline in a name would break it.
    return "" if value is None else " ".join(str(value).split())


def _line(*values: object) -> str:
    return "\t".join(_cell(v) for v in values)


def list_disputed(session: Session, limit: int, offset: int) -> tuple[int, list[str]]:
    """alias_id, chain, alias text, product_id, product name, votes (product_id:count, ...)."""
    total, items = matching_service.disputed_matches(session, limit, offset)
    return total, [
        _line(
            item.alias.id,
            item.alias.chain_name,
            item.alias.alias_text,
            item.alias.product_id,
            item.alias.product_name,
            ", ".join(f"{v.product_id}:{v.votes}" for v in item.votes),
        )
        for item in items
    ]


def list_uncertain(session: Session, limit: int, offset: int) -> tuple[int, list[str]]:
    """alias_id, occurrences, chain, alias text, product_id, confidence, candidates
    (product_id:score name; ...)."""
    total, items = matching_service.uncertain_matches(session, limit, offset)
    return total, [
        _line(
            item.alias.id,
            item.alias.occurrences,
            item.alias.chain_name,
            item.alias.alias_text,
            item.alias.product_id,
            item.alias.confidence,
            "; ".join(f"{c.product_id}:{c.score} {c.product_name or ''}" for c in item.candidates),
        )
        for item in items
    ]


def list_proposed(session: Session, limit: int, offset: int) -> tuple[int, list[str]]:
    """product_id, alias count, barcode, name."""
    total, items = catalog_service.proposed_products(session, limit, offset)
    return total, [_line(p.id, p.alias_count, p.barcode, p.name) for p in items]


_LISTS: dict[str, Callable[[Session, int, int], tuple[int, list[str]]]] = {
    "disputed": list_disputed,
    "uncertain": list_uncertain,
    "proposed": list_proposed,
}


def _act(session: Session, args: argparse.Namespace, operator: uuid.UUID) -> str:
    if args.command == "approve":
        approval = matching_service.operator_approve_match(
            session, args.alias_id, operator, args.product_id
        )
        session.commit()
        outcome = approval.outcome
        return (
            f"alias {outcome.alias_id} is {outcome.state} for product {outcome.product_id}"
            f" (changed: {outcome.changed}; other final aliases moved: "
            f"{len(approval.realigned_alias_ids)})"
        )
    if args.command == "approve-product":
        status, changed = matching_service.operator_approve_product(
            session, args.product_id, operator
        )
        session.commit()
        return f"product {args.product_id} is {status} (changed: {changed})"
    merged = matching_service.merge_products(session, args.keep_id, args.remove_id, operator)
    session.commit()
    return (
        f"product {merged.remove_id} is merged into {merged.keep_id}: "
        f"{merged.aliases_moved} aliases, {merged.observations_moved} observations, "
        f"{merged.promotion_products_moved} promotion products, {merged.votes_moved} votes moved; "
        f"barcode moved: {merged.barcode_moved}"
    )


def run(argv: Sequence[str], session_factory: Callable[[], Session], settings: Settings) -> int:
    try:
        args = _parser().parse_args(list(argv))
    except SystemExit as exc:  # argparse printed the usage
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        with session_factory() as session:
            operator = operator_user_id(session, args.operator, settings)
            if args.command in _LISTS:
                limit = min(max(args.limit, 1), MAX_LIMIT)
                total, lines = _LISTS[args.command](session, limit, max(args.offset, 0))
                for line in lines:
                    print(line)
                print(f"{PROG}: {args.command}: {len(lines)} of {total}", file=sys.stderr)
                return 0
            print(_act(session, args, operator))
            return 0
    except NotOperatorError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1
    except AppError as exc:
        print(f"{PROG}: {exc.code}: {exc.message_he}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(f"{PROG}: database error ({type(exc).__name__})", file=sys.stderr)
        return 1


def main(argv: Sequence[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")  # alias texts and product names are in Hebrew
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    try:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            print(f"{PROG}: no database ({type(exc).__name__}); set DATABASE_URL", file=sys.stderr)
            return 1
        return run(argv, lambda: Session(engine), settings)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
