"""Entirely synthetic events. No user conversation content in fixtures."""
import json


def usage(i=100, read=20, write=0, o=10, reasoning=4):
    return dict(input_tokens=i, cached_input_tokens=read, cache_write_input_tokens=write,
                output_tokens=o, reasoning_output_tokens=reasoning, total_tokens=i + o)


def sum_usage(*items):
    return {k: sum(x[k] for x in items) for k in items[0]}


def event(kind, payload, ts="2026-10-14T01:00:00Z"):
    return {"timestamp": ts, "type": kind, "payload": payload}


def meta(sid="s1", **extra):
    return event("session_meta", {"id": sid, "originator": "Codex Desktop", "cli_version": "synthetic-v1",
        "source": "vscode", "timestamp": "2026-10-13T01:00:00Z", **extra}, "2026-10-13T01:00:00Z")


def context(model="gpt-6.1-sol", turn="t1", ts="2026-10-14T00:59:00Z"):
    return event("turn_context", {"model": model, "turn_id": turn}, ts)


def count(total=None, last=None, ts="2026-10-14T01:00:00Z", **extra):
    total = total or usage()
    last = last or total
    return event("event_msg", {"type": "token_count", "info": {"total_token_usage": total, "last_token_usage": last}, **extra}, ts)


def response(sid="s1", rid="response1", turn="t1", value=None, total=None, ts="2026-10-14T01:00:00Z"):
    value = value or usage()
    return event("token_usage_record", {"thread_id": sid, "turn_id": turn,
        "response_id": rid, "usage": value, "thread_token_usage": total or value,
        "session_id": "synthetic-session", "root_turn_id": "synthetic-root", "turn_token_usage": value}, ts)


def write(path, events, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8", newline="\n") as stream:
        for item in events:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
