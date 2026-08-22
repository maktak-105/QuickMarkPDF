"""実行結果の履歴を蓄積するSQLite DB。

qa/baseline.json・behaviors.json等のJSONファイルは「直近1回分」のスナップショットを
上書きするだけで、実行するたびに前回の結果が消えてしまう。ユーザー指示により、
extract_python.py / extract_cpp.py / check_behaviors_python.py / check_behaviors_cpp.py の
各スクリプトが実行されるたびに、その結果を qa/qa_history.db (SQLite) へ追記し、
推移を後から追えるようにする。JSONファイル出力(dashboard.pyの入力)は従来通り維持し、
DBはその横に「毎回消えない実行履歴」として並行して蓄積する。

qa_history.db はテスト実行のたびに増える生成物のため .gitignore 対象(qa/dashboard.html
等の他の生成物と同じ扱い)。

Run: 他のqa/*.pyスクリプトから import して record_run() を呼ぶだけ。単体実行はしない。
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "qa_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL,      -- 'baseline' (extract_*.py) or 'behaviors' (check_behaviors_*.py)
    source TEXT NOT NULL,    -- 'python' or 'cpp'
    total INTEGER NOT NULL,
    passed INTEGER           -- baseline系はNULL(合否の概念が無い計測のため)
);

CREATE TABLE IF NOT EXISTS run_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    name TEXT NOT NULL,      -- チェック名 または パーツ/アクションのpath
    category TEXT NOT NULL,  -- 'part' / 'action' / 'behavior'
    pass INTEGER,            -- 1/0/NULL(baseline系の計測項目はNULL)
    detail TEXT NOT NULL     -- 実測値・before/after/behavior文などのJSON
);

CREATE INDEX IF NOT EXISTS idx_run_items_run_id ON run_items(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_kind_source ON runs(kind, source);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def record_baseline_run(source: str, parts: list, actions: list):
    """extract_python.py / extract_cpp.py の結果(パーツ・アクションの実測)を1件記録する。"""
    conn = _connect()
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        total = len(parts) + len(actions)
        cur = conn.execute(
            "INSERT INTO runs (timestamp, kind, source, total, passed) VALUES (?, 'baseline', ?, ?, NULL)",
            (timestamp, source, total),
        )
        run_id = cur.lastrowid
        rows = [(run_id, p.get("path", ""), "part", None, json.dumps(p, ensure_ascii=False)) for p in parts]
        rows += [(run_id, a.get("path", ""), "action", None, json.dumps(a, ensure_ascii=False)) for a in actions]
        conn.executemany(
            "INSERT INTO run_items (run_id, name, category, pass, detail) VALUES (?, ?, ?, ?, ?)", rows
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def record_behaviors_run(source: str, results: list):
    """check_behaviors_python.py / check_behaviors_cpp.py の結果(PASS/FAILの一覧)を1件記録する。"""
    conn = _connect()
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        passed = sum(1 for r in results if r.get("pass"))
        cur = conn.execute(
            "INSERT INTO runs (timestamp, kind, source, total, passed) VALUES (?, 'behaviors', ?, ?, ?)",
            (timestamp, source, len(results), passed),
        )
        run_id = cur.lastrowid
        rows = [
            (run_id, r["name"], "behavior", 1 if r.get("pass") else 0, json.dumps(r, ensure_ascii=False))
            for r in results
        ]
        conn.executemany(
            "INSERT INTO run_items (run_id, name, category, pass, detail) VALUES (?, ?, ?, ?, ?)", rows
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def recent_runs(limit: int = 20):
    """直近の実行履歴をdashboard.py表示用に返す(新しい順)。"""
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT timestamp, kind, source, total, passed FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [
            {"timestamp": row[0], "kind": row[1], "source": row[2], "total": row[3], "passed": row[4]}
            for row in cur.fetchall()
        ]
    finally:
        conn.close()
