"""Command line interface for local development."""

from __future__ import annotations

import argparse
from pathlib import Path

from .advisor import Advisor
from .sample_data import seed_demo
from .storage import DEFAULT_DB_PATH, SQLiteRepository
from .web import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beleggingsraadgever")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to local SQLite database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the local database")
    subparsers.add_parser("demo-seed", help="Load deterministic demo data")
    demo = subparsers.add_parser("demo", help="Initialize demo data and render a demo report")
    demo.add_argument("--symbol", default="DEMO")

    import_text = subparsers.add_parser("import-text", help="Import an OCR/text file into the RAG store")
    import_text.add_argument("path", help="Path to UTF-8 text file")
    import_text.add_argument("--title", required=True)
    import_text.add_argument("--source-type", default="beleggers_belangen")
    import_text.add_argument("--author")
    import_text.add_argument("--date")
    import_text.add_argument("--tag", action="append", default=[])

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


if __name__ == "__main__":
    raise SystemExit(main())
