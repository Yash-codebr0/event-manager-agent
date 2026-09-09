import json
import os

from agent import run


def handler(request):

    # SECURITY
    

    cron_secret = os.getenv(
        "CRON_SECRET"
    )

    if cron_secret:

        authorization = request.headers.get(
            "authorization",
            ""
        )

        if authorization != (
            f"Bearer {cron_secret}"
        ):

            return {
                "statusCode": 401,

                "headers": {
                    "Content-Type":
                        "application/json"
                },

                "body": json.dumps({
                    "success": False,
                    "error": "Unauthorized"
                })
            }

    # RUN AGENT
    

    try:

        result = run()

        return {
            "statusCode": 200,

            "headers": {
                "Content-Type":
                    "application/json"
            },

            "body": json.dumps({
                "success": True,
                "result": result
            })
        }

    except Exception as e:

        print(
            "Agent execution failed:",
            str(e)
        )

        return {
            "statusCode": 500,

            "headers": {
                "Content-Type":
                    "application/json"
            },

            "body": json.dumps({
                "success": False,
                "error": str(e)
            })
        }
