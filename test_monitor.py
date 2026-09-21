import json
import sqlite3
import tempfile
import unittest
import queue
import threading
import urllib.request
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

from monitor import ProbeStore, ThreadingHTTPServer, main, make_handler


class ProbeStoreTest(unittest.TestCase):
    def test_retention_keeps_latest_15_dates_and_does_not_restore_expired_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.jsonl"
            rows = [{"id": str(day), "phase": "response", "time": f"2026-09-{day:02}T00:00:00Z",
                     "requested_model": "model", "response_model": "model"} for day in range(17, 0, -1)]
            probe.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            store = ProbeStore(probe)
            store.scan()
            expected = [f"2026-09-{day:02}.sqlite" for day in range(3, 18)]
            self.assertEqual(sorted(path.name for path in store.archive_dir.glob("*.sqlite")), expected)
            self.assertEqual(len(probe.read_text().splitlines()), 15)
            # A delayed old event must not recreate its deleted archive after restart.
            with probe.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(rows[-1]) + "\n")
            restarted = ProbeStore(probe)
            restarted.scan()
            self.assertEqual(sorted(path.name for path in store.archive_dir.glob("*.sqlite")), expected)
            self.assertEqual(len(probe.read_text().splitlines()), 15)
            self.assertEqual(len(restarted.snapshot()["events"]), 15)
            with closing(sqlite3.connect(probe.with_suffix(".archive-index.sqlite"))) as database:
                self.assertEqual(database.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 15)

    def test_browser_launch_can_wait_for_http_without_blocking_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(ProbeStore(Path(directory) / "probe.jsonl"), Path(__file__).parent / "web"),
            )
            result = queue.Queue()

            def open_browser(url):
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        result.put(response.status)
                except OSError:
                    result.put("HTTP timed out while opening browser")

            with patch("sys.argv", ["monitor.py", "--probe-file", str(Path(directory) / "probe.jsonl")]), patch("monitor.ThreadingHTTPServer", return_value=server), patch("monitor.webbrowser.open", side_effect=open_browser):
                worker = threading.Thread(target=main, daemon=True)
                worker.start()
                try:
                    status = result.get(timeout=3)
                finally:
                    server.shutdown()
                    worker.join(timeout=3)
                self.assertEqual(status, 200)

    def test_daily_archive_uses_beijing_date_and_survives_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.jsonl"
            rows = [
                {"id": "before", "phase": "request", "time": "2026-09-14T15:59:58Z", "requested_model": "wanted"},
                {"id": "before", "phase": "response", "time": "2026-09-14T15:59:59Z", "response_model": "served"},
                {"id": "before", "phase": "response", "time": "2026-09-14T15:59:59Z", "server_model": "header-only"},
                {"id": "another-call", "phase": "response", "time": "2026-09-14T15:59:59Z", "requested_model": "wanted", "response_model": "served"},
                {"id": "equal-call", "phase": "response", "time": "2026-09-14T15:59:59Z", "requested_model": "served", "response_model": "served"},
                {"id": "after", "phase": "response", "time": "2026-09-14T16:00:00Z", "response_model": "served", "input": "PRIVATE"},
            ]
            probe.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            archive = Path(directory) / "probe-daily"
            archive.mkdir()
            with closing(sqlite3.connect(archive / "2026-09-14.sqlite")) as database:
                with database:
                    database.execute("CREATE TABLE events (id TEXT, time TEXT, phase TEXT, data TEXT)")
                    database.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (rows[0]["id"], rows[0]["time"], rows[0]["phase"], json.dumps(rows[0])))
            for _ in range(2):
                store = ProbeStore(probe, max_events=1)
                store.scan()
                self.assertEqual(store.snapshot()["health"]["status"], "ok")
            # Replay also upgrades the previously shipped two-column daily format.
            with closing(sqlite3.connect(archive / "2026-09-14.sqlite")) as database:
                with database:
                    database.execute("ALTER TABLE events DROP COLUMN time")
                    database.execute("ALTER TABLE events DROP COLUMN status")
                    database.execute("ALTER TABLE events DROP COLUMN purpose")
            ProbeStore(probe).scan()
            for day, expected in [
                ("2026-09-14", [
                    ("wanted", "served", "2026-09-14T23:59:58.000+08:00", "different"),
                    ("wanted", "served", "2026-09-14T23:59:59.000+08:00", "different"),
                    ("served", "served", "2026-09-14T23:59:59.000+08:00", "equal"),
                ]),
                ("2026-09-15", [(None, "served", "2026-09-15T00:00:00.000+08:00", "unknown")]),
            ]:
                with closing(sqlite3.connect(store.archive_dir / f"{day}.sqlite")) as database:
                    records = database.execute("SELECT * FROM events ORDER BY rowid").fetchall()
                    columns = [column[1] for column in database.execute("PRAGMA table_info(events)")]
                self.assertEqual(columns, ["requested_model", "response_model", "time", "status", "purpose"])
                self.assertEqual(records, [(*row, "unknown") for row in expected])

    def test_purpose_uses_metadata_and_backfills_delayed_title_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.jsonl"
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as db, db:
                db.execute("CREATE TABLE threads (id TEXT, source TEXT, thread_source TEXT)")
                db.executemany("INSERT INTO threads VALUES (?, ?, ?)", [
                    ("main", "vscode", "user"), ("child", '{"subagent":{"thread_spawn":{}}}', "subagent"),
                ])
            rows = [dict(id=tid, thread_id=tid, turn_id="turn", phase="request",
                         time="2026-09-19T00:00:00Z", requested_model="same-model")
                    for tid in ("main", "child", "title", "unidentified")]
            probe.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            store = ProbeStore(probe, metadata_dir=Path(directory))
            initial = {e["id"]: e["purpose"] for e in store.snapshot()["events"]}
            self.assertEqual(initial, {"main": "main", "child": "subagent", "title": "unknown", "unidentified": "unknown"})
            with closing(sqlite3.connect(Path(directory) / "logs_2.sqlite")) as db, db:
                db.execute("CREATE TABLE logs (thread_id TEXT, target TEXT, feedback_log_body TEXT)")
                db.execute("INSERT INTO logs VALUES (?, ?, ?)", ("title", "codex_core::session::handlers",
                    'Submission { id: "turn", content: [Text { text: "You are a helpful assistant. You will be presented with a user prompt, and your job is to provide a short title for a task PRIVATE'))
            self.assertEqual({e["id"]: e["purpose"] for e in store.snapshot()["events"]}["title"], "title_summary")
            with closing(sqlite3.connect(store.archive_dir / "2026-09-19.sqlite")) as db:
                self.assertEqual(db.execute("SELECT purpose FROM events ORDER BY rowid").fetchall(),
                                 [("main",), ("subagent",), ("title_summary",), ("unknown",)])
                self.assertNotIn("PRIVATE", str(db.execute("SELECT * FROM events").fetchall()))
            with closing(sqlite3.connect(Path(directory) / "logs_2.sqlite")) as db, db:
                db.execute("DELETE FROM logs")
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as db, db:
                db.execute("DELETE FROM threads")
            restarted = ProbeStore(probe, metadata_dir=Path(directory)).snapshot()
            self.assertEqual({e["id"]: e["purpose"] for e in restarted["events"]},
                             {"main": "main", "child": "subagent", "title": "title_summary", "unidentified": "unknown"})

    def test_fork_purpose_preserves_system_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "probe.jsonl"
            rows = [dict(id=tid, thread_id=tid, turn_id="turn", phase="request",
                         time="2026-09-20T00:00:00Z", requested_model="same-model")
                    for tid in ("fork", "title")]
            probe.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            with closing(sqlite3.connect(root / "logs_2.sqlite")) as db, db:
                db.execute("CREATE TABLE logs (thread_id TEXT, target TEXT, feedback_log_body TEXT)")
                db.executemany("INSERT INTO logs VALUES (?, ?, ?)", [
                    (tid, "codex_core::shell_snapshot", 'app_server.request{rpc.method="thread/fork"}:shell_snapshot')
                    for tid in ("fork", "title")])
                db.execute("INSERT INTO logs VALUES (?, ?, ?)", ("title", "codex_core::session::handlers",
                    'Submission { id: "turn", content: [Text { text: "You are in a fork of an existing Codex thread.\\nFill the structured description field with a compact, search-oriented summary'))
            store = ProbeStore(probe, metadata_dir=root)
            self.assertEqual({e["id"]: e["purpose"] for e in store.snapshot()["events"]},
                             {"fork": "fork", "title": "title_summary"})
            with closing(sqlite3.connect(store.archive_dir / "2026-09-20.sqlite")) as db:
                self.assertEqual(db.execute("SELECT purpose FROM events ORDER BY rowid").fetchall(),
                                 [("fork",), ("title_summary",)])

    def test_archive_write_failure_is_reported_and_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.jsonl"
            probe.write_text(json.dumps({"id": "retry", "phase": "request", "time": "2026-09-14T00:00:00Z"}) + "\n", encoding="utf-8")
            store = ProbeStore(probe)
            with patch("monitor.sqlite3.connect", side_effect=sqlite3.OperationalError("disk full")):
                self.assertEqual(store.snapshot()["health"]["status"], "error")
            self.assertEqual(store.snapshot()["health"]["status"], "ok")
            with closing(sqlite3.connect(store.archive_dir / "2026-09-14.sqlite")) as database:
                self.assertEqual(database.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_system_purposes_with_separate_metadata_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            probe = root / "logs" / "probe.jsonl"
            rows = [dict(id=kind, thread_id=kind, turn_id="turn", phase="request",
                         time="2026-09-19T00:00:00Z", requested_model="terra")
                    for kind in ("memory", "suggestions", "suggestion_review", "title_summary")]
            probe.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            with closing(sqlite3.connect(root / "logs_2.sqlite")) as db, db:
                db.execute("CREATE TABLE logs (thread_id TEXT, target TEXT, feedback_log_body TEXT)")
                for kind, prefix in [("memory", "## Memory Writing Agent: Phase 2 (Consolidation)"),
                                     ("suggestions", "# Overview\\n\\nGenerate 0 to 3 hyperpersonalized suggestions for what this user can do with Codex in this local project:"),
                                     ("suggestion_review", "You are an expert at upholding safety and compliance standards for Codex ambient suggestions."),
                                     ("title_summary", "You are in a fork of an existing Codex thread.\\nFill the structured description field with a compact, search-oriented summary")]:
                    db.execute("INSERT INTO logs VALUES (?, ?, ?)", (kind, "codex_core::session::handlers",
                        'Submission { id: "turn", content: [Text { text: "' + prefix))
            store = ProbeStore(probe, metadata_dir=root)
            self.assertEqual({e["id"]: e["purpose"] for e in store.snapshot()["events"]},
                             {"memory": "memory", "suggestions": "suggestions", "suggestion_review": "suggestion_review", "title_summary": "title_summary"})
            with closing(sqlite3.connect(store.archive_dir / "2026-09-19.sqlite")) as db:
                self.assertEqual(db.execute("SELECT purpose FROM events ORDER BY rowid").fetchall(),
                                 [("memory",), ("suggestions",), ("suggestion_review",), ("title_summary",)])

    def test_merges_response_and_derives_mismatch_and_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.jsonl"
            rows = [
                {
                    "id": "attempt-1",
                    "phase": "request",
                    "time": 1_700_000_000,
                    "thread_id": "thread-1",
                    "requested_model": "wanted",
                },
                {
                    "id": "attempt-1",
                    "phase": "response",
                    "time": 1_700_000_001,
                    "requested_model": None,
                    "response_model": "served",
                    "server_model": "header-model",
                    "transport": "responses",
                },
                {
                    "id": "attempt-2",
                    "phase": "request",
                    "time": "2023-11-14T22:13:22Z",
                    "requested_model": "wanted",
                },
            ]
            probe.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            result = ProbeStore(probe).snapshot()

            self.assertEqual(len(result["events"]), 2)
            unknown, merged = result["events"]
            self.assertEqual(merged["time"], "2023-11-14T22:13:21.000Z")
            self.assertEqual(merged["status"], "different")
            self.assertEqual(merged["source"], "response.model")
            self.assertEqual(unknown["status"], "unknown")
            self.assertEqual(unknown["source"], "none")
            self.assertEqual(result["health"]["status"], "ok")

    def test_waits_for_partial_line_and_skips_malformed_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.jsonl"
            store = ProbeStore(probe)
            self.assertEqual(store.snapshot()["health"]["status"], "waiting")

            probe.write_text("{bad json}\n", encoding="utf-8")
            invalid = store.snapshot()
            self.assertEqual(invalid["events"], [])
            self.assertEqual(invalid["health"]["status"], "error")

            row = json.dumps(
                {
                    "id": "partial",
                    "phase": "response",
                    "time": 1_700_000_000,
                    "server_model": "served",
                }
            )
            probe.write_text(row[:20], encoding="utf-8")
            self.assertEqual(store.snapshot()["events"], [])

            with probe.open("a", encoding="utf-8") as output:
                output.write(row[20:] + "\n{bad json}\n")
            result = store.snapshot()
            self.assertEqual([event["id"] for event in result["events"]], ["partial"])
            self.assertEqual(result["events"][0]["source"], "openai-model")

            probe.write_text(
                json.dumps(
                    {"id": "new", "phase": "request", "time": 1_700_000_001}
                )
                + "\n",
                encoding="utf-8",
            )
            result = store.snapshot()
            self.assertEqual([event["id"] for event in result["events"]], ["new", "partial"])


if __name__ == "__main__":
    unittest.main()
