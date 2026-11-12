from contextlib import contextmanager
import json
import sqlite3
from uuid import uuid4

from settings import DATA, DATABASE, DOCUMENTS


@contextmanager
def connect():
    db = sqlite3.connect(DATABASE, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    DOCUMENTS.mkdir(exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','processing','completed','failed')),
                published INTEGER NOT NULL DEFAULT 0,
                attempt TEXT,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chunks (
                doc_id TEXT NOT NULL,
                page INTEGER NOT NULL,
                text TEXT NOT NULL,
                images TEXT NOT NULL,
                model TEXT NOT NULL,
                vector BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chunk_doc ON chunks(doc_id);
        """)


def add_document(doc_id, name):
    with connect() as db:
        db.execute("INSERT INTO documents(id, name) VALUES (?, ?)", (doc_id, name))


def documents():
    with connect() as db:
        return [dict(row) for row in db.execute("""
            SELECT id, name, status, error, updated_at
            FROM documents ORDER BY rowid DESC
        """)]


def pending_dispatch():
    with connect() as db:
        return db.execute("""
            SELECT id FROM documents WHERE published = 0 AND status = 'pending'
            ORDER BY rowid LIMIT 1
        """).fetchone()


def dispatched(doc_id):
    with connect() as db:
        db.execute("UPDATE documents SET published = 1 WHERE id = ?", (doc_id,))


def claim(doc_id):
    attempt = uuid4().hex
    with connect() as db:
        result = db.execute("""
            UPDATE documents SET status = 'processing', attempt = ?, published = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('pending', 'processing')
        """, (attempt, doc_id))
        return attempt if result.rowcount else None


def finish(doc_id, attempt, chunks=(), error=None):
    status = "failed" if error else "completed"
    with connect() as db:
        result = db.execute("""
            UPDATE documents SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND attempt = ? AND status = 'processing'
        """, (status, error, doc_id, attempt))
        if not result.rowcount:
            return False
        if not error:
            db.executemany("""
                INSERT INTO chunks(doc_id, page, text, images, model, vector)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                (doc_id, page, body, json.dumps(images), model, vector)
                for page, body, images, model, vector in chunks
            ))
        return True


def indexed_chunks(model):
    with connect() as db:
        return db.execute("""
            SELECT d.id, d.name, d.attempt, c.page, c.text, c.images, c.vector
            FROM chunks AS c JOIN documents AS d ON d.id = c.doc_id
            WHERE d.status = 'completed' AND c.model = ?
        """, (model,)).fetchall()


def document_output(doc_id):
    with connect() as db:
        row = db.execute("""
            SELECT attempt FROM documents WHERE id = ? AND status = 'completed'
        """, (doc_id,)).fetchone()
    return DOCUMENTS / doc_id / row["attempt"] if row else None
