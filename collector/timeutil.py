from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone missing")
    return result.astimezone(UTC)


def tz(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Windows portable build: modern Shanghai has no DST. Other zones require tzdata.
        if name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name)
        if name == "UTC":
            return UTC
        raise


def window(day=None, name="Asia/Shanghai", now=None):
    zone = tz(name)
    now = now or datetime.now(UTC)
    d = datetime.fromisoformat(day).date() if day else now.astimezone(zone).date()
    start = datetime.combine(d, datetime.min.time(), zone)
    end = datetime.combine(d + timedelta(days=1), datetime.min.time(), zone)
    return d.isoformat(), start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()


def utcnow():
    return datetime.now(UTC).isoformat()
