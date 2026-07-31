"""Shared helpers for every Lambda. Keeps the handlers small and consistent."""
import datetime
import decimal
import json
import os

import boto3

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - stdlib on 3.9+
    ZoneInfo = None

_dynamodb = boto3.resource("dynamodb")
TABLE = _dynamodb.Table(os.environ["TABLE_NAME"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "Content-Type,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
}

# Typed partitions in the single table. See data-stack.ts for the full layout.
EVENT_PK = "EVENT#{source}"  # source = academic | community; SK = <startUTC>#<eventId>
SYNC_PK = "SYNC"             # SK = source, last-sync metadata
CONFLICT_PK = "CONFLICT"     # SK = conflictId
RECO_PK = "RECO"             # SK = requestedAt ISO timestamp
TASK_PK = "TASK"             # SK = taskId
MEMBER_PK = "MEMBER"         # SK = member name


def app_tz():
    """The timezone whose day-boundaries define 'today'. Lagos has no DST, so
    the fixed-offset fallback (+1) is safe if the image lacks tzdata."""
    name = os.environ.get("APP_TZ", "Africa/Lagos")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - missing tzdata -> fixed offset
            pass
    offset = int(os.environ.get("APP_UTC_OFFSET_HOURS", "1"))
    return datetime.timezone(datetime.timedelta(hours=offset))


def local_now():
    return datetime.datetime.now(app_tz())


class _DecimalEncoder(json.JSONEncoder):
    """DynamoDB returns numbers as Decimal; render them as int/float in JSON."""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def get_secret(name):
    """Fetch and parse a JSON secret from Secrets Manager."""
    sm = boto3.client("secretsmanager")
    return json.loads(sm.get_secret_value(SecretId=name)["SecretString"])
