# ================== IMPORTS ==================
import os
import re
import base64
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dateutil import parser

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from openai import OpenAI

# ================== CONFIG ==================
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

GMAIL_SCOPE = ['https://www.googleapis.com/auth/gmail.modify']
CALENDAR_SCOPE = ['https://www.googleapis.com/auth/calendar']

# ================== FILE HELPERS ==================
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

# ================== AUTH ==================
def get_service(api, version, scopes, token_file):
    creds = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            print("Token expired permanently. Re-auth required.")
            os.remove(token_file)
            creds = None
            
    if not creds:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json', scopes)
        creds = flow.run_local_server(port=0)

        with open(token_file, 'w') as f:
            f.write(creds.to_json())

    return build(api, version, credentials=creds)

# ================== GMAIL ==================
def decode(data):
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

def clean_html(text):
    text = re.sub('<.*?>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_body(payload):
    if payload.get("mimeType") == "text/plain":
        data = payload["body"].get("data")
        if data:
            return decode(data)

    if payload.get("mimeType") == "text/html":
        data = payload["body"].get("data")
        if data:
            return clean_html(decode(data))

    for part in payload.get("parts", []):
        result = extract_body(part)
        if result:
            return result

    return ""

def get_emails(service):
    #service = get_service('gmail', 'v1', GMAIL_SCOPE, 'gmail_token.json')

    results = service.users().messages().list(
        userId='me',
        q='is:unread newer_than:1d',
        maxResults=5
    ).execute()

    messages = results.get('messages', [])
    emails = []
    
    processed = load_json("processed.json")

    for msg in messages:
        msg_id = msg['id']
        
        if msg_id in processed:
            continue

        data = service.users().messages().get(
            userId='me', id=msg_id, format='full'
        ).execute()


    # -------- TIME FILTER --------
        msg_time = int(data['internalDate']) / 1000
        email_time = datetime.fromtimestamp(msg_time)

        if datetime.now() - email_time > timedelta(hours=6):
            print("⏭️ Old email skipped")
            mark_read(service, msg_id)
            continue

        body = extract_body(data['payload'])

        emails.append((msg_id, body))

    return emails

def mark_read(service, msg_id):
    service.users().messages().modify(
        userId='me',
        id=msg_id,
        body={'removeLabelIds': ['UNREAD']}
    ).execute()

# ================== AI EXTRACTION ==================
def extract_event(email):
    prompt = f"""
Extract event details.

Return JSON ONLY:
[
    {{
    "title": "",
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "confidence": 0-1
    }}
]

Email:
{email}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        #  EVERYTHING that uses res MUST be inside try
        output = res.choices[0].message.content.strip()
        output = output.replace("```json", "").replace("```", "").strip()
        
        print("\n🧠 AI RAW OUTPUT:\n", output)

        return json.loads(output)

    except Exception as e:
        print("❌ AI FAILED:", e)
        return []

# ================== VALIDATION ==================
def fallback_extract(text):
    events = []
    text_lower = text.lower()

    # -------- STEP 1: RELATIVE DATE --------
    if "today" in text_lower:
        date = datetime.now().date()
    elif "tomorrow" in text_lower:
        date = datetime.now().date() + timedelta(days=1)
    else:
        date = None

    # -------- STEP 2: TIME DETECTION --------
    time_match = re.search(r'(\d{1,2})(:\d{2})?\s*(am|pm)', text_lower)

    if date and time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)[1:]) if time_match.group(2) else 0

        if time_match.group(3) == "pm" and hour != 12:
            hour += 12
        if time_match.group(3) == "am" and hour == 12:
            hour = 0

        dt = datetime.combine(date, datetime.min.time()).replace(
            hour=hour, minute=minute
        )

        events.append({
            "title": "Meeting - " + text[:30],
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "confidence": 0.7,
            "source": "fallback"
        })

    # -------- STEP 3: EXISTING FORMAL PARSER --------
    patterns = [
        r'\w+ \d{1,2}, \d{4}.*?\d{1,2}:\d{2}',
        r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)

        for m in matches:
            try:
                dt = parser.parse(m)

                events.append({
                    "title": "Detected Event",
                    "date": dt.strftime("%Y-%m-%d"),
                    "time": dt.strftime("%H:%M"),
                    "confidence": 0.6
                })
            except:
                continue

    return events
    
# ================== CALENDAR ==================
def parse_datetime(date, time_str):
    try:
        if time_str:
            return parser.parse(f"{date} {time_str}")
        return parser.parse(date)
    except:
        return None
    
def add_to_calendar(service,event,email):
    dt = parse_datetime(event['date'], event.get('time'))

    if not dt:
        print("❌ Invalid datetime")
        return

    end = dt + timedelta(hours=1)

    body = {
        "summary": event['title'],
        "description": email[:500],
        "start": {"dateTime": dt.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"}
    }

    created = service.events().insert(
        calendarId='primary',
        body=body
    ).execute()

    print("✅ Event created:", created.get("htmlLink"))


# ================== AGENT LOOP ==================
def run():
    gmail_service  = get_service('gmail', 'v1', GMAIL_SCOPE, 'gmail_token.json')
    calendar_service = get_service('calendar', 'v3', CALENDAR_SCOPE, 'calendar_token.json')

    emails = get_emails(gmail_service)

    if not emails:
        print("No new emails")
        return
    
    processed = load_json("processed.json")

    for msg_id, email in emails:
        print("\nProcessing email...")
        print("\n📩 EMAIL CONTENT:\n", email[:300])

        if not email or len(email.strip()) < 20:
            print("⚠️ Empty email skipped")
            mark_read(gmail_service, msg_id)
            continue

        ####FILTER#####  
        keywords = ["meeting", "schedule", "call", "appointment", "interview", "zoom", "meet", "join"]

        if not any(k in email.lower() for k in keywords):
            print("⏭️ Not a scheduling email")
            mark_read(gmail_service, msg_id)
            continue
        
########FALLBACK ai #####
        events = extract_event(email)
        print("\n🧠 Extracted events:", events)
        
        if not events:
            print("⚠️ AI failed, swiching to fallback...")
            events = fallback_extract(email)

        if not events:
            print("No events found")
            mark_read(gmail_service, msg_id)
            processed[msg_id]= True
            continue

        for e in events:
            if e.get("confidence", 0) < 0.5 and "fallback" not in e.get("source", ""):
                print("Low confidence skipped")
                continue

            add_to_calendar(calendar_service, e, email)

        mark_read(gmail_service, msg_id)
        processed[msg_id] = True

    save_json("processed.json", processed)

# ================== MAIN ==================
if __name__ == "__main__":
    while True:
        print("\n🤖 Agent running...")
        run()
        time.sleep(60)