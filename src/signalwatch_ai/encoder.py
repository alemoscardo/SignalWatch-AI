"""Explicit model download; encoding itself is CPU-only and local."""

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"


def model_path():
    return Path(os.getenv("SIGNALWATCH_ENCODER_PATH", "data/local/encoder")).resolve()


def setup():
    from sentence_transformers import SentenceTransformer

    path = model_path()
    if path.exists():
        raise RuntimeError(
            "Encoder directory already exists. Keep it or choose a new path for an upgrade."
        )
    model = SentenceTransformer(
        MODEL, revision=REVISION, device="cpu", trust_remote_code=False
    )
    model.save(str(path), safe_serialization=True)
    (path / "identity.json").write_text(
        json.dumps({"model": MODEL, "revision": REVISION}), encoding="utf-8"
    )
    return identity()


def identity():
    path = model_path()
    if not (path / "identity.json").is_file():
        raise RuntimeError(
            "Local encoder is missing. Run signalwatch-db encoder-setup."
        )
    files = tuple(
        (
            str(file),
            file.stat().st_size,
            file.stat().st_mtime_ns,
            file.stat().st_ctime_ns,
        )
        for file in sorted(path.rglob("*"))
        if file.is_file()
    )
    return _identity(str(path), files)


@lru_cache(maxsize=1)
def _identity(directory, files):
    path = Path(directory)
    digest = hashlib.sha256()
    for name, *_ in files:
        file = Path(name)
        digest.update(file.relative_to(path).as_posix().encode())
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return {
        **json.loads((path / "identity.json").read_text(encoding="utf-8")),
        "sha256": digest.hexdigest(),
        "dimensions": 384,
    }


@lru_cache(maxsize=1)
def load():
    from sentence_transformers import SentenceTransformer

    identity()
    return SentenceTransformer(
        str(model_path()), device="cpu", local_files_only=True, trust_remote_code=False
    )


def encode(texts):
    model = load()
    for text in texts:
        if not text.strip() or len(model.tokenizer.encode(text)) > model.max_seq_length:
            raise ValueError(
                "Text is empty or exceeds the encoder input length; shorten or split it."
            )
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    if vectors.shape != (len(texts), 384):
        raise RuntimeError(
            "Encoder dimensions do not match the database; rebuild with a compatible model."
        )
    return vectors.tolist()
