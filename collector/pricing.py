"""Reviewed, offline JSON snapshot; Decimal amounts, exact model aliases."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

RATE_KEYS = ("uncachedInput", "cacheReadInput", "cacheWriteInput", "output")


def validate(table):
    if table.get("schemaVersion") != "1" or not table.get("priceVersion"):
        raise ValueError("Invalid pricing schema")
    date.fromisoformat(table["verifiedAt"])
    used = set()
    for row in table["models"]:
        if row["currency"] != "USD" or row["tier"] != "Standard" or row["unitTokens"] != 1_000_000:
            raise ValueError("Only Standard USD per million supported")
        for name in [row["modelId"], *row["aliases"]]:
            if not isinstance(name, str) or name in used:
                raise ValueError("Duplicate model alias")
            used.add(name)
        for rates in (row["rates"], row["longContext"]["rates"]):
            for key in RATE_KEYS:
                value = rates[key]
                if value is not None and (not isinstance(value, str) or not Decimal(value).is_finite() or Decimal(value) < 0):
                    raise ValueError("Invalid rate")
        rule = row["longContext"]
        if type(rule["thresholdInputTokens"]) is not int or rule["thresholdInputTokens"] < 0 or rule["mode"] != "whole-request" or rule["comparison"] != ">":
            raise ValueError("Invalid long context rule")
        if not row["sourceUrls"] or any(not u.startswith("https://developers.openai.com/") for u in row["sourceUrls"]):
            raise ValueError("Official source required")
        date.fromisoformat(row["verifiedAt"])
        policy = row.get("imageInputPricing")
        if policy is not None:
            if policy != "included-in-input-tokens" or "https://developers.openai.com/api/docs/guides/images-vision" not in row["sourceUrls"]:
                raise ValueError("Unreviewed image input policy")
        for key in ("effectiveFrom", "effectiveTo"):
            if row[key] is not None:
                date.fromisoformat(row[key])
    return table


class PriceBook:
    def __init__(self, path, backup=None):
        self.path = Path(path)
        self.backup = Path(backup) if backup else None
        self.table = None
        self.error = None
        self.signature = None
        if self.backup and self.backup.exists():
            try:
                self.table = validate(json.loads(self.backup.read_text(encoding="utf-8")))
            except (ValueError, KeyError, TypeError):
                pass
        self.reload()

    def reload(self):
        try:
            sig = (self.path.stat().st_mtime_ns, self.path.stat().st_size)
            if sig == self.signature:
                return
            table = validate(json.loads(self.path.read_text(encoding="utf-8")))
            if self.backup:
                self.backup.parent.mkdir(parents=True, exist_ok=True)
                temp = self.backup.with_suffix(".tmp")
                temp.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(self.backup)
            self.table, self.signature, self.error = table, sig, None
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation):
            self.error = "invalid_price_table"

    def lookup(self, model):
        if self.table:
            for row in self.table["models"]:
                if model == row["modelId"] or model in row["aliases"]:
                    return row
        return None

    def cost(self, request):
        row = self.lookup(request["model"])
        if row is None:
            return None, "unknown_model", None, None
        if request["errors"]:
            return None, request["errors"][0], row["modelId"], None
        modality = request.get("modality", "text")
        if modality != "text" and not (modality == "image-input" and row.get("imageInputPricing") == "included-in-input-tokens"):
            return None, "unsupported_modality", row["modelId"], None
        if not request["requestBoundary"]:
            return None, "unknown_request_boundary", row["modelId"], None
        u = request["usage"]
        if u.get("uncachedInput") is None or u.get("cacheRead") is None or u.get("cacheWrite") is None or u.get("output") is None:
            return None, "missing_cache_classification", row["modelId"], None
        long = u["input"] > row["longContext"]["thresholdInputTokens"]
        rates = row["longContext"]["rates"] if long else row["rates"]
        values = (u["uncachedInput"], u["cacheRead"], u["cacheWrite"], u["output"])
        if any(rates[k] is None and n for k, n in zip(RATE_KEYS, values)):
            return None, "missing_category_price", row["modelId"], None
        amount = sum((Decimal(n) * Decimal(rates[k] or "0") for k, n in zip(RATE_KEYS, values)), Decimal(0)) / Decimal(row["unitTokens"])
        return amount, None, row["modelId"], "long" if long else "short"

