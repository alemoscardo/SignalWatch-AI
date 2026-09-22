"""Repeatable retrieval and real-model runs, persisted in PostgreSQL."""

import hashlib
import json
import os
from pathlib import Path
from time import monotonic

import psycopg
from psycopg.types.json import Jsonb
from .database import connect, MAINTENANCE_LOCK
from .knowledge import MODES, search_documents, status, MIN_SIMILARITY
from .agent import (
    DEFAULT_OPENROUTER_MODEL,
    investigation_events,
    SYSTEM,
    TOOLS,
)
from . import knowledge
from itertools import product
from datetime import datetime, timezone
from .telemetry import read_measurements, detect_alerts

FIXTURES = Path(__file__).parent / "evaluation"
CRITERIA = {
    "numeric_consistency",
    "citation_support",
    "missing_data",
    "conflicts",
    "causal_restraint",
}


def run(
    database=None, *, kind="retrieval", modes=MODES, split="all", attempts=1, live=False
):
    database = database or os.getenv("DATABASE_URL")
    if (
        kind not in ("retrieval", "reports")
        or not modes
        or len(set(modes)) != len(modes)
        or any(m not in MODES for m in modes)
        or attempts < 1
    ):
        raise ValueError("Invalid evaluation settings.")
    if kind == "reports" and (not live or not os.getenv("OPENROUTER_API_KEY")):
        raise ValueError(
            "Real-model evaluation requires --live and OPENROUTER_API_KEY. No simulated quality scores are produced."
        )
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    state = status(database)
    if not state["ready"]:
        raise RuntimeError(state["message"])
    source = (FIXTURES / f"{kind}.json").read_bytes()
    cases = json.loads(source)
    cases = [c for c in cases if split == "all" or c.get("split") == split]
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Empty evaluation split or duplicate case IDs.")
    config = {
        "fixture_sha256": hashlib.sha256(source).hexdigest(),
        "generation": state["generation"],
        "prompt_sha256": hashlib.sha256(
            json.dumps({"system": SYSTEM, "tools": TOOLS}, sort_keys=True).encode()
        ).hexdigest(),
        "prompt": {"system": SYSTEM, "tools": TOOLS},
        "model": model if kind == "reports" else None,
        "modes": list(modes),
        "split": split,
        "attempts": attempts,
        "cases": len(cases),
        "similarity_cutoff": MIN_SIMILARITY,
        "cases_snapshot": cases,
    }
    with connect(database, readonly=True) as db:
        config["corpus_manifest"] = db.execute(
            "SELECT manifest FROM corpus_generations WHERE id=%s",
            (state["generation"],),
        ).fetchone()["manifest"]
        telemetry = db.execute(
            "SELECT dataset,sensor,timestamp::text,value FROM measurements ORDER BY dataset,sensor,timestamp"
        ).fetchall()
    config["telemetry_sha256"] = hashlib.sha256(
        json.dumps(telemetry, sort_keys=True).encode()
    ).hexdigest()
    config["telemetry_snapshot"] = telemetry if kind == "reports" else None
    config["code_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(__file__).parent.glob("*.py")
    }
    with connect(database) as db:
        run_id = db.execute(
            "INSERT INTO evaluation_runs(kind,config) VALUES (%s,%s) RETURNING id",
            (kind, Jsonb(config)),
        ).fetchone()["id"]
    run_status = "completed"
    try:
        with connect(database, readonly=True) as lock:
            lock.execute("SELECT pg_advisory_lock_shared(%s)", (MAINTENANCE_LOCK,))
            for case, mode, attempt in product(cases, modes, range(1, attempts + 1)):
                run_attempt(
                    database, run_id, kind, case, mode, attempt, state["generation"]
                )

    except KeyboardInterrupt:
        run_status = "cancelled"
    except Exception:
        run_status = "failed"
        raise
    finally:
        with connect(database) as db:
            db.execute(
                "UPDATE evaluation_runs SET status=%s WHERE id=%s", (run_status, run_id)
            )
    return run_id


