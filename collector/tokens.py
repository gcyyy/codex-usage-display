"""Conservative normalization for Codex cumulative TokenUsage snapshots."""
FIELDS = {"input": "input_tokens", "cacheRead": "cached_input_tokens",
          "cacheWrite": "cache_write_input_tokens", "output": "output_tokens",
          "reasoning": "reasoning_output_tokens", "total": "total_tokens"}
KEYS = tuple(FIELDS)


def normalize(raw, write_semantics=None):
    errors = []
    result = {}
    for key, field in FIELDS.items():
        value = raw.get(field)
        if value is not None and (type(value) is not int or value < 0):
            errors.append("invalid_token_count")
            value = None
        result[key] = value
    i, o = result["input"], result["output"]
    if i is None or o is None:
        errors.append("missing_token_total")
    else:
        if result["total"] is not None and result["total"] != i + o:
            errors.append("inconsistent_total")
        result["total"] = i + o
    for child, parent in (("cacheRead", "input"), ("reasoning", "output")):
        if result[child] is not None and result[parent] is not None and result[child] > result[parent]:
            errors.append("invalid_subcategory")
    read, write = result["cacheRead"], result["cacheWrite"]
    result["uncachedInput"] = None
    if read is None or write is None:
        errors.append("missing_cache_classification")
    elif write and write_semantics != "included":
        errors.append("unknown_cache_write_semantics")
    elif i is not None:
        if read + write > i:
            errors.append("invalid_subcategory")
        else:
            result["uncachedInput"] = i - read - write
    return result, sorted(set(errors))


def delta(current, previous):
    return {k: (current[k] - previous[k] if type(current.get(k)) is int and type(previous.get(k)) is int and current[k] >= 0 and previous[k] >= 0 else None)
            for k in FIELDS.values()}


def zero_totals():
    return dict.fromkeys(KEYS, 0)


def add_totals(target, usage):
    for key in KEYS:
        target[key] = None if target[key] is None or usage.get(key) is None else target[key] + usage[key]

