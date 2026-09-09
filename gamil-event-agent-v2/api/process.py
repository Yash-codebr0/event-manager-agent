import json
import os

from agent import run


def handler(request):
    # Protect the endpoint from random people triggering your Gmail agent.
    cron_secret = os.getenv("CRON_SECRET")

    if cron_secret:
        auth = request.headers.get("authorization", "")

        if auth != f"Bearer {cron_secret}":
            return {
                "statusCode": 401,
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": json.dumps({
                    "error": "Unauthorized"
                })
            }

    try:
        result = run()

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "success": True,
                "result": result
            })
        }

    except Exception as e:

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "success": False,
                "error": str(e)
            })
        }