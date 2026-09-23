"""Persistent chat threads, turns, context snapshots and evidence."""

from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .database import connect
from .telemetry import SCENARIOS, detect_alerts, read_measurements


def datasets(database):
    with connect(database, readonly=True) as db:
        rows = db.execute(
            "SELECT d.id,d.equipment,MIN(m.timestamp) AS start,MAX(m.timestamp) AS end "
            "FROM datasets d LEFT JOIN measurements m ON m.dataset=d.id "
            "GROUP BY d.id,d.equipment ORDER BY d.id"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "label": SCENARIOS.get(row["id"], row["id"]),
            "equipment": row["equipment"],
            "start": row["start"].isoformat() if row["start"] else None,
            "end": row["end"].isoformat() if row["end"] else None,
        }
        for row in rows
    ]


def dataset_telemetry(database, dataset):
    metadata = next((row for row in datasets(database) if row["id"] == dataset), None)
    if metadata is None:
        raise ValueError("Dataset not found.")
    temperature = read_measurements(database, "temperature", scenario=dataset)
    return {
        **metadata,
        "scenario": dataset,
        "temperature": temperature,
        "speed": read_measurements(database, "speed", scenario=dataset),
        "alerts": [
            alert_row(dataset, metadata["equipment"], row)
            for row in detect_alerts(temperature)
        ],
    }


def alert_row(dataset, equipment, alert):
    reference = f"a:{dataset}@{alert['timestamp']}"
    return {
        **alert,
        "dataset": dataset,
        "equipment": equipment,
        "reference": reference,
        "citation": f"[ref:{reference}]",
        "source_type": "alert",
    }


def list_alerts(database, dataset=None):
    available = datasets(database)
    if dataset is not None and not any(row["id"] == dataset for row in available):
        raise ValueError("Dataset not found.")
    selected = [row for row in available if dataset is None or row["id"] == dataset]
    result = []
    for metadata in selected:
        temperature = read_measurements(
            database, "temperature", scenario=metadata["id"]
        )
        result.extend(
            alert_row(metadata["id"], metadata["equipment"], alert)
            for alert in detect_alerts(temperature)
        )
    return result


def resolve_alert(database, dataset, alert_id):
    for alert in list_alerts(database, dataset):
        if alert["id"] == alert_id:
            return alert
    return None


def create_thread(database):
    with connect(database) as db:
        row = db.execute(
            "INSERT INTO chat_threads DEFAULT VALUES RETURNING id,created_at,updated_at,title,active_context"
        ).fetchone()
    return row


