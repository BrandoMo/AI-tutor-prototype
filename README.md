# AI Tutor — Proof of Concept

A prototype that generates live, personalized explanations instead of reciting
fixed scripted text. Built to answer one question: can an LLM sitting on top
of a small, structured knowledge base actually behave like a tutor — noticing
a student's repeated mistakes and adjusting its explanations — rather than
just being a fancy playback system?

**Status: working end-to-end.** Tested and confirmed: the tutor references a
student's specific past mistakes (by wording, not just right/wrong) when
generating new explanations for the same concept.

## How it works

1. `app/knowledge/*.json` stores **facts**, not prose — the rule, common
   misconceptions, and worked examples for a concept.
2. When a student asks a question, `app/main.py` pulls those facts plus the
   student's recent attempt history from Redis, and hands both to Gemini.
3. `app/llm_client.py` builds the prompt and calls the Gemini API, which
   generates a fresh explanation shaped by that specific context.
4. `app/state.py` logs each attempt (right/wrong + an optional note on what
   went wrong) to Upstash Redis, so history survives server restarts and
   feeds into future explanations.

## Stack

- **Backend:** FastAPI (Python)
- **LLM:** Google Gemini API (`google-genai` SDK), free tier
- **State storage:** Upstash Redis (free tier, REST API)
- **Frontend:** Plain HTML/CSS/JS, no build step, no framework

Chosen deliberately to run entirely on free tiers for prototyping —
see "Costs" below.

---

## Setup on a fresh machine

### 1. Prerequisites
- Python 3.11+ installed
- A Google account (for Gemini API key)
- An Upstash account (for Redis) — free, no credit card

### 2. Clone/download and install dependencies

```
git clone <your-repo-url>
cd ai-tutor-poc
python -m venv venv
```

Activate the venv:
- **Windows:** `venv\Scripts\activate`
- **Mac/Linux:** `source venv/bin/activate`

You'll know it worked when you see `(venv)` at the start of your terminal prompt.

Then install dependencies:
```
pip install -r requirements.txt
```

If you hit a `HASHES DO NOT MATCH` error, it's almost always a corrupted
download from a flaky connection, not a real problem. Fix with:
```
pip cache purge
pip install -r requirements.txt --no-cache-dir
```

### 3. Get a Gemini API key

1. Go to [aistudio.google.com](https://aistudio.google.com) and sign in
2. Click "Get API key" in the sidebar, then "Create API key"
3. Copy the key immediately — it starts with `AIzaSy...`
4. New keys are auto-restricted by default (Google's current security model),
   so no extra step needed there

### 4. Set up Upstash Redis

1. Go to [console.upstash.com](https://console.upstash.com) and sign up (free, no card)
2. Click "+ Create Database", name it, pick a region close to you
3. On the database page, find the **REST API** section
4. Copy `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` using the
   copy button next to each (not manual text selection — the token is
   masked on screen and manual copy can grab the mask instead of the real value)

### 5. Configure environment variables

Copy `.env.example` to `.env`:
```
cp .env.example .env
```

Fill in the three values — **no quotes, no spaces around `=`**:
```
GEMINI_API_KEY=AIzaSy...
UPSTASH_REDIS_URL=https://your-db.upstash.io
UPSTASH_REDIS_TOKEN=your_token_here
```

### 6. Run it

```
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` in your browser. Ask a question about
equivalent fractions, then use the "Got it right / wrong" buttons to log
attempts.

---

## Known gotchas (learned the hard way)

- **Gemini model names go stale.** Google deprecates free-tier models
  periodically. If you get a `404 ... no longer available to new users`
  error, check [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)
  and update the `model=` string in `app/llm_client.py`. Currently using
  `gemini-3.1-flash-lite` for its generous free-tier quota (1,500 requests/day).
- **`.env` changes need a full restart.** `uvicorn --reload` watches `.py`
  files, not `.env`. After editing `.env`, stop the server fully (`Ctrl+C`)
  and restart it.
- **Free tier quotas are per-model.** If one model's daily quota runs out,
  switching to a different model name gives you a fresh quota immediately.
- **`getaddrinfo failed` errors** are DNS/network issues, not code bugs —
  usually transient on unstable connections (mobile hotspots especially).
- **Activate the venv from an already-open terminal**, not by double-clicking
  `activate.bat` in File Explorer — that opens and immediately closes a new
  window since there's nothing keeping it open afterward.

## What's NOT built yet (Phase 2 ideas)

- Only one concept (`equivalent_fractions`) has a knowledge base entry —
  adding more is just adding more JSON files to `app/knowledge/`
- No real database — Redis stores state as simple JSON blobs, fine for a
  prototype but not for structured querying across many students
- No automatic error-type classification — the student manually types what
  went wrong; a smarter version might have the LLM tag it automatically
- No deployment yet — this runs locally; Render (free tier) is the intended
  next step for hosting

## Costs

Everything above runs on free tiers:
- Gemini API: free tier, no card required
- Upstash Redis: free tier (500K commands/month), no card required
- Hosting (when deployed): Render free tier

The only real cost so far has been data/bandwidth for testing.
