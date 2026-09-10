"""Small offline fixtures shared by the test suite."""

from pathlib import Path
from tempfile import TemporaryDirectory

from signalwatch_ai.telemetry import seed_demo


def demo_database(test):
    folder = test.enterContext(TemporaryDirectory())
    path = Path(folder) / "demo.sqlite3"
    seed_demo(path)
    return path


def reply(message, reason="stop"):
    return {
        "model": "test:free",
        "usage": {"total_tokens": 10},
        "choices": [{"message": message, "finish_reason": reason}],
    }
