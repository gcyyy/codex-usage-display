from collections import Counter
from datetime import datetime, date
from decimal import Decimal
from .timeutil import utcnow, window
from .tokens import zero_totals, add_totals
from .compatibility import log_compatibility

MESSAGES = {
    "unknown_model": "模型没有经过核实的官方价格",
    "missing_ancestor": "缺少 fork 祖先，继承基线待核验",
    "missing_fork_baseline": "祖先中没有可验证的继承基线",
    "unknown_cache_write_semantics": "非零缓存写入的包含关系未验证",
    "missing_cache_classification": "缓存分类缺失，不能当作零",
    "unknown_request_boundary": "累计差值不能证明为单次请求",
    "counter_decreased": "累计计数下降，未确认序列重置",
    "bad_line": "日志包含无法解析的完整行",
    "incomplete_line": "末尾半行等待写入完成",
    "unverified_log_version": "日志版本未通过适配验证",
    "subagent_accounting_unverified": "工作子代理与父会话的计数关系待核验",
    "invalid_price_table": "价格表无效，继续使用上一有效版本（如有）",
    "price_table_stale": "价格核验时间超过 30 天",
    "unknown_source": "来源无法确认为桌面，默认未纳入",
    "unsupported_modality": "模态尚无核验过的 Token 计价规则",
    "file_unreadable": "日志暂时无法读取",
    "directory_unreadable": "日志目录无法完整枚举",
    "missing_session_metadata": "记录缺少有效会话身份",
    "missing_cumulative_usage": "用量事件缺少累计快照",
    "unverified_initial_snapshot": "第一条累计快照无法确认为全新用量",
    "inconsistent_total": "总 Token 与输入加输出不一致",
    "invalid_subcategory": "子分类超过父分类",
    "invalid_token_count": "Token 不是非负整数",
    "missing_token_total": "缺少可信输入或输出总量",
    "ancestor_cycle": "会话祖先存在环",
    "parent_includes_subagents": "父会话已包含子代理，子代理从主合计排除",
    "invalid_response_usage": "逐响应用量缺少必要身份或数字字段",
    "conflicting_response_usage": "相同响应 ID 存在互相矛盾的用量",
    "conflicting_session_metadata": "非分支日志包含互相矛盾的会话身份",
}


def money(value):
    return format(value, "f") if value is not None else None


