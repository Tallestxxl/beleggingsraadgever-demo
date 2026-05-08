"""Command line interface for local development."""

from __future__ import annotations

import argparse
from pathlib import Path

from .advisor import Advisor
from .collector import collect_snapshot_data
from .importer import (
    SnapshotValidationError,
    import_company_snapshot,
    load_company_snapshot,
    validate_company_snapshot,
    write_snapshot_template,
)
from .real_data import DRAFTS_DIR, seed_besi, seed_curated_snapshots
from .sample_data import seed_demo, seed_demo_instance
from .storage import DEFAULT_DB_PATH, SQLiteRepository
from .web import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beleggingsraadgever")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to local SQLite database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the local database")
    subparsers.add_parser("demo-seed", help="Load deterministic demo data")
    subparsers.add_parser("demo-instance-seed", help="Load non-private demo profile and portfolio data")
    subparsers.add_parser("seed-besi", help="Load the curated BESI v1 snapshot")
    subparsers.add_parser("seed-imports", help="Load all curated company JSON snapshots")
    demo = subparsers.add_parser("demo", help="Initialize demo data and render a demo report")
    demo.add_argument("--symbol", default="DEMO")

    import_text = subparsers.add_parser("import-text", help="Import an OCR/text file into the RAG store")
    import_text.add_argument("path", help="Path to UTF-8 text file")
    import_text.add_argument("--title", required=True)
    import_text.add_argument("--source-type", default="beleggers_belangen")
    import_text.add_argument("--author")
    import_text.add_argument("--date")
    import_text.add_argument("--tag", action="append", default=[])

    import_snapshot = subparsers.add_parser("import-snapshot", help="Import a curated company JSON snapshot")
    import_snapshot.add_argument("path", help="Path to company snapshot JSON")

    new_snapshot = subparsers.add_parser("new-snapshot", help="Create a new company JSON snapshot template")
    new_snapshot.add_argument("symbol")
    new_snapshot.add_argument("--output", help="Output path; defaults to data/drafts/<symbol>.json")
    new_snapshot.add_argument("--force", action="store_true", help="Overwrite an existing template")

    validate_snapshot = subparsers.add_parser("validate-snapshot", help="Validate a company JSON snapshot")
    validate_snapshot.add_argument("path", help="Path to company snapshot JSON")

    collect_snapshot = subparsers.add_parser("collect-snapshot", help="Prefill a draft snapshot with public data")
    collect_snapshot.add_argument("symbol")
    collect_snapshot.add_argument("--path", help="Draft path; defaults to data/drafts/<symbol>.json")

    analyze = subparsers.add_parser("analyze", help="Analyze a symbol with local data")
    analyze.add_argument("symbol")

    serve_parser = subparsers.add_parser("serve", help="Start the local web interface")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--no-seed", action="store_true", help="Do not load demo data on startup")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repository = SQLiteRepository(Path(args.db))

    if args.command == "init-db":
        repository.init()
        print(f"Database initialized: {repository.db_path}")
        return 0

    if args.command == "demo-seed":
        seed_demo(repository)
        print(f"Demo data loaded: {repository.db_path}")
        return 0

    if args.command == "demo-instance-seed":
        seed_demo_instance(repository)
        seed_curated_snapshots(repository)
        print(f"Demo instance data loaded: {repository.db_path}")
        return 0

    if args.command == "seed-besi":
        seed_besi(repository)
        print(f"BESI data loaded: {repository.db_path}")
        return 0

    if args.command == "seed-imports":
        seed_curated_snapshots(repository)
        print(f"Curated company snapshots loaded: {repository.db_path}")
        return 0

    if args.command == "demo":
        seed_demo(repository)
        advisor = Advisor(repository)
        report = advisor.analyze(args.symbol)
        print(advisor.render_markdown(report))
        return 0

    if args.command == "import-text":
        repository.init()
        raw_text = Path(args.path).read_text(encoding="utf-8")
        document_id = repository.add_document(
            title=args.title,
            source_type=args.source_type,
            raw_text=raw_text,
            author=args.author,
            publication_date=args.date,
            source_path=args.path,
            tags=args.tag,
        )
        print(f"Imported document {document_id}: {args.title}")
        return 0

    if args.command == "import-snapshot":
        try:
            symbol = import_company_snapshot(repository, Path(args.path))
        except SnapshotValidationError as error:
            _print_validation_errors(error.errors)
            return 1
        print(f"Imported company snapshot for {symbol}: {repository.db_path}")
        return 0

    if args.command == "new-snapshot":
        output = Path(args.output) if args.output else DRAFTS_DIR / f"{args.symbol.lower()}.json"
        try:
            path = write_snapshot_template(args.symbol, output, force=args.force)
        except FileExistsError as error:
            print(error)
            print("Use --force to overwrite.")
            return 1
        print(f"Snapshot template created: {path}")
        print(f"Next: edit it, then run: /bin/sh scripts/br validate-snapshot {path}")
        return 0

    if args.command == "validate-snapshot":
        try:
            errors = validate_company_snapshot(load_company_snapshot(Path(args.path)))
        except SnapshotValidationError as error:
            errors = error.errors
        if errors:
            _print_validation_errors(errors)
            return 1
        print(f"Snapshot is valid: {args.path}")
        return 0

    if args.command == "collect-snapshot":
        path = Path(args.path) if args.path else None
        result = collect_snapshot_data(args.symbol, path)
        for message in result.messages:
            print(message)
        if result.updated_fields:
            print("Bijgewerkte velden: " + ", ".join(result.updated_fields))
        if result.errors:
            if not result.messages:
                print(result.errors[0])
            print(f"Concept bijgewerkt, nog {len(result.errors)} validatiepunten open: {result.path}")
            return 1
        print(f"Snapshot is klaar voor import: {result.path}")
        return 0

    if args.command == "analyze":
        repository.init()
        advisor = Advisor(repository)
        report = advisor.analyze(args.symbol)
        print(advisor.render_markdown(report))
        return 0

    if args.command == "serve":
        serve(repository.db_path, host=args.host, port=args.port, seed=not args.no_seed)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _print_validation_errors(errors: list[str]) -> None:
    print("Snapshot validation failed:")
    for error in errors:
        print(f"- {error}")


if __name__ == "__main__":
    raise SystemExit(main())
