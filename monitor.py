#!/usr/bin/env python3
"""Small local HTTP viewer for model-probe JSONL events."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import threading
import webbrowser
from collections import OrderedDict
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


MAX_EVENTS = 1000
MAX_LINE_BYTES = 8192
MAX_STRING_LENGTH = 256
RETAIN_DAYS = 15
ARCHIVE_TIMEZONE = timezone(timedelta(hours=8))
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/logo.png": ("logo.png", "image/png"),
}
STRING_FIELDS = (
    "thread_id",
    "turn_id",
    "requested_model",
    "response_model",
    "server_model",
    "transport",
)


def _iso_time(value: object) -> str | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                return None
            moment = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str) and len(value) <= MAX_STRING_LENGTH:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            moment = moment.astimezone(timezone.utc)
        else:
            return None
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_event(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    event_id = raw.get("id")
    phase = raw.get("phase")
    timestamp = _iso_time(raw.get("time"))
    if (
        not isinstance(event_id, str)
        or not event_id
        or len(event_id) > MAX_STRING_LENGTH
        or phase not in ("request", "response")
        or timestamp is None
    ):
        return None

    event: dict[str, object] = {"id": event_id, "time": timestamp, "phase": phase}
    for field in STRING_FIELDS:
        value = raw.get(field)
        if value is not None and (
            not isinstance(value, str) or len(value) > MAX_STRING_LENGTH
        ):
            return None
        if field in raw:
            event[field] = value
    if "warmup" in raw:
        if not isinstance(raw["warmup"], bool):
            return None
        event["warmup"] = raw["warmup"]
    return event


@contextmanager
def _locked_probe(path: Path):
    with path.open("r+b") as stream:
        if os.name == "nt":
            import msvcrt
            # This byte overlaps Rust File::lock's whole-file lock.
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield stream
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class ProbeStore:
    def __init__(self, probe_file: Path, max_events: int = MAX_EVENTS, metadata_dir: Path | None = None) -> None:
        self.probe_file = probe_file
        self.max_events = max_events
        self.metadata_dir = (metadata_dir or Path.home() / ".codex").resolve()
        self.archive_dir = probe_file.parent / f"{probe_file.stem}-daily"
        self._oldest_day = ""
        self._needs_compact = False
        index = probe_file.with_suffix(".archive-index.sqlite")
        if index.exists():
            with closing(sqlite3.connect(index)) as database, database:
                database.execute("CREATE TABLE IF NOT EXISTS retention (oldest_day TEXT)")
                row = database.execute("SELECT oldest_day FROM retention").fetchone()
                if row:
                    self._oldest_day = row[0]
        self._events: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._offset = 0
        self._identity: tuple[int, int] | None = None
        self._partial = b""
        self._discard_line = False
        self._marker = b""
        self._invalid = False
        self._valid = False
        self._lock = threading.Lock()
        self._purposes = OrderedDict()
        self._health: dict[str, object] = {
            "source": "probe",
            "status": "waiting",
            "error": None,
            "last_scan": None,
            "probe": str(probe_file),
            "archive": str(self.archive_dir),
        }

    def _reset_tail(self, identity: tuple[int, int]) -> None:
        self._offset = 0
        self._identity = identity
        self._partial = b""
        self._discard_line = False
        self._marker = b""
        self._invalid = False
        self._valid = False

    def _purpose(self, event: dict[str, object]) -> str:
        if event.get("warmup"):
            return "warmup"
        thread_id, turn_id = event.get("thread_id"), event.get("turn_id")
        if not thread_id:
            return "unknown"
        key = (thread_id, turn_id)
        if key in self._purposes:
            return self._purposes[key]
        purpose = "unknown"
        try:
            state = self.metadata_dir / "state_5.sqlite"
            if state.exists():
                with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True)) as database:
                    row = database.execute("SELECT source, thread_source FROM threads WHERE id = ?", (thread_id,)).fetchone()
                if row:
                    source, thread_source = row
                    if thread_source == "subagent" or '"thread_spawn"' in source:
                        purpose = "subagent"
                    elif '"subagent"' in source:
                        purpose = "background"
                    elif thread_source == "user":
                        purpose = "main"
            logs = self.metadata_dir / "logs_2.sqlite"
            if turn_id and logs.exists():
                with closing(sqlite3.connect(logs.as_uri() + "?mode=ro", uri=True)) as database:
                    # Match system submission prefixes, never the model name.
                    found = database.execute(
                        "SELECT CASE WHEN instr(feedback_log_body, ?) > 0 OR instr(feedback_log_body, ?) > 0 THEN 'title_summary' "
                        "WHEN instr(feedback_log_body, ?) > 0 THEN 'memory' "
                        "WHEN instr(feedback_log_body, ?) > 0 THEN 'suggestions' "
                        "WHEN instr(feedback_log_body, ?) > 0 THEN 'suggestion_review' END "
                        "FROM logs WHERE thread_id = ? AND target = 'codex_core::session::handlers' "
                        "AND instr(feedback_log_body, ?) > 0 LIMIT 1",
                        ('content: [Text { text: "You are a helpful assistant. You will be presented with a user prompt, and your job is to provide a short title for a task',
                         'content: [Text { text: "You are in a fork of an existing Codex thread.\\nFill the structured description field with a compact, search-oriented summary',
                         'content: [Text { text: "## Memory Writing Agent: Phase 2 (Consolidation)',
                         'content: [Text { text: "# Overview\\n\\nGenerate 0 to 3 hyperpersonalized suggestions for what this user can do with Codex in this local project:',
                         'content: [Text { text: "You are an expert at upholding safety and compliance standards for Codex ambient suggestions.',
                         thread_id, f'Submission {{ id: "{turn_id}"'),
                    ).fetchone()
                    if not (found and found[0]) and purpose in ("unknown", "main"):
                        fork = database.execute(
                            "SELECT 1 FROM logs WHERE thread_id = ? "
                            "AND target = 'codex_core::shell_snapshot' "
                            "AND feedback_log_body LIKE 'app_server.request{%' "
                            "AND instr(feedback_log_body, 'rpc.method=\"thread/fork\"') > 0 LIMIT 1",
                            (thread_id,),
                        ).fetchone()
                        if fork:
                            purpose = "fork"
                if found and found[0]:
                    purpose = found[0]
        except sqlite3.Error:
            # Missing/locked source metadata must not prevent model-call archiving.
            return "unknown"
        if purpose != "unknown":
            self._purposes[key] = purpose
            if len(self._purposes) > MAX_EVENTS:
                self._purposes.popitem(last=False)
        return purpose

    def _consume(self, chunk: bytes) -> None:
        archive_rows = {}
        data = self._partial + chunk
        self._partial = b""
        for line in data.splitlines(keepends=True):
            complete = line.endswith((b"\n", b"\r"))
            payload = line.rstrip(b"\r\n") if complete else line
            if self._discard_line:
                if complete:
                    self._discard_line = False
                continue
            if not complete:
                if len(payload) > MAX_LINE_BYTES:
                    self._discard_line = True
                else:
                    self._partial = payload
                continue
            if len(payload) > MAX_LINE_BYTES:
                continue
            try:
                event = _validate_event(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._invalid = True
                continue
            if event is None:
                self._invalid = True
                continue
            self._valid = True
            event["purpose"] = self._purpose(event)
            day = datetime.fromisoformat(event["time"]).astimezone(ARCHIVE_TIMEZONE).date().isoformat()
            if day < self._oldest_day:
                self._needs_compact = True
                continue
            archive_rows.setdefault(day, []).append(event)
            event_id = event["id"]
            existing = self._events.get(event_id, {})
            existing.update((key, value) for key, value in event.items() if value is not None)
            self._events[event_id] = existing
            self._events.move_to_end(event_id)
            while len(self._events) > self.max_events:
                self._events.popitem(last=False)
        self._archive(archive_rows)

    def _archive(self, archive_rows: dict) -> None:
        if archive_rows:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
        for day, rows in archive_rows.items():
            if day < self._oldest_day:
                continue
            # Keep replay bookkeeping outside the daily files.
            database = sqlite3.connect(self.probe_file.with_suffix(".archive-index.sqlite"))
            try:
                database.execute("ATTACH DATABASE ? AS daily", (str(self.archive_dir / f"{day}.sqlite"),))
                with database:
                    database.execute("BEGIN IMMEDIATE")
                    database.execute(
                        "CREATE TABLE IF NOT EXISTS calls "
                        "(day TEXT, call_id TEXT, row_id INTEGER, response_seen INTEGER, PRIMARY KEY(day, call_id))"
                    )
                    columns = [column[1] for column in database.execute("PRAGMA daily.table_info(events)")]
                    if "data" in columns:
                        rows = [json.loads(row[0]) for row in database.execute("SELECT data FROM daily.events ORDER BY rowid")] + rows
                        database.execute("DROP TABLE daily.events")
                        database.execute("DELETE FROM calls WHERE day = ?", (day,))
                    database.execute("CREATE TABLE IF NOT EXISTS daily.events (requested_model TEXT, response_model TEXT)")
                    columns = [column[1] for column in database.execute("PRAGMA daily.table_info(events)")]
                    for column in ("time", "status", "purpose"):
                        if column not in columns:
                            database.execute(f"ALTER TABLE daily.events ADD COLUMN {column} TEXT")
                    for event in rows:
                        purpose = event.get("purpose") or self._purpose(event)
                        timestamp = datetime.fromisoformat(event["time"]).astimezone(ARCHIVE_TIMEZONE).isoformat(timespec="milliseconds")
                        match = database.execute(
                            "SELECT calls.row_id, response_seen, events.purpose FROM calls "
                            "JOIN daily.events ON events.rowid = calls.row_id WHERE day = ? AND call_id = ?",
                            (day, event["id"]),
                        ).fetchone()
                        models = (event.get("requested_model"), event.get("response_model") or event.get("server_model"))
                        if match:
                            if purpose == "unknown" and match[2]:
                                purpose = match[2]
                            if event["id"] in self._events:
                                self._events[event["id"]]["purpose"] = purpose
                            if match[1] and not event.get("response_model"):
                                models = (models[0], None)
                            database.execute(
                                "UPDATE daily.events SET requested_model = COALESCE(?, requested_model), "
                                "response_model = COALESCE(?, response_model), "
                                "time = MIN(COALESCE(time, ?), ?), "
                                "purpose = COALESCE(NULLIF(?, 'unknown'), purpose, 'unknown') WHERE rowid = ?",
                                (*models, timestamp, timestamp, purpose, match[0]),
                            )
                            if event.get("response_model"):
                                database.execute("UPDATE calls SET response_seen = 1 WHERE day = ? AND call_id = ?", (day, event["id"]))
                        else:
                            cursor = database.execute(
                                "INSERT INTO daily.events (requested_model, response_model, time, purpose) VALUES (?, ?, ?, ?)",
                                (*models, timestamp, purpose),
                            )
                            database.execute("INSERT INTO calls VALUES (?, ?, ?, ?)", (day, event["id"], cursor.lastrowid, bool(event.get("response_model"))))
                    database.execute(
                        "UPDATE daily.events SET status = CASE "
                        "WHEN COALESCE(requested_model, '') = '' OR COALESCE(response_model, '') = '' THEN 'unknown' "
                        "WHEN requested_model = response_model THEN 'equal' ELSE 'different' END"
                    )
            finally:
                database.close()

    def _prune(self) -> None:
        files = sorted(path for path in self.archive_dir.glob("*.sqlite")
                       if len(path.stem) == 10 and _iso_time(path.stem))
        if len(files) > RETAIN_DAYS:
            self._oldest_day = max(self._oldest_day, files[-RETAIN_DAYS].stem)
            with closing(sqlite3.connect(self.probe_file.with_suffix(".archive-index.sqlite"))) as database, database:
                database.execute("CREATE TABLE IF NOT EXISTS retention (oldest_day TEXT)")
                database.execute("DELETE FROM retention")
                database.execute("INSERT INTO retention VALUES (?)", (self._oldest_day,))
            self._needs_compact = True
        expired = [path for path in files if path.stem < self._oldest_day]
        if expired:
            with closing(sqlite3.connect(self.probe_file.with_suffix(".archive-index.sqlite"))) as database, database:
                database.execute("DELETE FROM calls WHERE day < ?", (self._oldest_day,))
            for path in expired:
                path.unlink()
        for key, event in list(self._events.items()):
            if datetime.fromisoformat(event["time"]).astimezone(ARCHIVE_TIMEZONE).date().isoformat() < self._oldest_day:
                del self._events[key]
        if self._needs_compact and self.probe_file.exists():
            with _locked_probe(self.probe_file) as stream:
                retained = []
                for line in stream:
                    try:
                        event = _validate_event(json.loads(line))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        event = None
                    if event and datetime.fromisoformat(event["time"]).astimezone(ARCHIVE_TIMEZONE).date().isoformat() < self._oldest_day:
                        continue
                    retained.append(line)
                stream.seek(0)
                stream.writelines(retained)
                stream.truncate()
                stream.flush()
            self._offset = 0
            self._partial = b""
            self._discard_line = False
            self._marker = b""
            self._needs_compact = False

    def scan(self) -> None:
        scanned_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        with self._lock:
            try:
                stat = self.probe_file.stat()
            except FileNotFoundError:
                self._identity = None
                self._offset = 0
                self._partial = b""
                self._discard_line = False
                self._marker = b""
                self._invalid = False
                self._valid = False
                self._health.update(
                    status="waiting", error=None, last_scan=scanned_at
                )
                return
            except OSError as error:
                self._health.update(
                    status="error", error=str(error), last_scan=scanned_at
                )
                return

            identity = (stat.st_dev, stat.st_ino)
            if identity != self._identity or stat.st_size < self._offset:
                self._reset_tail(identity)
            try:
                with self.probe_file.open("rb") as probe:
                    if self._marker:
                        probe.seek(self._offset - len(self._marker))
                        if probe.read(len(self._marker)) != self._marker:
                            self._reset_tail(identity)
                    probe.seek(self._offset)
                    remaining = stat.st_size - self._offset
                    while remaining > 0 and (chunk := probe.read(min(65536, remaining))):
                        self._offset += len(chunk)
                        remaining -= len(chunk)
                        self._consume(chunk)
                    marker_length = min(self._offset, 64)
                    probe.seek(self._offset - marker_length)
                    self._marker = probe.read(marker_length)
                # Local metadata can arrive after the probe line; retry recent unknown calls.
                resolved = {}
                for event in self._events.values():
                    if event.get("purpose") == "unknown":
                        purpose = self._purpose(event)
                        if purpose != "unknown":
                            event["purpose"] = purpose
                            day = datetime.fromisoformat(event["time"]).astimezone(ARCHIVE_TIMEZONE).date().isoformat()
                            resolved.setdefault(day, []).append(event)
                self._archive(resolved)
                self._prune()
            except (OSError, sqlite3.Error) as error:
                self._reset_tail(identity)
                self._health.update(
                    status="error", error=str(error), last_scan=scanned_at
                )
                return
            if self._valid:
                self._health.update(status="ok", error=None, last_scan=scanned_at)
            elif self._invalid:
                self._health.update(
                    status="error",
                    error="probe contains no valid events",
                    last_scan=scanned_at,
                )
            else:
                self._health.update(status="waiting", error=None, last_scan=scanned_at)

    def snapshot(self) -> dict[str, object]:
        self.scan()
        with self._lock:
            events = []
            for stored in reversed(self._events.values()):
                event = {
                    "id": stored["id"],
                    "time": stored["time"],
                    "thread_id": stored.get("thread_id"),
                    "turn_id": stored.get("turn_id"),
                    "requested_model": stored.get("requested_model"),
                    "response_model": stored.get("response_model"),
                    "server_model": stored.get("server_model"),
                    "transport": stored.get("transport"),
                    "warmup": stored.get("warmup", False),
                    "purpose": stored.get("purpose", "unknown"),
                }
                observed = event["response_model"] or event["server_model"]
                requested = event["requested_model"]
                event["source"] = (
                    "response.model"
                    if event["response_model"]
                    else "openai-model"
                    if event["server_model"]
                    else "none"
                )
                event["status"] = (
                    "unknown"
                    if not requested or not observed
                    else "equal"
                    if requested == observed
                    else "different"
                )
                events.append(event)
            return {"events": events, "health": dict(self._health)}


def make_handler(store: ProbeStore, web_root: Path) -> type[BaseHTTPRequestHandler]:
    class MonitorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            allowed_hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if (
                self.headers.get("Host", "").lower() not in allowed_hosts
                or self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
            ):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == "/api/events":
                body = json.dumps(store.snapshot(), separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
            elif path in STATIC_FILES:
                filename, content_type = STATIC_FILES[path]
                try:
                    body = (web_root / filename).read_bytes()
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_error(404)
                return
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return MonitorHandler


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--probe-file", type=Path, default=Path(__file__).resolve().parent / "logs" / "model-probe.jsonl"
    )
    args = parser.parse_args()

    store = ProbeStore(args.probe_file)
    web_root = Path(__file__).resolve().parent / "web"
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(store, web_root)
    )
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Codex model monitor: {url}")
    print(f"Probe: {args.probe_file}")
    if not args.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    stop_scanning = threading.Event()

    def archive_in_background():
        while not stop_scanning.is_set():
            store.scan()
            stop_scanning.wait(2)

    scanner = threading.Thread(target=archive_in_background, daemon=True)
    scanner.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_scanning.set()
        scanner.join()
        server.server_close()


if __name__ == "__main__":
    main()