def aggregate(index, prices, timezone="Asia/Shanghai", day=None, include_internal=False, include_cli=False, include_other=False):
    day, start, end = window(day, timezone)
    sessions, records, diagnostics = index.snapshot(start, end)
    included_sessions = set()
    compatibility_records = []

    def desktop(sid, seen=None):
        seen = seen or set()
        if sid in seen or sid not in sessions:
            return False
        s = sessions[sid]
        if s["scope"] == "desktop":
            return True
        if s["scope"] in ("work", "internal"):
            return desktop(s["parent"], seen | {sid})
        return False

    def included(sid):
        s = sessions.get(sid)
        if not s:
            return False
        scope = s["scope"]
        if scope == "internal":
            return include_internal and desktop(sid)
        if scope == "work":
            parent = sessions.get(s["parent"])
            if parent and parent["meta"].get("usage_includes_subagents") is True:
                return False
            return desktop(sid)
        return scope == "desktop" or (scope == "cli" and include_cli) or (scope == "other" and include_other)

    models, internal, excluded = {}, {}, Counter()
    totals = zero_totals()
    known = Decimal(0)
    priced, unpriced, priced_count = 0, 0, 0
    data_errors = bool(diagnostics)
    for r in records:
        s = sessions[r["sessionId"]]
        take = included(r["sessionId"])
        is_internal = s["scope"] == "internal" or r["model"] == "codex-auto-review"
        if r["model"] == "codex-auto-review" and not include_internal:
            take = False
        if take:
            compatibility_records.append(r)
        amount, reason, price_id, context = prices.cost(r)
        target = models if take else internal if is_internal else None
        if target is None:
            excluded[s["scope"]] += r["usage"]["total"]
            continue
        model = target.setdefault(r["model"], {"modelId": r["model"], "pricingModelId": price_id,
              "mappingEvidence": "exact-id-or-reviewed-alias" if price_id else None,
              "totals": zero_totals(), "known": Decimal(0), "pricedTokens": 0, "unpricedTokens": 0,
              "pricedRequests": 0, "unpricedRequests": 0, "reasons": Counter(), "rateContexts": set(), "internal": is_internal})
        add_totals(model["totals"], r["usage"])
        if amount is None:
            model["unpricedTokens"] += r["usage"]["total"]
            model["unpricedRequests"] += 1
            model["reasons"][reason] += 1
        else:
            model["known"] += amount
            model["pricedTokens"] += r["usage"]["total"]
            model["pricedRequests"] += 1
            model["rateContexts"].add(context)
        if not take:
            continue
        included_sessions.add(r["sessionId"])
        add_totals(totals, r["usage"])
        if reason:
            diagnostics[reason] += 1
        for problem in r["errors"]:
            if problem in ("invalid_token_count", "invalid_subcategory", "inconsistent_total", "missing_token_total", "unverified_log_version", "invalid_response_usage", "conflicting_response_usage"):
                data_errors = True
                diagnostics[problem] += 1
        if amount is not None:
            known += amount
            priced += r["usage"]["total"]
            priced_count += 1
        else:
            unpriced += r["usage"]["total"]
    # Sessions with only quarantined usage also invalidate coverage.
    for sid, s in sessions.items():
        if included(sid):
            diagnostics.update(s["errors"])
            if s["errors"]:
                data_errors = True
    if excluded.get("other"):
        diagnostics["unknown_source"] += 1
    if prices.error:
        diagnostics[prices.error] += 1
    pricing = prices.table
    if pricing and (date.fromisoformat(day) - date.fromisoformat(pricing["verifiedAt"])).days > 30:
        diagnostics["price_table_stale"] += 1
    data_status = "unavailable" if index.unavailable else "indexing" if index.indexing else "partial" if data_errors else "complete"
    price_status = "unavailable" if not pricing or (unpriced and not priced_count) else "partial" if unpriced else "complete"
    complete = data_status == "complete" and price_status == "complete"

    def finish(group):
        output = []
        for model in group.values():
            known_amount = model.pop("known")
            model["knownSubtotalUSD"] = money(known_amount) if model["pricedRequests"] else None
            model["costUSD"] = model["knownSubtotalUSD"] if not model["unpricedRequests"] else None
            model["priceStatus"] = "complete" if not model["unpricedRequests"] else "partial" if model["pricedRequests"] else "unavailable"
            model["reasons"] = [{"code": k, "count": n, "message": MESSAGES.get(k, k)} for k, n in model["reasons"].items()]
            model["rateContexts"] = sorted(model["rateContexts"])
            entry = prices.lookup(model["modelId"])
            model["rates"] = {"short": entry["rates"], "long": entry["longContext"]} if entry else None
            output.append(model)
        return sorted(output, key=lambda m: (-m["totals"]["total"], m["modelId"]))

    return {"schemaVersion": "1", "date": day, "timezone": timezone,
        "windowStartUtc": start, "windowEndUtc": end, "generatedAt": utcnow(), "lastSuccessfulScanAt": index.last_scan,
        "sourceScope": {"homes": len(index.homes), "rule": "desktop-originator-and-parent-chain", "includeInternal": include_internal,
                        "includeCLI": include_cli, "includeOther": include_other, "accountScope": "local-home-not-current-account-billing"},
        "dataStatus": data_status, "priceStatus": price_status,
        "compatibility": log_compatibility(sessions, compatibility_records, included),
        "pricing": {"priceVersion": pricing["priceVersion"] if pricing else None, "verifiedAt": pricing["verifiedAt"] if pricing else None,
                    "currency": "USD", "tier": "Standard", "basis": "current-snapshot-text-and-image-input-token-equivalent"},
        "totals": totals, "totalCostUSD": money(known) if complete else None,
        "knownSubtotalUSD": money(known) if priced_count or (totals["total"] == 0 and data_status == "complete") else None,
        "pricedTokens": priced, "unpricedTokens": unpriced,
        "priceCoverage": str(Decimal(priced) / Decimal(priced + unpriced)) if priced + unpriced else None,
        "models": finish(models), "internalModels": finish(internal), "excludedTokens": dict(excluded),
        "diagnostics": [{"code": k, "count": n, "message": MESSAGES.get(k, k)} for k, n in sorted(diagnostics.items())]}
