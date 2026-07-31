"""GET /health - proves the API GW -> Lambda -> table wiring end to end."""
import os

from common import TABLE, local_now, resp


def handler(event, context):
    # DescribeTable via the resource's table_status: a real call against the
    # table this stage wired in, not just a static 200.
    return resp(200, {
        "ok": True,
        "service": "convene",
        "stage": os.environ.get("TABLE_NAME", "?").rsplit("-", 1)[-1],
        "table": TABLE.table_name,
        "table_status": TABLE.table_status,
        "time": local_now().isoformat(),
    })