def retrieval_case(database, case, mode, generation):
    passages = search_documents(
        case["query"],
        database,
        equipment=case.get("equipment", "M-01"),
        at=case.get("at", knowledge.DEFAULT_DATE),
        generation=generation,
        mode=mode,
    )
    found = {f"{p['document']}#{p['section']}" for p in passages}
    expected = set(case["expected"])
    return {
        "status": "completed",
        "passages": passages,
        "hit": bool(found & expected) if expected else None,
        "coverage": len(found & expected) / len(expected) if expected else None,
        "false_positive": bool(passages) if not expected else None,
        "forbidden": sorted(found & set(case.get("forbidden", []))),
    }


def report_case(database, case, mode, result):
    alerts = detect_alerts(
        read_measurements(database, "temperature", scenario=case["scenario"])
    )
    index = case.get("alert_index", 0)
    if not 0 <= index < len(alerts):
        raise ValueError("Evaluation alert not found in the dataset.")
    for event in investigation_events(
        database, alerts[index], case["context"], scenario=case["scenario"], mode=mode
    ):
        if event["type"] == "tool":
            result["trace"].append(event["call"])
        elif event["type"] == "metrics":
            result.update({key: value for key, value in event.items() if key != "type"})
        elif event["type"] == "result":
            result.update(event["result"])
            result["expected"] = case["expected"]
    if result["status"] == "running":
        raise RuntimeError("Investigation ended without a report.")


def run_attempt(database, run_id, kind, case, mode, attempt, generation):
    started = monotonic()
    result = {
        "status": "running",
        "trace": [],
        "calls": 0,
        "tokens": None,
        "known_tokens": 0,
        "model": "unknown",
    }
    key = (run_id, case["id"], mode, attempt)
    with connect(database) as db:
        db.execute(
            "INSERT INTO evaluation_results(run_id,case_id,mode,attempt,result) VALUES (%s,%s,%s,%s,%s)",
            (*key, Jsonb(result)),
        )
    try:
        if kind == "retrieval":
            result.update(retrieval_case(database, case, mode, generation))
        else:
            report_case(database, case, mode, result)
    except KeyboardInterrupt:
        result["status"] = "cancelled"
        raise
    except Exception as error:
        result["status"] = "error"
        if isinstance(error, psycopg.Error):
            result["error"] = "PostgreSQL error"
        elif isinstance(error, (ValueError, RuntimeError)):
            result["error"] = str(error)
        else:
            result["error"] = (
                f"Unexpected {type(error).__name__}; inspect the local failure."
            )
            raise
    finally:
        result["seconds"] = round(monotonic() - started, 3)
        with connect(database) as db:
            db.execute(
                "UPDATE evaluation_results SET result=%s WHERE run_id=%s AND case_id=%s AND mode=%s AND attempt=%s",
                (Jsonb(result), *key),
            )


def review(database, run_id, case_id, mode, attempt, rubric, reviewer="human"):
    if reviewer not in ("human", "assistant"):
        raise ValueError("Reviewer must be human or assistant.")
    if set(rubric) != CRITERIA or any(
        not isinstance(v, dict)
        or set(v) != {"verdict", "reason"}
        or v["verdict"] not in ("pass", "fail", "not_applicable")
        or not isinstance(v["reason"], str)
        or not v["reason"].strip()
        or v["reason"].startswith("Replace with")
        for v in rubric.values()
    ):
        raise ValueError(
            "Review must contain all five criteria, each with verdict and a non-empty reason."
        )
    with connect(database) as db:
        row = db.execute(
            "SELECT r.kind,e.result FROM evaluation_results e JOIN evaluation_runs r ON r.id=e.run_id WHERE run_id=%s AND case_id=%s AND mode=%s AND attempt=%s",
            (run_id, case_id, mode, attempt),
        ).fetchone()
        if (
            not row
            or row["kind"] != "reports"
            or row["result"].get("status")
            not in ("references_valid", "supported", "insufficient_evidence")
        ):
            raise ValueError(
                "Only completed real-model reports can receive a semantic review."
            )
        db.execute(
            "UPDATE evaluation_results SET review=%s WHERE run_id=%s AND case_id=%s AND mode=%s AND attempt=%s",
            (
                Jsonb(
                    {
                        "reviewer": reviewer,
                        "reviewed_at": datetime.now(timezone.utc).isoformat(),
                        "criteria": rubric,
                    }
                ),
                run_id,
                case_id,
                mode,
                attempt,
            ),
        )


