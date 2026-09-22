"""Versioned Markdown passages, local embeddings and PostgreSQL retrieval."""

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re

from psycopg.types.json import Jsonb
from .database import connect, MAINTENANCE_LOCK
from . import encoder
from .telemetry import parse_timestamp

DOCUMENTS = Path(__file__).parent / "documents"
DEFAULT_DATE = "2026-09-10T08:00:00+00:00"
MODES = ("lexical", "semantic", "hybrid")
STOP_WORDS = set(
    "a an the is are was were be to of in for on and or with this that what how why can could does it my about".split()
)
# Chosen on development cases; similarity is not confidence in an answer.
MIN_SIMILARITY = 0.35
SPLITTER_VERSION = 1


def source_manifest(folder=DOCUMENTS):
    files = sorted(folder.glob("*.md")) + [folder / "catalog.json"]
    if not (folder / "catalog.json").is_file():
        raise ValueError("Document catalog is missing.")
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def read_sources(folder=DOCUMENTS):
    catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or not catalog:
        raise ValueError("The document catalog must contain at least one document.")
    required = {"file", "manual", "equipment", "revision", "valid_from", "valid_to"}
    seen, revisions, documents = set(), {}, []
    for meta in catalog:
        if not isinstance(meta, dict) or set(meta) != required:
            raise ValueError("Invalid document metadata fields.")
        name = meta["file"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z0-9-]+\.md", name)
            or name in seen
        ):
            raise ValueError("Invalid or duplicate document filename.")
        if any(
            not isinstance(meta[k], str) or not meta[k].strip()
            for k in ("manual", "equipment")
        ):
            raise ValueError(f"{name}: missing manual or equipment.")
        if type(meta["revision"]) is not int or meta["revision"] < 1:
            raise ValueError(f"{name}: revision must be a positive integer.")
        start = parse_timestamp(meta["valid_from"])
        end = (
            parse_timestamp(meta["valid_to"])
            if meta["valid_to"]
            else datetime.max.replace(tzinfo=timezone.utc)
        )
        if start >= end:
            raise ValueError(f"{name}: invalid validity interval.")
        key = (meta["manual"], meta["equipment"])
        for old_revision, old_start, old_end in revisions.get(key, []):
            if old_revision == meta["revision"] or max(start, old_start) < min(
                end, old_end
            ):
                raise ValueError(f"{name}: duplicate or overlapping manual revisions.")
        revisions.setdefault(key, []).append((meta["revision"], start, end))
        text = (folder / name).read_text(encoding="utf-8").strip()
        if not text.startswith("# ") or "\n## " not in text or "```" in text:
            raise ValueError(
                f"{name}: expected a title and Markdown sections, without code blocks."
            )
        title, _, body = text.partition("\n")
        if body.split("\n## ")[0].strip():
            raise ValueError(f"{name}: put body text inside a section.")
        sections = []
        for section in body.split("\n## ")[1:]:
            heading, _, content = section.partition("\n")
            if not heading.strip() or not content.strip():
                raise ValueError(f"{name}: empty section.")
            sections.append((heading.strip(), content.strip()))
        documents.append(
            {
                **meta,
                "title": title[2:],
                "sections": sections,
                "version": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
        seen.add(name)
    if seen != {p.name for p in folder.glob("*.md")}:
        raise ValueError("Every Markdown file must appear exactly once in the catalog.")
    return documents


def make_passages(documents):
    model = encoder.load()
    passages = []
    for document in documents:
        position = 0
        for heading, body in document["sections"]:
            prefix = f"{document['title']}\n{heading}\n"
            chunk = ""
            for paragraph in body.split("\n\n"):
                if (
                    len(model.tokenizer.encode(prefix + paragraph))
                    > model.max_seq_length
                ):
                    raise ValueError(
                        f"{document['file']}: paragraph is too long; split it."
                    )
                combined = (chunk + "\n\n" + paragraph).strip()
                if (
                    len(model.tokenizer.encode(prefix + combined))
                    > model.max_seq_length
                ):
                    passages.append(_passage(document, heading, chunk, position))
                    position += 1
                    chunk = paragraph
                else:
                    chunk = combined
            passages.append(_passage(document, heading, chunk, position))
            position += 1
    return passages


def _passage(doc, heading, text, position):
    return {
        "id": f"{Path(doc['file']).stem}-{position + 1}-{doc['version'][:16]}",
        "document": doc["file"],
        "title": doc["title"],
        "section": heading,
        "text": text,
        "version": doc["version"],
        "equipment": doc["equipment"],
        "revision": doc["revision"],
        "valid_from": doc["valid_from"],
        "valid_to": doc["valid_to"],
    }


def prepare(database=None, folder=DOCUMENTS):
    sources = source_manifest(folder)
    passages = make_passages(read_sources(folder))
    vectors = encoder.encode(
        [f"{p['title']}\n{p['section']}\n{p['text']}" for p in passages]
    )
    manifest = {
        "sources": sources,
        "encoder": encoder.identity(),
        "splitter": SPLITTER_VERSION,
        "passages": len(passages),
        "documents": len(sources) - 1,
        "sentence_transformers": importlib.metadata.version("sentence-transformers"),
    }
    if source_manifest(folder) != sources:
        raise RuntimeError(
            "Documents changed during preparation. Retry with the app stopped."
        )
    with connect(database) as db:
        if not db.execute(
            "SELECT pg_try_advisory_xact_lock(%s) AS locked", (MAINTENANCE_LOCK,)
        ).fetchone()["locked"]:
            raise RuntimeError("Stop the app before preparing documents.")
        generation = db.execute(
            "INSERT INTO corpus_generations(manifest) VALUES (%s) RETURNING id",
            (Jsonb(manifest),),
        ).fetchone()["id"]
        with db.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO passages(generation,id,document,title,section,text,version,equipment,revision,valid_from,valid_to,embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                [
                    (
                        generation,
                        p["id"],
                        p["document"],
                        p["title"],
                        p["section"],
                        p["text"],
                        p["version"],
                        p["equipment"],
                        p["revision"],
                        p["valid_from"],
                        p["valid_to"],
                        json.dumps(v),
                    )
                    for p, v in zip(passages, vectors)
                ],
            )
        count = db.execute(
            "SELECT count(*) AS n FROM passages WHERE generation=%s", (generation,)
        ).fetchone()["n"]
        if count != len(passages):
            raise RuntimeError("Passage count mismatch; preparation rolled back.")
        db.execute(
            "SELECT id FROM passages WHERE generation=%s ORDER BY embedding <=> %s::vector LIMIT 1",
            (generation, json.dumps(vectors[0])),
        ).fetchone()
        db.execute("UPDATE corpus_generations SET active=false WHERE active")
        db.execute(
            "UPDATE corpus_generations SET active=true WHERE id=%s", (generation,)
        )
    return {"generation": generation, "passages": count, "documents": len(sources) - 1}


def status(database=None, folder=DOCUMENTS):
    with connect(database, readonly=True) as db:
        row = db.execute(
            "SELECT id, manifest FROM corpus_generations WHERE active"
        ).fetchone()
        count = db.execute(
            "SELECT count(DISTINCT document) AS documents, count(*) AS passages FROM passages WHERE generation=%s",
            (row["id"] if row else -1,),
        ).fetchone()
    try:
        manifest = row["manifest"] if row else {}
        ready = bool(
            row
            and manifest["sources"] == source_manifest(folder)
            and manifest["splitter"] == SPLITTER_VERSION
            and manifest["passages"] == count["passages"] > 0
            and manifest["documents"] == count["documents"] > 0
            and row["manifest"]["encoder"] == encoder.identity()
            and row["manifest"]["sentence_transformers"]
            == importlib.metadata.version("sentence-transformers")
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        ready = False
    return {
        "ready": ready,
        "generation": row["id"] if row else None,
        "documents": count["documents"],
        "message": (
            "Knowledge base ready"
            if ready
            else "Knowledge base needs preparation. Run signalwatch-db prepare."
        ),
    }


def document_sections(database=None, generation=None):
    with connect(database, readonly=True) as db:
        return db.execute(
            "SELECT p.id,document,title,section,text,version,equipment,revision,valid_from::text,valid_to::text "
            "FROM passages p JOIN corpus_generations c ON c.id=p.generation "
            "WHERE (%s::bigint IS NULL AND c.active) OR p.generation=%s ORDER BY document,p.id",
            (generation, generation),
        ).fetchall()


def search_documents(
    query,
    database=None,
    *,
    equipment="M-01",
    at=DEFAULT_DATE,
    mode="semantic",
    generation=None,
    limit=5,
):
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Enter a search question of 1 to 2000 characters.")
    words = set(re.findall(r"\w+", query.casefold())) - STOP_WORDS
    if not words:
        raise ValueError("Enter a meaningful search question.")
    if mode not in MODES or type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid retrieval settings.")
    at = parse_timestamp(at)
    if generation is None:
        state = status(database)
        if not state["ready"]:
            raise RuntimeError(state["message"])
        generation = state["generation"]
    vector = encoder.encode([query])[0] if mode != "lexical" else None
    with connect(database, readonly=True) as db:
        rows = db.execute(
            "SELECT id,document,title,section,text,version,equipment,revision,valid_from::text,valid_to::text, "
            "CASE WHEN %s::vector IS NULL THEN NULL ELSE 1-(embedding <=> %s::vector) END AS similarity "
            "FROM passages WHERE generation=%s AND equipment IN (%s,'general') "
            "AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) ORDER BY similarity DESC NULLS LAST,id",
            (
                json.dumps(vector) if vector else None,
                json.dumps(vector) if vector else None,
                generation,
                equipment,
                at,
                at,
            ),
        ).fetchall()
    lexical = []
    if mode != "semantic":
        word_scores = {
            p["id"]: len(
                words
                & set(
                    re.findall(
                        r"\w+", f"{p['title']} {p['section']} {p['text']}".casefold()
                    )
                )
            )
            for p in rows
        }
        lexical = sorted(
            (p for p in rows if word_scores[p["id"]]),
            key=lambda p: (-word_scores[p["id"]], p["id"]),
        )
    semantic = [
        p
        for p in rows
        if p["similarity"] is not None and p["similarity"] >= MIN_SIMILARITY
    ]
    if mode == "lexical":
        ranked = lexical
    elif mode == "semantic":
        ranked = semantic
    else:
        scores = {}
        # Only semantically eligible passages enter hybrid results. Literal matches improve their rank.
        for ranking in (lexical, semantic):
            for rank, passage in enumerate(ranking, 1):
                scores[passage["id"]] = scores.get(passage["id"], 0) + 1 / (60 + rank)
        ranked = sorted(semantic, key=lambda p: (-scores[p["id"]], p["id"]))
    result, seen = [], set()
    for passage in ranked:
        content = passage["text"].strip().casefold()
        if content not in seen:
            result.append(passage)
            seen.add(content)
        if len(result) == limit:
            break
    return result
