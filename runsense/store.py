"""Small durable store. No OAuth tokens, frames or raw provider responses are stored."""
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str = "data/runsense.sqlite3"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS actions (namespace TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(namespace,id))")

    def connect(self):
        return sqlite3.connect(self.path)

    def save_run(self, payload: dict):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", (payload["run_id"], json.dumps(payload)))

    def get_run(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def upsert_action(self, namespace: str, action_id: str, payload: dict) -> dict:
        with self.connect() as db:
            existed = db.execute("SELECT 1 FROM actions WHERE namespace=? AND id=?", (namespace, action_id)).fetchone()
            db.execute("INSERT OR REPLACE INTO actions VALUES (?,?,?)", (namespace, action_id, json.dumps(payload)))
        return {"id": action_id, "status": "updated" if existed else "created", **payload}

    def get_action(self, namespace: str, action_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM actions WHERE namespace=? AND id=?", (namespace, action_id)).fetchone()
        return json.loads(row[0]) if row else None

    def count_actions(self, namespace: str) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM actions WHERE namespace=?", (namespace,)).fetchone()[0]