def export(database, run_id, folder):
    with connect(database, readonly=True) as db:
        run = db.execute(
            "SELECT * FROM evaluation_runs WHERE id=%s", (run_id,)
        ).fetchone()
        if not run:
            raise ValueError("Evaluation run not found.")
        rows = db.execute(
            "SELECT case_id,mode,attempt,result,review FROM evaluation_results WHERE run_id=%s ORDER BY case_id,mode,attempt",
            (run_id,),
        ).fetchall()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {**run, "created_at": run["created_at"].isoformat(), "results": rows}
    (folder / f"evaluation-{run_id}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        f"# {run['kind'].capitalize()} evaluation {run_id}",
        "",
        f"Run status: {run['status']}. Corpus generation: {run['config']['generation']}.",
        "",
        "This is a small synthetic benchmark. Retrieval similarity and valid citations do not establish factual support or a physical root cause.",
        "",
    ]
    for mode in run["config"]["modes"]:
        results = [r for r in rows if r["mode"] == mode]
        expected_count = run["config"]["cases"] * run["config"]["attempts"]
        completed = [
            r
            for r in results
            if r["result"]["status"]
            in ("completed", "references_valid", "supported", "insufficient_evidence")
        ]
        lines += [
            f"## {mode}",
            "",
            f"Completed: {len(completed)}/{expected_count} planned attempts.",
        ]
        if run["kind"] == "retrieval":
            answerable = [r for r in completed if r["result"].get("hit") is not None]
            unanswered = [
                r for r in completed if r["result"].get("false_positive") is not None
            ]
            lines += [
                f"Expected passage in first five: {sum(r['result']['hit'] for r in answerable)}/{len(answerable)} answerable completed cases.",
                f"Unanswerable queries returning candidates: {sum(r['result']['false_positive'] for r in unanswered)}/{len(unanswered)}.",
                f"Forbidden-source cases: {sum(bool(r['result']['forbidden']) for r in completed)}.",
            ]
        else:
            lines += [
                f"Reviews completed: {sum(r['review'] is not None for r in completed)}/{len(completed)}. "
                f"Human: {sum(bool(r['review']) and r['review'].get('reviewer', 'human') == 'human' for r in completed)}. "
                "Assistant reviews are not independent human validation. Unreviewed reports have no semantic-quality score."
            ]
        lines += [
            "",
            "| Case | Attempt | Status | Seconds | Detail |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in results:
            value = row["result"]
            detail = value.get("error") or (
                f"hit={value['hit']}; coverage={value['coverage']}; false_positive={value['false_positive']}"
                if "hit" in value
                else (
                    "review pending"
                    if row["review"] is None
                    else "; ".join(
                        f"{k}: {v['verdict']}"
                        for k, v in row["review"].get("criteria", row["review"]).items()
                    )
                )
            )
            if row["review"]:
                rubric = row["review"].get("criteria", row["review"])
                detail = row["review"].get("reviewer", "human") + ": " + detail
                if any(
                    rubric[k]["verdict"] == "fail"
                    for k in ("numeric_consistency", "causal_restraint")
                ):
                    detail = "CRITICAL REVIEW FAILURE: " + detail
            lines.append(
                f"| {row['case_id']} | {row['attempt']} | {value['status']} | {value.get('seconds','unknown')} | {detail.replace('|','/')} |"
            )
        lines += [""]
    path = folder / f"evaluation-{run_id}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)
