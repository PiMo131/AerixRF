"""Field-test sessions: self-describing capture directories + Markdown summaries.

    from aerix_rf.session import Session, build_summary, write_summary

See ``store.py`` for the directory layout / session.json and ``report.py`` for
the detections.jsonl / decode.jsonl record fields the summary reads.
"""

from .report import build_summary, write_summary
from .store import Session, SessionIntegrityError, TEST_KEYS

__all__ = ["Session", "SessionIntegrityError", "TEST_KEYS", "build_summary", "write_summary"]