def list_threads(database):
    with connect(database, readonly=True) as db:
        rows = db.execute(
            "SELECT c.id,c.created_at,c.updated_at,c.title,c.active_context, "
            "(SELECT user_message FROM chat_turns t WHERE t.thread_id=c.id ORDER BY t.id DESC LIMIT 1) AS last_message "
            "FROM chat_threads c ORDER BY c.updated_at DESC,c.id DESC"
        ).fetchall()
    return [
        {
            **row,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]


def load_thread(database, thread_id):
    with connect(database, readonly=True) as db:
        thread = db.execute(
            "SELECT id,created_at,updated_at,title,active_context,last_context_tokens,last_context_limit "
            "FROM chat_threads WHERE id=%s",
            (thread_id,),
        ).fetchone()
        if thread is None:
            return None
        turns = db.execute(
            "SELECT id,request_id,created_at,completed_at,user_message,context_snapshot,status,"
            "assistant_message,partial_message,trace,metrics,error FROM chat_turns "
            "WHERE thread_id=%s ORDER BY id",
            (thread_id,),
        ).fetchall()
        compactions = db.execute(
            "SELECT id,through_turn_id,created_at,summary,context_tokens_before,context_tokens_after "
            "FROM chat_compactions WHERE thread_id=%s ORDER BY id",
            (thread_id,),
        ).fetchall()
    return {
        "thread": {
            **thread,
            "created_at": thread["created_at"].isoformat(),
            "updated_at": thread["updated_at"].isoformat(),
        },
        "turns": [
            {
                **turn,
                "created_at": turn["created_at"].isoformat(),
                "completed_at": (
                    turn["completed_at"].isoformat() if turn["completed_at"] else None
                ),
            }
            for turn in turns
        ],
        "compactions": [
            {**row, "created_at": row["created_at"].isoformat()} for row in compactions
        ],
    }


def set_context(database, thread_id, context):
    with connect(database) as db:
        row = db.execute(
            "UPDATE chat_threads SET active_context=%s,updated_at=now() "
            "WHERE id=%s RETURNING id,active_context,updated_at",
            (Jsonb(context) if context is not None else None, thread_id),
        ).fetchone()
    return row


def begin_turn(database, thread_id, request_id, message):
    with connect(database) as db:
        exists = db.execute(
            "SELECT id,active_context FROM chat_threads WHERE id=%s FOR UPDATE",
            (thread_id,),
        ).fetchone()
        if exists is None:
            return None
        if db.execute(
            "SELECT 1 FROM chat_turns WHERE thread_id=%s AND status='running' LIMIT 1",
            (thread_id,),
        ).fetchone():
            raise RuntimeError("This conversation already has a running turn.")
        row = db.execute(
            "INSERT INTO chat_turns(request_id,thread_id,user_message,context_snapshot) "
            "VALUES (%s,%s,%s,%s) RETURNING id,created_at,context_snapshot",
            (
                request_id,
                thread_id,
                message,
                (
                    Jsonb(exists["active_context"])
                    if exists["active_context"] is not None
                    else None
                ),
            ),
        ).fetchone()
        db.execute(
            "UPDATE chat_threads SET updated_at=now(),title=CASE WHEN title='New chat' "
            "THEN left(%s,72) ELSE title END WHERE id=%s",
            (message.strip().replace("\n", " ") or "New chat", thread_id),
        )
    return row


def append_trace(database, turn_id, event):
    with connect(database) as db:
        row = db.execute(
            "SELECT trace FROM chat_turns WHERE id=%s AND status='running' FOR UPDATE",
            (turn_id,),
        ).fetchone()
        if row is None:
            return
        trace = row["trace"]
        trace.append(event)
        db.execute(
            "UPDATE chat_turns SET trace=%s WHERE id=%s", (Jsonb(trace), turn_id)
        )


def update_metrics(database, turn_id, metrics):
    with connect(database) as db:
        db.execute(
            "UPDATE chat_turns SET metrics=%s WHERE id=%s AND status='running'",
            (Jsonb(metrics), turn_id),
        )


def update_partial(database, turn_id, partial):
    with connect(database) as db:
        db.execute(
            "UPDATE chat_turns SET partial_message=%s WHERE id=%s AND status='running'",
            (partial, turn_id),
        )


def finish_turn(database, turn_id, answer, metrics):
    now = datetime.now(timezone.utc)
    with connect(database) as db:
        row = db.execute(
            "UPDATE chat_turns SET status='completed',assistant_message=%s,partial_message=NULL,"
            "metrics=%s,completed_at=%s,error=NULL WHERE id=%s AND status='running' "
            "RETURNING thread_id",
            (answer, Jsonb(metrics), now, turn_id),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE chat_threads SET updated_at=%s WHERE id=%s",
                (now, row["thread_id"]),
            )


def stop_turn(database, turn_id, partial, message="Generation stopped."):
    with connect(database) as db:
        row = db.execute(
            "UPDATE chat_turns SET status='interrupted',partial_message=%s,error=%s,completed_at=now() "
            "WHERE id=%s AND status='running' RETURNING thread_id",
            (partial, message, turn_id),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE chat_threads SET updated_at=now() WHERE id=%s",
                (row["thread_id"],),
            )


def fail_turn(database, turn_id, partial, message):
    with connect(database) as db:
        row = db.execute(
            "UPDATE chat_turns SET status='error',partial_message=%s,error=%s,completed_at=now() "
            "WHERE id=%s AND status='running' RETURNING thread_id",
            (partial, message[:1000], turn_id),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE chat_threads SET updated_at=now() WHERE id=%s",
                (row["thread_id"],),
            )


def latest_compaction(database, thread_id):
    with connect(database, readonly=True) as db:
        return db.execute(
            "SELECT id,through_turn_id,summary,context_tokens_before,context_tokens_after "
            "FROM chat_compactions WHERE thread_id=%s ORDER BY id DESC LIMIT 1",
            (thread_id,),
        ).fetchone()


def completed_turns(database, thread_id, after_id=0):
    with connect(database, readonly=True) as db:
        return db.execute(
            "SELECT id,user_message,context_snapshot,assistant_message,trace,metrics "
            "FROM chat_turns WHERE thread_id=%s AND status='completed' AND id>%s ORDER BY id",
            (thread_id, after_id),
        ).fetchall()


def add_compaction(database, thread_id, through_turn_id, summary, before, after):
    with connect(database) as db:
        return db.execute(
            "INSERT INTO chat_compactions(thread_id,through_turn_id,summary,context_tokens_before,context_tokens_after) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id,created_at",
            (thread_id, through_turn_id, summary, before, after),
        ).fetchone()


def evidence_for_thread(database, thread_id):
    with connect(database, readonly=True) as db:
        thread = db.execute(
            "SELECT active_context FROM chat_threads WHERE id=%s", (thread_id,)
        ).fetchone()
        turns = db.execute(
            "SELECT context_snapshot,trace FROM chat_turns WHERE thread_id=%s ORDER BY id",
            (thread_id,),
        ).fetchall()
    evidence = {}
    if thread and isinstance(thread["active_context"], dict):
        alert = thread["active_context"].get("alert")
        if isinstance(alert, dict) and isinstance(alert.get("reference"), str):
            evidence[alert["reference"]] = alert
    for turn in turns:
        context = turn["context_snapshot"]
        if isinstance(context, dict) and isinstance(context.get("alert"), dict):
            alert = context["alert"]
            evidence[alert["reference"]] = alert
        for call in turn["trace"] or []:
            for row in call.get("result", []) if isinstance(call, dict) else []:
                if isinstance(row, dict) and isinstance(row.get("reference"), str):
                    evidence[row["reference"]] = row
    return evidence


def save_context_usage(database, thread_id, tokens, limit):
    with connect(database) as db:
        db.execute(
            "UPDATE chat_threads SET last_context_tokens=%s,last_context_limit=%s WHERE id=%s",
            (tokens, limit, thread_id),
        )
