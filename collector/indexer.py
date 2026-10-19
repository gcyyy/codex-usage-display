"""Transactional, bounded JSONL tailer. Persists only metadata and token evidence.

Content is projected before storage: never store prompts, responses or tool bodies.
The derived requests are rebuilt only for changed sessions and their fork descendants.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from .tokens import FIELDS, delta, normalize
from .timeutil import parse_time, utcnow
from .watch import DirectorySignals

PARSER_VERSION = "6"
# Exact official tags reviewed in docs/log-version-evidence.json, never prefix-match unknown releases.
SUPPORTED_VERSIONS = {"0.153.0-alpha.5", "0.153.4", "0.154.0-alpha.6.2", "0.155.0-alpha.9.2",
                      "0.155.0-alpha.16.3", "0.158.0-alpha.2.1", "0.160.1", "0.162.0-alpha.2",
                      "0.162.0-alpha.17.2", "0.163.0-alpha.10.2", "synthetic-v1"}
META_KEYS = ("id", "timestamp", "originator", "cli_version", "source", "parent_thread_id",
             "forked_from_id", "fork_timestamp", "usage_includes_subagents")


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def media_modality(messages):
    """Read type labels only. Ambiguous image/output/audio types remain unsupported."""
    result = "text"
    for message in messages:
        content = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content, list):
            continue
        for part in content:
            kind = part.get("type") if isinstance(part, dict) else None
            if kind == "input_image":
                if result == "text":
                    result = "image-input"
            elif kind in {"image", "input_audio", "audio", "output_audio", "output_image", "input_video", "video"}:
                result = "unsupported"
    return result


def merge_modality(current, event):
    incoming = event["modality"]
    if event.get("replacement"):
        return incoming
    if current not in ("text", "image-input") or incoming not in ("text", "image-input"):
        return "unsupported"
    return "image-input" if "image-input" in (current, incoming) else "text"


def project(event):
    kind, payload = event.get("type"), event.get("payload")
    if not isinstance(payload, dict):
        return None
    if kind == "session_meta":
        data = {k: payload[k] for k in META_KEYS if k in payload}
        # Source objects contain only origin/parent labels; whitelist nested fields too.
        if isinstance(data.get("source"), dict):
            sub = data["source"].get("subagent", {})
            if not isinstance(sub, dict):
                sub = {}
            spawn = sub.get("spawn", {})
            data["source"] = {"subagent": {k: sub[k] for k in ("other",) if k in sub}}
            if isinstance(spawn, dict):
                data["source"]["subagent"]["spawn"] = {k: spawn[k] for k in ("parent_thread_id", "depth") if k in spawn}
    elif kind == "token_usage_record":
        data = {k: payload.get(k) for k in ("thread_id", "turn_id", "response_id")}
        for key in ("usage", "thread_token_usage"):
            raw = payload.get(key)
            data[key] = {k: raw[k] for k in FIELDS.values() if k in raw} if isinstance(raw, dict) else None
        kind = "response_usage"
    elif kind == "turn_context":
        data = {k: payload[k] for k in ("model", "turn_id") if k in payload}
    elif kind == "event_msg" and payload.get("type") == "token_count":
        info = payload.get("info")
        if info is None:  # rate-limit-only notifications contain no new usage
            return None
        if not isinstance(info, dict):
            raise ValueError("Invalid usage info")
        data = {k: payload[k] for k in ("request_id", "response_id", "model", "actual_model", "turn_id", "sequence_id", "usage_reset", "modality") if k in payload}
        for key in ("total_token_usage", "last_token_usage"):
            raw = info.get(key)
            data[key] = {k: raw[k] for k in FIELDS.values() if k in raw} if isinstance(raw, dict) else None
        kind = "usage"
    elif kind in ("response_msg", "response_item") and payload.get("type") == "message":
        modality = media_modality([payload])
        if modality == "text":
            return None
        # Store only a modality flag, never image URLs, data, text or audio bodies.
        kind, data = "modality", {"modality": modality}
    elif kind == "compacted" and isinstance(payload.get("replacement_history"), list):
        # Only an explicit replacement history can prove that media left the active context.
        kind, data = "modality", {"modality": media_modality(payload["replacement_history"]), "replacement": True}
    else:
        return None
    for key in ("id", "thread_id", "originator", "cli_version", "parent_thread_id", "forked_from_id", "fork_timestamp", "model", "actual_model", "turn_id", "request_id", "response_id", "modality"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            raise ValueError("Invalid metadata field")
    timestamp = parse_time(event.get("timestamp")).isoformat()
    return kind, timestamp, data


class Indexer:
    def __init__(self, database, homes):
        self.homes = list(dict.fromkeys(str(Path(p).expanduser().resolve()) for p in homes))
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self.indexing = True
        self.unavailable = False
        self.last_scan = None
        self.discovery_errors = []
        self.last_discovery = 0
        self.paths = []
        self.cursor = 0
        self.dirty = set()
        self.bytes_read = 0
        self.signals = DirectorySignals()
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, offset INTEGER NOT NULL,
            size INTEGER NOT NULL, mtime INTEGER NOT NULL, signature TEXT, head TEXT, tail TEXT,
            sid TEXT, errors TEXT NOT NULL, pending INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS evidence (path TEXT, pos INTEGER, sid TEXT, kind TEXT,
            ts TEXT, data TEXT, fingerprint TEXT, PRIMARY KEY(path,pos));
          CREATE INDEX IF NOT EXISTS evidence_sid ON evidence(sid);
          CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, meta TEXT, scope TEXT,
            parent TEXT, fork TEXT, errors TEXT);
          CREATE TABLE IF NOT EXISTS requests (identity TEXT PRIMARY KEY, sid TEXT, ts TEXT,
            model TEXT, data TEXT);
          CREATE INDEX IF NOT EXISTS request_day ON requests(ts);
          CREATE TABLE IF NOT EXISTS issues (sid TEXT, ts TEXT, code TEXT, PRIMARY KEY(sid,ts,code));
        """)
        version = self.db.execute("SELECT value FROM settings WHERE key='parser'").fetchone()
        if not version or version[0] != PARSER_VERSION:
            self.rebuild()

    def rebuild(self):
        with self.lock, self.db:
            for table in ("files", "evidence", "sessions", "requests", "issues"):
                self.db.execute(f"DELETE FROM {table}")
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('parser',?)", (PARSER_VERSION,))
            self.indexing, self.cursor, self.last_discovery = True, 0, 0

    def discover(self):
        paths, errors, available = [], [], False
        for home in self.homes:
            for dirname in ("sessions", "archived_sessions"):
                root = Path(home) / dirname
                if not root.exists():
                    continue
                available = True
                def onerror(_):
                    errors.append("directory_unreadable")
                for directory, _, names in os.walk(root, onerror=onerror, followlinks=False):
                    paths.extend(str(Path(directory) / n) for n in names if n.endswith(".jsonl"))
        # Old active files first so a huge historical tree doesn't delay live tails.
        self.paths = sorted(set(paths))
        self.discovery_errors, self.unavailable = errors, not available
        self.last_discovery = time.monotonic()
        self.signals.register([str(Path(h) / d) for h in self.homes for d in ("sessions", "archived_sessions")])
        live = set(self.paths)
        with self.lock, self.db:
            for row in self.db.execute("SELECT path,sid FROM files").fetchall():
                if row["path"] not in live and not errors:
                    self.dirty.add(row["sid"])
                    self.db.execute("DELETE FROM evidence WHERE path=?", (row["path"],))
                    self.db.execute("DELETE FROM files WHERE path=?", (row["path"],))

    def scan(self, budget_seconds=0.25, max_bytes=4 * 1024 * 1024, force_discovery=False):
        if not self.scan_lock.acquire(blocking=False):
            return False
        try:
            interval = 30 if self.signals.handles else 5
            if force_discovery or self.signals.changed() or time.monotonic() - self.last_discovery >= interval:
                self.discover()
            deadline, read = time.monotonic() + budget_seconds, 0
            count = len(self.paths)
            processed = 0
            while processed < count and (processed == 0 or (time.monotonic() < deadline and read < max_bytes)):
                if self.cursor >= count:
                    self.cursor = 0
                read += self._tail(self.paths[self.cursor], max(65536, max_bytes - read))
                self.cursor += 1
                processed += 1
            with self.lock, self.db:
                self._derive_dirty()
                tracked = self.db.execute("SELECT COUNT(*),SUM(pending) FROM files").fetchone()
                self.indexing = tracked[0] < count or bool(tracked[1])
                self.last_scan = utcnow()
            self.bytes_read += read
            return True
        finally:
            self.scan_lock.release()

    def scan_all(self):
        self.scan(60, 64 * 1024 * 1024, True)
        while self.indexing:
            self.scan(60, 64 * 1024 * 1024)

    def _tail(self, path, max_bytes):
        with self.lock:
            row = self.db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
        try:
            stat = os.stat(path)
            signature = f"{stat.st_dev}:{stat.st_ino}"
            if row and row["mtime"] == stat.st_mtime_ns and row["size"] == stat.st_size and row["signature"] == signature and not row["pending"] and "file_unreadable" not in row["errors"]:
                return 0
            with open(path, "rb") as stream:
                offset = row["offset"] if row else 0
                # Validate both ends of the consumed prefix before accepting an append.
                head = digest(stream.read(min(offset, 4096)))
                stream.seek(max(0, offset - 4096))
                tail = digest(stream.read(min(offset, 4096)))
                reset = bool(row and (stat.st_size < row["size"] or signature != row["signature"] or head != row["head"] or tail != row["tail"] or (stat.st_size == row["size"] and stat.st_mtime_ns != row["mtime"])))
                if reset:
                    offset = 0
                stream.seek(offset)
                chunk = stream.read(max_bytes)
                # A large body line is not stored; permit finishing one line (bounded 32MB).
                if chunk and b"\n" not in chunk and len(chunk) == max_bytes:
                    chunk += stream.readline(32 * 1024 * 1024)
                end = chunk.rfind(b"\n") + 1
                complete = chunk[:end]
                new_offset = offset + end
                pending = new_offset < stat.st_size and offset + len(chunk) < stat.st_size
                half_line = new_offset < stat.st_size and not pending
                stream.seek(0)
                new_head = digest(stream.read(min(new_offset, 4096)))
                stream.seek(max(0, new_offset - 4096))
                new_tail = digest(stream.read(min(new_offset, 4096)))
        except OSError:
            with self.lock, self.db:
                if row:
                    errors = json.loads(row["errors"])
                    if "file_unreadable" not in errors:
                        errors.append("file_unreadable")
                    self.db.execute("UPDATE files SET errors=? WHERE path=?", (compact(errors), path))
                else:
                    self.db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?)", (path, 0, 0, 0, "", "", "", None, '["file_unreadable"]', 0))
            return 0
        errors = json.loads(row["errors"]) if row and not reset else []
        errors = [e for e in errors if e not in ("file_unreadable", "incomplete_line")]
        if half_line:
            errors.append("incomplete_line")
        sid = row["sid"] if row and not reset else None
        with self.lock, self.db:
            if reset:
                self.dirty.add(row["sid"])
                self.db.execute("DELETE FROM evidence WHERE path=?", (path,))
            pos = offset
            for line in complete.splitlines(keepends=True):
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                    projected = project(event)
                    if projected:
                        kind, timestamp, data = projected
                        if kind == "session_meta":
                            candidate = data.get("id")
                            if not isinstance(candidate, str) or not candidate:
                                raise ValueError()
                            if sid is None:
                                sid = candidate
                            elif candidate != sid:
                                # Forked files begin with their owner, then may replay the parent's header.
                                # Replayed metadata must not switch ownership of subsequent child responses.
                                kind, data = "inherited_session_meta", {"id": candidate}
                        if not sid:
                            errors.append("missing_session_metadata")
                        else:
                            fp = digest(compact([kind, timestamp, data]).encode())
                            self.db.execute("INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?,?)", (path, pos, sid, kind, timestamp, compact(data), fp))
                            self.dirty.add(sid)
                except (ValueError, UnicodeError, TypeError, AttributeError, OverflowError):
                    errors.append("bad_line")
                pos += len(line)
            self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?)", (path, new_offset, stat.st_size, stat.st_mtime_ns, signature, new_head, new_tail, sid, compact(errors), int(pending)))
        return len(complete)

    def _events(self, sid):
        # Distinct projection fingerprints remove copied/replayed lines without using token sizes as identity.
        rows = self.db.execute("SELECT * FROM evidence WHERE sid=? ORDER BY ts,pos,path", (sid,)).fetchall()
        seen, events = set(), []
        for row in rows:
            if row["fingerprint"] not in seen:
                seen.add(row["fingerprint"])
                events.append({**dict(row), "data": json.loads(row["data"])})
        return events

    def _derive_dirty(self):
        dirty = {s for s in self.dirty if s}
        self.dirty.clear()
        if not dirty:
            return
        # First metadata for all changed sessions; parents may appear later in directory order.
        for sid in dirty:
            events = self._events(sid)
            metas = [e for e in events if e["kind"] == "session_meta"]
            self.db.execute("DELETE FROM requests WHERE sid=?", (sid,))
            self.db.execute("DELETE FROM issues WHERE sid=?", (sid,))
            if not metas:
                self.db.execute("DELETE FROM sessions WHERE sid=?", (sid,))
                continue
            meta = metas[-1]["data"]
            sub = meta.get("source", {})
            parent = meta.get("parent_thread_id")
            if isinstance(sub, dict):
                parent = parent or sub.get("subagent", {}).get("spawn", {}).get("parent_thread_id")
            scope = "desktop" if meta.get("originator") == "Codex Desktop" else ("cli" if meta.get("source") == "cli" else "other")
            internal = isinstance(sub, dict) and sub.get("subagent", {}).get("other") in ("guardian", "auto-review")
            if internal:
                scope = "internal"
            elif parent:
                scope = "work"
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?)", (sid, compact(meta), scope, parent, meta.get("forked_from_id"), "[]"))
        # A parent change also invalidates descendant fork baselines/source filtering.
        changed = True
        while changed:
            changed = False
            for row in self.db.execute("SELECT sid,parent,fork FROM sessions").fetchall():
                if row["sid"] not in dirty and (row["fork"] in dirty or row["parent"] in dirty):
                    dirty.add(row["sid"])
                    changed = True
        visited, cycles = set(), set()
        def derive(sid, visiting):
            if sid in visited:
                return
            if sid in visiting:
                cycles.update(visiting)
                return
            row = self.db.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
            if row:
                if row["fork"] in dirty:
                    derive(row["fork"], visiting | {sid})
                if sid in cycles:
                    self.db.execute("DELETE FROM requests WHERE sid=?", (sid,))
                    self.db.execute("DELETE FROM issues WHERE sid=?", (sid,))
                    for event in self._events(sid):
                        if event["kind"] in ("usage", "response_usage"):
                            self._issue(sid, event["ts"], "ancestor_cycle")
                    self.db.execute("UPDATE sessions SET errors='[\"ancestor_cycle\"]' WHERE sid=?", (sid,))
                else:
                    self._derive(row)
            visited.add(sid)
        for sid in sorted(dirty):
            derive(sid, set())

    def _derive(self, session):
        sid, meta = session["sid"], json.loads(session["meta"])
        errors, previous, model, turn, seq = [], None, "unknown", None, None
        modality = "text"
        inherited = set()
        events = self._events(sid)
        native = [e for e in events if e["kind"] == "response_usage" and e["data"].get("thread_id") == sid]
        first_native = min((e["ts"], e["pos"]) for e in native) if native else None
        if native:
            first_record = min(native, key=lambda e: (e["ts"], e["pos"]))["data"]
            if session["fork"] or first_record.get("thread_token_usage") == first_record.get("usage"):
                # A fresh per-response accumulator, or a fork whose inherited requests have
                # explicit different owners, needs no legacy context-counter prefix at all.
                first_native = ("", 0)
        parent = session["fork"]
        if parent:
            ancestor = self.db.execute("SELECT meta FROM sessions WHERE sid=?", (parent,)).fetchone()
            if ancestor:
                cutoff = meta.get("fork_timestamp") or meta.get("timestamp")
                try:
                    cutoff = parse_time(cutoff).isoformat()
                except ValueError:
                    cutoff = None
                for e in self._events(parent):
                    inherited.add(e["fingerprint"])
                    if e["kind"] == "usage" and cutoff and e["ts"] <= cutoff:
                        previous = e["data"].get("total_token_usage") or previous
                if previous is None:
                    errors.append("missing_fork_baseline")
            else:
                errors.append("missing_ancestor")
        if meta.get("cli_version") not in SUPPORTED_VERSIONS:
            errors.append("unverified_log_version")
        seen_requests = set()
        self.db.execute("DELETE FROM requests WHERE sid=?", (sid,))
        self.db.execute("DELETE FROM issues WHERE sid=?", (sid,))
        if not parent and any(e["kind"] == "inherited_session_meta" for e in events):
            for event in events:
                if event["kind"] in ("usage", "response_usage"):
                    self._issue(sid, event["ts"], "conflicting_session_metadata")
        for e in events:
            p = e["data"]
            if e["kind"] == "modality":
                modality = merge_modality(modality, p)
                continue
            if e["kind"] == "turn_context":
                model = p.get("model") or "unknown"
                turn = p.get("turn_id")
                continue
            if e["kind"] != "usage":
                continue
            if first_native and (e["ts"], e["pos"]) >= first_native:
                # The native stream identifies completed responses. TokenCount is UI context telemetry,
                # may be estimated/recomputed, and must not be added to the same native responses.
                continue
            current, last = p.get("total_token_usage"), p.get("last_token_usage")
            if not current:
                errors.append("missing_cumulative_usage")
                self._issue(sid, e["ts"], "missing_cumulative_usage")
                continue
            _, snapshot_errors = normalize(current, "included" if meta.get("cli_version") == "synthetic-v1" else None)
            if e["fingerprint"] in inherited:
                previous = current
                continue
            if current == previous:
                continue
            req_id = p.get("response_id") or p.get("request_id")
            if req_id and req_id in seen_requests:
                # Replayed ID must not advance the baseline or consume a different request.
                continue
            usage_raw = delta(current, previous) if previous else current
            reset = any(v is not None and v < 0 for v in usage_raw.values())
            if reset:
                if p.get("usage_reset") is True or (seq is not None and p.get("sequence_id") and seq != p["sequence_id"]):
                    usage_raw = current
                else:
                    errors.append("counter_decreased")
                    self._issue(sid, e["ts"], "counter_decreased")
                    previous, seq = current, p.get("sequence_id")
                    continue
            if previous is None and parent:
                # Missing ancestry: quarantine first inherited snapshot as baseline, count subsequent deltas.
                previous, seq = current, p.get("sequence_id")
                for code in errors:
                    if code in ("missing_ancestor", "missing_fork_baseline"):
                        self._issue(sid, e["ts"], code)
                continue
            boundary = bool(last and all(usage_raw.get(k) == last.get(k) for k in FIELDS.values()))
            if not previous and not boundary:
                errors.append("unverified_initial_snapshot")
                self._issue(sid, e["ts"], "unverified_initial_snapshot")
                # Keep only the identified last request; the preceding cumulative portion is pending.
                if last:
                    usage_raw, boundary = last, True
                else:
                    previous = current
                    continue
            usage, problems = normalize(usage_raw, "included" if meta.get("cli_version") == "synthetic-v1" else None)
            problems.extend(snapshot_errors)
            if not boundary:
                problems.append("unknown_request_boundary")
            if meta.get("cli_version") not in SUPPORTED_VERSIONS:
                problems.append("unverified_log_version")
            if session["scope"] == "work" and meta.get("cli_version") not in SUPPORTED_VERSIONS:
                problems.append("subagent_accounting_unverified")
            request_modality = merge_modality(modality, {"modality": p.get("modality", "text")})
            if usage["total"] is None:
                errors.extend(problems)
                for code in problems:
                    self._issue(sid, e["ts"], code)
                previous = current
                continue
            actual_model = p.get("actual_model") or p.get("model") or model
            identity = f"{sid}:id:{req_id}" if req_id else f"{sid}:event:{e['fingerprint']}"
            record = {"identity": identity, "sessionId": sid, "turnId": p.get("turn_id") or turn,
                      "timestamp": e["ts"], "model": actual_model, "modelEvidence": "usage" if p.get("actual_model") or p.get("model") else "turn_context",
                      "usage": usage, "requestBoundary": boundary, "dedupConfidence": "request-id" if req_id else "source-sequence",
                      "modality": request_modality,
                      "errors": sorted(set(problems))}
            self.db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?)", (identity, sid, e["ts"], actual_model, compact(record)))
            if req_id:
                seen_requests.add(req_id)
            previous, seq = current, p.get("sequence_id")
        if native and not parent:
            first = min(native, key=lambda e: (e["ts"], e["pos"]))
            current, last = first["data"].get("thread_token_usage"), first["data"].get("usage")
            baseline = delta(current, last) if isinstance(current, dict) and isinstance(last, dict) else None
            prefix = [json.loads(r[0])["usage"] for r in self.db.execute("SELECT data FROM requests WHERE sid=?", (sid,))]
            recovered = {raw: sum(u[key] for u in prefix) if all(type(u[key]) is int for u in prefix) else None
                         for key, raw in FIELDS.items()}
            if baseline is None or any(baseline[k] is None or baseline[k] < 0 or recovered[k] != baseline[k] for k in FIELDS.values()):
                self._issue(sid, first["ts"], "unverified_initial_snapshot")
        self._derive_native(session, events, native)
        self.db.execute("UPDATE sessions SET errors=? WHERE sid=?", (compact(sorted(set(errors))), sid))

    def _issue(self, sid, timestamp, code):
        self.db.execute("INSERT OR IGNORE INTO issues VALUES (?,?,?)", (sid, timestamp, code))

    def _derive_native(self, session, events, native):
        sid, meta = session["sid"], json.loads(session["meta"])
        models, model, modality = {}, "unknown", "text"
        signatures, conflicts = {}, set()
        for e in native:
            p = e["data"]
            rid = p.get("response_id")
            signature = compact(p.get("usage"))
            if rid in signatures and signatures[rid] != signature:
                conflicts.add(rid)
            signatures[rid] = signature
        for e in events:
            p = e["data"]
            if e["kind"] == "turn_context":
                model = p.get("model") or "unknown"
                if p.get("turn_id"):
                    models[p["turn_id"]] = model
            elif e["kind"] == "modality":
                modality = merge_modality(modality, p)
            elif e["kind"] == "response_usage" and p.get("thread_id") == sid:
                rid = p.get("response_id")
                if not rid or not p.get("turn_id") or not isinstance(p.get("usage"), dict):
                    self._issue(sid, e["ts"], "invalid_response_usage")
                    continue
                usage, problems = normalize(p["usage"], "included" if meta.get("cli_version") == "synthetic-v1" else None)
                if meta.get("cli_version") not in SUPPORTED_VERSIONS:
                    problems.append("unverified_log_version")
                if rid in conflicts:
                    problems.append("conflicting_response_usage")
                if usage["total"] is None:
                    for code in problems:
                        self._issue(sid, e["ts"], code)
                    continue
                actual_model = models.get(p["turn_id"], "unknown")
                identity = f"{sid}:id:{rid}"
                record = {"identity": identity, "sessionId": sid, "turnId": p["turn_id"],
                    "timestamp": e["ts"], "model": actual_model, "modelEvidence": "turn_context",
                    "usage": usage, "requestBoundary": True, "dedupConfidence": "request-id",
                    "modality": modality,
                    "usageEvidence": "token_usage_record", "errors": sorted(set(problems))}
                self.db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?)",
                    (identity, sid, e["ts"], actual_model, compact(record)))

    def snapshot(self, start, end):
        with self.lock:
            sessions = {r["sid"]: {**dict(r), "meta": json.loads(r["meta"]), "errors": json.loads(r["errors"])} for r in self.db.execute("SELECT * FROM sessions")}
            # Session audit history is retained in SQLite, but a daily card only includes issues
            # observed in that day's usage. An inactive old format cannot invalidate today's logs.
            for session in sessions.values():
                session["errors"] = []
            for issue in self.db.execute("SELECT sid,code FROM issues WHERE ts>=? AND ts<?", (start, end)):
                if issue["sid"] in sessions:
                    sessions[issue["sid"]]["errors"].append(issue["code"])
            records = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM requests WHERE ts>=? AND ts<?", (start, end))]
            errors = Counter(self.discovery_errors)
            for r in self.db.execute("SELECT errors FROM files"):
                errors.update(json.loads(r[0]))
            return sessions, records, errors

    def price_version(self, version):
        with self.lock, self.db:
            current = self.db.execute("SELECT value FROM settings WHERE key='priceVersion'").fetchone()
            if not current or current[0] != version:
                self.db.execute("INSERT OR REPLACE INTO settings VALUES ('priceVersion',?)", (version,))

    def close(self):
        self.signals.close()
        self.db.close()
