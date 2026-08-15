"""Assessment history.

The photo is kept alongside the report: an estimate nobody can trace back to
the image it came from is not worth much when someone disputes it.
"""

import json
import os
import sqlite3
from pathlib import Path

# Configurable so a deployment can point this at a mounted disk. Render's free
# plan has no persistent storage, so history there lasts until the next restart.
DB_PATH = Path(os.environ.get("DAMAGESCAN_DB")
               or Path(__file__).parent / "assessments.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS assessment (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    reference   TEXT NOT NULL,
    image       TEXT NOT NULL,
    report      TEXT NOT NULL,
    estimate    TEXT NOT NULL,
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def next_reference(conn):
    """Human-quotable claim reference, e.g. DS-2026-0007."""
    from datetime import date
    year = date.today().year
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM assessment WHERE reference LIKE ?",
        (f"DS-{year}-%",),
    ).fetchone()
    return f"DS-{year}-{row['n'] + 1:04d}"


def save(conn, reference, image, report, estimate, model, usage):
    cur = conn.execute(
        "INSERT INTO assessment (reference, image, report, estimate, model,"
        " tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (reference, image, json.dumps(report), json.dumps(estimate), model,
         usage.input_tokens, usage.output_tokens),
    )
    conn.commit()
    return cur.lastrowid


def get(conn, assessment_id):
    row = conn.execute("SELECT * FROM assessment WHERE id = ?",
                       (assessment_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "reference": row["reference"],
        "created_at": row["created_at"], "image": row["image"],
        "report": json.loads(row["report"]),
        "estimate": json.loads(row["estimate"]),
        "model": row["model"],
    }


def recent(conn, limit=40):
    rows = conn.execute(
        "SELECT id, reference, created_at, report, estimate FROM assessment"
        " ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    out = []
    for row in rows:
        report = json.loads(row["report"])
        estimate = json.loads(row["estimate"])
        out.append({
            "id": row["id"],
            "reference": row["reference"],
            "created_at": row["created_at"],
            "summary": report["summary"],
            "findings": len(report["findings"]),
            "severity": _worst(report["findings"]),
            "total_low": estimate["total_low"],
            "total_high": estimate["total_high"],
            "currency": estimate["currency"],
        })
    return out


def _worst(findings):
    for level in ("severe", "moderate", "minor"):
        if any(f["severity"] == level for f in findings):
            return level
    return "none"
