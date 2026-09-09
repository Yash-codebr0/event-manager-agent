import os
import re
import base64
import json
from datetime import datetime, timedelta, timezone

from dateutil import parser

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from openai import OpenAI


# ============================================================
# CONFIG
# ============================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")

TIMEZONE = "Asia/Kolkata"

client = OpenAI(api_key=OPENAI_API_KEY)

GMAIL_SCOPE = [
    "https://www.googleapis.com/auth/gmail.modify"
]

CALENDAR_SCOPE = [
    "https://www.googleapis.com/auth/calendar"
]


# ============================================================
# ENVIRONMENT VALIDATION
# ============================================================

def validate_environment():

    required = {
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "GOOGLE_REFRESH_TOKEN": GOOGLE_REFRESH_TOKEN,
    }

    missing = [
        name
        for name, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# GOOGLE AUTHENTICATION
# ============================================================

def get_google_credentials(scopes):

    validate_environment()

    credentials = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=scopes,
    )

    if credentials.expired or not credentials.valid:
        credentials.refresh(Request())

    return credentials


def get_service(api, version, scopes):

    credentials = get_google_credentials(scopes)

    return build(
        api,
        version,
        credentials=credentials,
        cache_discovery=False,
    )


# ============================================================
# GMAIL
# ============================================================

def decode(data):

    if not data:
        return ""

    try:
        return base64.urlsafe_b64decode(
            data + "=" * (-len(data) % 4)
        ).decode(
            "utf-8",
            errors="ignore"
        )
    except Exception:
        return ""


def clean_html(text):

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def extract_body(payload):

    if not payload:
        return ""

    mime_type = payload.get("mimeType", "")

    # Plain text
    if mime_type == "text/plain":

        data = payload.get("body", {}).get("data")

        if data:
            return decode(data)

    # HTML
    if mime_type == "text/html":

        data = payload.get("body", {}).get("data")

        if data:
            return clean_html(
                decode(data)
            )

    # Multipart
    for part in payload.get("parts", []):

        result = extract_body(part)

        if result:
            return result

    return ""


def get_emails(service):

    results = service.users().messages().list(
        userId="me",
        q="is:unread newer_than:1d",
        maxResults=5
    ).execute()

    messages = results.get(
        "messages",
        []
    )

    emails = []

    for msg in messages:

        msg_id = msg["id"]

        try:

            data = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full"
            ).execute()

            # Gmail internal timestamp
            msg_time = int(
                data["internalDate"]
            ) / 1000

            email_time = datetime.fromtimestamp(
                msg_time,
                tz=timezone.utc
            )

            now = datetime.now(timezone.utc)

            # Keep the original 6-hour filter
            if now - email_time > timedelta(hours=6):

                print(
                    f"Skipping old email: {msg_id}"
                )

                mark_read(
                    service,
                    msg_id
                )

                continue

            body = extract_body(
                data.get("payload", {})
            )

            emails.append(
                (
                    msg_id,
                    body
                )
            )

        except Exception as e:

            print(
                f"Failed to read message {msg_id}: {e}"
            )

    return emails


def mark_read(service, msg_id):

    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={
            "removeLabelIds": [
                "UNREAD"
            ]
        }
    ).execute()


# ============================================================
# AI EXTRACTION
# ============================================================

def extract_event(email):

    prompt = f"""
You are an event extraction system.

Analyze the email below.

Extract ONLY actual events, meetings,
appointments, calls, interviews, or scheduled activities.

Return JSON ONLY.

Required format:

[
    {{
        "title": "",
        "date": "YYYY-MM-DD",
        "time": "HH:MM",
        "confidence": 0.0
    }}
]

Rules:

- date must be YYYY-MM-DD
- time must be 24-hour HH:MM
- confidence must be between 0 and 1
- Do not invent information.
- If there is no event, return [].
- If multiple events exist, return multiple objects.

Email:

{email}
"""

    try:

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        output = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        # Remove markdown fences
        output = (
            output
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        print(
            "\nAI RAW OUTPUT:\n",
            output
        )

        events = json.loads(output)

        if not isinstance(events, list):
            return []

        return events

    except Exception as e:

        print(
            "AI FAILED:",
            str(e)
        )

        return []


# ============================================================
# FALLBACK PARSER
# ============================================================

def fallback_extract(text):

    events = []

    text_lower = text.lower()

    # --------------------------------------------------------
    # Relative date
    # --------------------------------------------------------

    if "today" in text_lower:

        date = datetime.now().date()

    elif "tomorrow" in text_lower:

        date = (
            datetime.now().date()
            + timedelta(days=1)
        )

    else:

        date = None

    # --------------------------------------------------------
    # Time detection
    # --------------------------------------------------------

    time_match = re.search(
        r"(\d{1,2})(:\d{2})?\s*(am|pm)",
        text_lower
    )

    if date and time_match:

        hour = int(
            time_match.group(1)
        )

        minute = (
            int(
                time_match.group(2)[1:]
            )
            if time_match.group(2)
            else 0
        )

        meridiem = time_match.group(3)

        if meridiem == "pm" and hour != 12:
            hour += 12

        if meridiem == "am" and hour == 12:
            hour = 0

        dt = datetime.combine(
            date,
            datetime.min.time()
        ).replace(
            hour=hour,
            minute=minute
        )

        events.append(
            {
                "title": "Meeting - " + text[:30],
                "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M"),
                "confidence": 0.7,
                "source": "fallback"
            }
        )

    # --------------------------------------------------------
    # Formal date/time patterns
    # --------------------------------------------------------

    patterns = [

        r"\w+ \d{1,2}, \d{4}.*?\d{1,2}:\d{2}",

        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}",

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text
        )

        for match in matches:

            try:

                dt = parser.parse(
                    match
                )

                events.append(
                    {
                        "title": "Detected Event",
                        "date": dt.strftime(
                            "%Y-%m-%d"
                        ),
                        "time": dt.strftime(
                            "%H:%M"
                        ),
                        "confidence": 0.6,
                        "source": "fallback"
                    }
                )

            except Exception:
                continue

    return events


