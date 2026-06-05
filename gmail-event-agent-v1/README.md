# 🤖 AI Scheduling Agent v1.0

## 📌 Overview

AI Scheduling Agent v1.0 is an automation system that reads emails from Gmail, detects scheduling-related content, extracts event details using AI or fallback logic, and automatically creates events in Google Calendar.

This version represents a stable MVP (Minimum Viable Product) with a complete end-to-end pipeline.

---

## ⚙️ Features

### ✅ Email Processing

* Reads unread emails from Gmail
* Filters emails based on scheduling-related keywords
* Skips already processed emails

### 🧠 Event Extraction

* Uses AI (OpenAI) to extract:

  * Title
  * Date
  * Time
* Fallback parser handles:

  * “today”, “tomorrow”
  * Time formats like “8pm”, “10:30 am”
  * Basic structured date formats

### 📅 Calendar Integration

* Automatically creates events in Google Calendar
* Sets:

  * Title
  * Start time
  * End time (+1 hour default)
  * Timezone (Asia/Kolkata)

### 🔁 Continuous Execution

* Runs in a loop every 60 seconds
* Processes new emails automatically

### 🗂️ State Management

* Tracks processed emails using `processed.json`
* Prevents duplicate processing

---

## 🏗️ Project Structure

```
agent/
 ├── agent_v1.py
 ├── gmail_token.json
 ├── calendar_token.json
 ├── processed.json
 ├── credentials.json
 ├── .env
```

---

## 🔐 Setup Instructions

### 1. Install Dependencies

```
pip install google-api-python-client google-auth google-auth-oauthlib python-dotenv python-dateutil openai
```

---

### 2. Configure Environment Variables

Create `.env` file:

```
OPENAI_API_KEY=your_api_key_here
```

---

### 3. Google API Setup

* Enable:

  * Gmail API
  * Google Calendar API
* Download `credentials.json`
* Place it in project root

---

### 4. Run the Agent

```
python agent_v1.py
```

On first run:

* Browser will open for authentication
* Tokens will be saved locally

---

## 🔄 Workflow

```
Gmail → Fetch Emails → Filter → AI Extraction → Fallback Parser → Calendar Event
```

---

## 🧪 Example Input

Email:

```
There's a meeting today at 8pm
```

Output:

```
Event created in Google Calendar at 20:00
```

---

## ⚠️ Limitations

* AI extraction depends on API quota
* Fallback parser handles only simple patterns
* No duplicate event detection (based on content)
* No timezone detection from email content
* No multi-event extraction in a single email
* No auto-reply system

---

## 🚀 Future Improvements (V2)

* Advanced natural language parsing (e.g., “next Friday evening”)
* Multi-event detection from a single email
* Auto email reply after scheduling
* Priority-based filtering
* Duplicate event detection
* Logging and monitoring system
* Modular architecture

---

## 🧠 Key Concept

This project demonstrates:

> Converting unstructured data (emails) into structured actions (calendar events)

---

## 📌 Version

**v1.0 — Stable Core**

* Fully working pipeline
* Ready for extension into advanced AI agent

---

## 👨‍💻 Author Notes

This version is intentionally kept simple and stable.
All future features should be implemented in **v2** to preserve this baseline.

---
