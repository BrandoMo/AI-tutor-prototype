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
4. Each concept file also has **practice problems with answer keys**.
   `app/grading.py` checks the student's answer deterministically (no LLM)
   and diagnoses wrong answers from the shape of the mistake — e.g. `11/12`
   for "2/3 = ?/12" added 9 to top and bottom, so it's tagged with the
   "adding instead of multiplying" misconception.
5. Students get **one retry**. After a first wrong answer the tutor gives a
   hint but is told not to reveal the answer; after a second wrong answer
   the answer is shown and the tutor walks through it. Some mistakes (an
   equivalent fraction in the wrong form, like `4/6` for "?/12") get an
   instant message from the grader instead of an LLM call.
6. `app/state.py` logs each graded attempt (problem, try, answer,
   right/wrong, matched misconception) to Upstash Redis, so history survives
   server restarts and feeds into future explanations.

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

Open `http://127.0.0.1:8000` in your browser. Answer the practice
problems — they're checked automatically, and a wrong answer gets a hint
and a second try. You can also ask the tutor questions directly.

To add problems, append to `practice_problems` in the concept's JSON file.
Each needs a `prompt`, an `answer`, an `answer_format` (`"fraction"`, which
must match exactly, or `"yes_no"`), and numbers describing the problem so
wrong answers can be diagnosed:

| `kind`     | Fields                                               | Example prompt                                  |
|------------|------------------------------------------------------|-------------------------------------------------|
| `fill`     | `given`, `target` (`{"denominator": n}` or `{"numerator": n}`) | Find a fraction equivalent to 2/3 with denominator 12. |
| `simplify` | `given`                                              | Simplify 6/9 to its simplest form.             |
| `compare`  | `given`, `other`                                     | Is 2/5 equivalent to 4/10? (yes or no)          |

For an odd wrong answer the rules miss, add `"wrong_answers": {"7/12":
"<misconception id>"}` to that problem. The test suite checks that every
problem's numbers, prompt and answer key agree.

### 7. Run the tests (optional)

```
pip install -r requirements-dev.txt
python -m pytest
node --test tests/markdown.test.js
```

Tests stub out Redis and Gemini, so they run offline with no API keys.
The second line needs Node.js 18+ and tests the chat's Markdown formatter.

GitHub Actions runs both on every pull request and every push to `main`
(see `.github/workflows/tests.yml`); results show up as a check on the PR.

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
## Costs

Everything above runs on free tiers:
- Gemini API: free tier, no card required
- Upstash Redis: free tier (500K commands/month), no card required
- Hosting (when deployed): Render free tier

The only real cost so far has been data/bandwidth for testing.