# ============================================================
# DATE/TIME
# ============================================================

def parse_datetime(
    date,
    time_str
):

    try:

        if time_str:

            return parser.parse(
                f"{date} {time_str}"
            )

        return parser.parse(date)

    except Exception:

        return None


# ============================================================
# CALENDAR
# ============================================================

def add_to_calendar(
    service,
    event,
    email
):

    try:

        dt = parse_datetime(
            event.get("date"),
            event.get("time")
        )

        if not dt:

            print(
                "Invalid datetime"
            )

            return None

        end = dt + timedelta(
            hours=1
        )

        body = {
            "summary": event.get(
                "title",
                "Detected Event"
            ),

            "description": email[:500],

            "start": {
                "dateTime": dt.isoformat(),
                "timeZone": TIMEZONE
            },

            "end": {
                "dateTime": end.isoformat(),
                "timeZone": TIMEZONE
            }
        }

        created = (
            service
            .events()
            .insert(
                calendarId="primary",
                body=body
            )
            .execute()
        )

        link = created.get(
            "htmlLink"
        )

        print(
            "Event created:",
            link
        )

        return {
            "id": created.get("id"),
            "title": created.get("summary"),
            "link": link
        }

    except Exception as e:

        print(
            "Calendar error:",
            str(e)
        )

        return None


# ============================================================
# MAIN AGENT
# ============================================================

def run():

    print(
        "\nAgent started..."
    )

    validate_environment()

    # --------------------------------------------------------
    # Google services
    # --------------------------------------------------------

    gmail_service = get_service(
        "gmail",
        "v1",
        GMAIL_SCOPE
    )

    calendar_service = get_service(
        "calendar",
        "v3",
        CALENDAR_SCOPE
    )

    # --------------------------------------------------------
    # Get unread emails
    # --------------------------------------------------------

    emails = get_emails(
        gmail_service
    )

    if not emails:

        print(
            "No new emails."
        )

        return {
            "processed": 0,
            "events_created": 0,
            "events": []
        }

    processed_count = 0
    created_events = []

    # --------------------------------------------------------
    # Process emails
    # --------------------------------------------------------

    for msg_id, email in emails:

        print(
            "\nProcessing:",
            msg_id
        )

        print(
            "\nEMAIL:\n",
            email[:500]
        )

        # ----------------------------------------------------
        # Empty email
        # ----------------------------------------------------

        if (
            not email
            or len(email.strip()) < 20
        ):

            print(
                "Empty email skipped."
            )

            mark_read(
                gmail_service,
                msg_id
            )

            continue

        # ----------------------------------------------------
        # Scheduling filter
        # ----------------------------------------------------

        keywords = [
            "meeting",
            "schedule",
            "call",
            "appointment",
            "interview",
            "zoom",
            "meet",
            "join"
        ]

        if not any(
            keyword in email.lower()
            for keyword in keywords
        ):

            print(
                "Not a scheduling email."
            )

            mark_read(
                gmail_service,
                msg_id
            )

            continue

        # ----------------------------------------------------
        # AI extraction
        # ----------------------------------------------------

        events = extract_event(
            email
        )

        print(
            "\nExtracted events:",
            events
        )

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        if not events:

            print(
                "AI failed. Using fallback."
            )

            events = fallback_extract(
                email
            )

        # ----------------------------------------------------
        # No event
        # ----------------------------------------------------

        if not events:

            print(
                "No events found."
            )

            mark_read(
                gmail_service,
                msg_id
            )

            continue

        # ----------------------------------------------------
        # Calendar creation
        # ----------------------------------------------------

        for event in events:

            confidence = event.get(
                "confidence",
                0
            )

            source = event.get(
                "source",
                ""
            )

            if (
                confidence < 0.5
                and source != "fallback"
            ):

                print(
                    "Low confidence event skipped."
                )

                continue

            created = add_to_calendar(
                calendar_service,
                event,
                email
            )

            if created:

                created_events.append(
                    created
                )

        # ----------------------------------------------------
        # Mark email processed
        # ----------------------------------------------------

        mark_read(
            gmail_service,
            msg_id
        )

        processed_count += 1

    # --------------------------------------------------------
    # Final response
    # --------------------------------------------------------

    result = {
        "processed": processed_count,
        "events_created": len(
            created_events
        ),
        "events": created_events
    }

    print(
        "\nAgent finished:",
        result
    )

    return result
