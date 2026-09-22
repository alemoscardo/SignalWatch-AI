"""Explicit local setup, migration, preparation and evaluation commands."""

import argparse
import json
from pathlib import Path
import psycopg
from dotenv import load_dotenv
from .database import initialize
from .telemetry import seed_demo, SCENARIOS
from . import encoder, knowledge, evaluation
from .migration import migrate


def main():
    load_dotenv(Path.cwd() / ".env", encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "seed", "encoder-setup", "prepare", "status"):
        sub.add_parser(name)
    migration = sub.add_parser("migrate")
    migration.add_argument("source", type=Path)
    migration.add_argument("--dataset", choices=SCENARIOS)
    ev = sub.add_parser("evaluate")
    ev.add_argument("kind", choices=("retrieval", "reports"))
    ev.add_argument(
        "--mode", nargs="+", choices=knowledge.MODES, default=list(knowledge.MODES)
    )
    ev.add_argument(
        "--split", choices=("all", "development", "held_out"), default="all"
    )
    ev.add_argument("--attempts", type=int, default=1)
    ev.add_argument("--live", action="store_true")
    ev.add_argument("--output", default="reports/local")
    exp = sub.add_parser("export")
    exp.add_argument("run_id", type=int)
    exp.add_argument("--output", default="reports/local")
    rev = sub.add_parser("review")
    rev.add_argument("run_id", type=int)
    rev.add_argument("case_id")
    rev.add_argument("mode", choices=knowledge.MODES)
    rev.add_argument("rubric", type=Path)
    rev.add_argument("--attempt", type=int, default=1)
    rev.add_argument("--reviewer", choices=("human", "assistant"), default="human")
    args = parser.parse_args()
    try:
        result = None
        if args.command == "init":
            initialize()
        elif args.command == "seed":
            for scenario in SCENARIOS:
                seed_demo(scenario=scenario)
        elif args.command == "encoder-setup":
            result = encoder.setup()
        elif args.command == "prepare":
            result = knowledge.prepare()
        elif args.command == "status":
            result = knowledge.status()
        elif args.command == "migrate":
            result = migrate(args.source, dataset=args.dataset)
        elif args.command == "evaluate":
            run_id = evaluation.run(
                kind=args.kind,
                modes=args.mode,
                split=args.split,
                attempts=args.attempts,
                live=args.live,
            )
            result = evaluation.export(None, run_id, args.output)
        elif args.command == "export":
            result = evaluation.export(None, args.run_id, args.output)
        elif args.command == "review":
            evaluation.review(
                None,
                args.run_id,
                args.case_id,
                args.mode,
                args.attempt,
                json.loads(args.rubric.read_text(encoding="utf-8")),
                reviewer=args.reviewer,
            )
        print(
            json.dumps(result if result is not None else {"status": "done"}, indent=2)
        )
    except psycopg.Error:
        parser.exit(
            1,
            "PostgreSQL operation failed. Check the service, connection settings, schema and pgvector extension.\n",
        )
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
