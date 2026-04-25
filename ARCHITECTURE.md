# Vertica ADHD Coach — Architecture

A self-hosted ADHD coaching agent designed to run on the Vertica homelab. Lives in one Docker container, talks to Claude (or a local model) through the homelab's OpenAI-compatible router, pushes notifications via Home Assistant, and shows a beautiful always-on dashboard on the portrait display.

---

## 1. Why this design

Three hard constraints shaped every decision:

1. **Must survive reboots and power cuts.** This is the one service where "oh I forgot to start it" defeats the entire purpose. It has to be resilient, with state on disk, auto-restart, and graceful handling of missed check-ins.
2. **Must feel good.** The portrait dashboard is the first thing Mert sees when walking past the shelf. If it looks like a Jira board, it loses. If it looks like an iPhone home screen, it wins.
3. **Must be editable by Mert.** Every protocol, every tone rule, every template — has to live in plain files Mert can tweak at 2am without touching Python. The coaching manual (`COACH.md`) is a first-class input, not a hardcoded string.

Three soft constraints:

1. **Small surface area.** One container, SQLite, no message broker, no job queue service. Boring Python. APScheduler in-process. HTMX for live UI updates without a React app.
2. **LLM-agnostic.** Everything routes through `${VERTICA_ROUTER_URL}` which is the OpenAI-compatible endpoint already planned. Swap Claude for a local Llama or Qwen by changing an env var.
3. **Markdown as source of truth, SQLite as cache.** The brain folder (already created at `data/brain/`) is the human-readable record. SQLite is the queryable projection for the dashboard and scheduler. A sync layer keeps them consistent.

---

## 2. System context

```
┌──────────────────────── Vertica homelab ────────────────────────┐
│                                                                 │
│  ┌─────────────┐   ┌────────────┐   ┌──────────────────┐        │
│  │  Ollama     │   │  Claude    │   │  Home Assistant  │        │
│  │ (local LLM) │   │  API       │   │  (notifications) │        │
│  └──────┬──────┘   └─────┬──────┘   └────────┬─────────┘        │
│         │                │                   │                  │
│         └──────┬─────────┘                   │                  │
│                │                             │                  │
│        ┌───────▼────────┐                    │                  │
│        │ vertica-router │                    │                  │
│        │  (OpenAI API)  │                    │                  │
│        └───────┬────────┘                    │                  │
│                │                             │                  │
│        ┌───────▼─────────────────────────────▼─────┐            │
│        │                                           │            │
│        │   vertica-adhd    ← THIS PROJECT          │            │
│        │                                           │            │
│        │  FastAPI + APScheduler + SQLite + HTMX    │            │
│        │                                           │            │
│        └───────┬───────────────────────────────────┘            │
│                │                                                │
│          ┌─────┴──────┬──────────────┐                          │
│          │            │              │                          │
│     ┌────▼────┐  ┌────▼────┐   ┌─────▼─────┐                    │
│     │ Portrait│  │ Mobile  │   │ Markdown  │                    │
│     │ display │  │ (PWA    │   │ brain     │                    │
│     │ (kiosk) │  │ via     │   │ folder on │                    │
│     │         │  │ TS)     │   │ disk      │                    │
│     └─────────┘  └─────────┘   └───────────┘                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

          Push notifications to phone via HA Companion app
          (Critical alerts bypass DND; actionable buttons
           send webhooks back to vertica-adhd)
```

Mert interacts with three surfaces:
- **The portrait display** for ambient awareness — glance at it and know what you're supposed to be doing.
- **The phone** via the HA Companion app — push notifications with actionable buttons ("✓ Done", "Snooze 15m", "Stuck, help"), and the mobile web view (served over Tailscale) for actual conversations with the coach.
- **The shell** for editing `COACH.md` and daily markdown files directly. The app re-reads on every LLM call, so edits take effect immediately.

---

## 3. Data model

SQLite at `data/vertica-adhd.db`. Five tables, kept small on purpose.

### `users`
Single-row table for v1. Holds preferences, timezone, tone overrides, quiet hours, and notification targets.

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
  morning_cron TEXT NOT NULL DEFAULT '0 9 * * *',
  evening_cron TEXT NOT NULL DEFAULT '0 21 * * *',
  quiet_hours_start TEXT DEFAULT '22:30',
  quiet_hours_end TEXT DEFAULT '08:00',
  ha_notify_target TEXT,          -- e.g. 'mobile_app_merts_iphone'
  current_streak INTEGER DEFAULT 0,
  longest_streak INTEGER DEFAULT 0,
  total_xp INTEGER DEFAULT 0,
  level INTEGER DEFAULT 1,
  grace_days_used_this_month INTEGER DEFAULT 0,
  grace_days_month TEXT,
  last_checkin_date TEXT,
  tone_overrides TEXT              -- freeform JSON the LLM reads
);
```

### `days`
One row per calendar day. This is the aggregate record for morning + evening + anything that happened in between.

```sql
CREATE TABLE days (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  date TEXT NOT NULL,               -- 'YYYY-MM-DD'
  energy INTEGER,                   -- 1-10
  meds_taken_at TEXT,
  sleep_hours REAL,
  head_weather TEXT,
  morning_plan_completed_at TEXT,
  evening_review_completed_at TEXT,
  xp_earned INTEGER DEFAULT 0,
  reflection TEXT,
  one_percent_easier_tomorrow TEXT,
  UNIQUE(user_id, date)
);
```

### `tasks`
Top-3 tasks, extras, and ad-hoc tasks live here. Uses `category` to distinguish. `parent_day_id` ties back to a day when it was planned; `completed_on_day_id` ties to the day it actually finished (which can be different — that's how carry-overs work).

```sql
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  parent_day_id INTEGER REFERENCES days(id),
  completed_on_day_id INTEGER REFERENCES days(id),
  text TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('must','should','want','extra','adhoc')),
  estimate_minutes INTEGER,
  actual_minutes INTEGER,
  first_2min_step TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_progress','done','moved','deleted')),
  created_at TEXT NOT NULL,
  completed_at TEXT,
  notes TEXT
);
CREATE INDEX idx_tasks_day ON tasks(parent_day_id);
CREATE INDEX idx_tasks_status ON tasks(user_id, status);
```

### `open_loops`
Things started but not finished. Every row has a mandatory `next_action` — if we can't name the next physical action, the loop is incomplete and rejected.

```sql
CREATE TABLE open_loops (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  text TEXT NOT NULL,
  next_action TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  source_task_id INTEGER REFERENCES tasks(id),
  notes TEXT
);
```

### `wins`
Append-only log. Dopamine bank. Read on the dashboard as a scrolling ticker, and readable back on demand ("show me this week's wins").

```sql
CREATE TABLE wins (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  day_id INTEGER REFERENCES days(id),
  text TEXT NOT NULL,
  xp_awarded INTEGER NOT NULL DEFAULT 1,
  logged_at TEXT NOT NULL
);
```

### `conversations` and `messages`
For coach chat sessions (morning plan, evening review, unstuck conversations). Kept short — old conversations roll up and get deleted after 90 days to keep the DB slim.

```sql
CREATE TABLE conversations (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  day_id INTEGER REFERENCES days(id),
  kind TEXT NOT NULL CHECK(kind IN ('morning','evening','unstuck','adhoc','weekly_sweep')),
  started_at TEXT NOT NULL,
  ended_at TEXT
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
  content TEXT NOT NULL,
  tool_calls TEXT,               -- JSON
  created_at TEXT NOT NULL
);
```

### Markdown sync

For each `days` row, a file at `data/brain/daily/YYYY-MM-DD.md`. The sync module renders the row (plus its tasks/wins/reflection) to markdown every time anything changes, AND parses markdown back on startup so human edits propagate into the DB.

`open_loops.md`, `wins.md`, and `streaks.json` (derived from the `users` table) are written the same way. The existing brain folder we already set up is directly reusable — the app picks up where the files already are.

---

## 4. The five protocols

Each protocol is a Python module in `app/protocols/` and follows the same shape: a scheduler entrypoint, a prompt builder, an LLM driver, and a set of tool handlers. They all use the same underlying coaching manual (`COACH.md`) as the system prompt — no per-protocol prompts drift.

### 4.1 Morning plan
Scheduled at `morning_cron` (default `0 9 * * *`). Sends an HA notification: *"Morning, Mert. Ready to plan?"* with a primary action **Start plan** that deep-links to `/chat/morning`. When Mert opens the chat:
1. System prompt = `COACH.md` + compact context (yesterday's row, open loops, streak).
2. LLM greets, asks energy/meds/sleep, invites a brain dump.
3. Conversational turns. LLM calls tools as conversation unfolds:
   - `add_to_inbox(items)` — brain-dump items
   - `log_energy(score, notes)` — energy/meds/sleep
   - `set_top_3(tasks)` — final top 3 with categories and first-2-min steps
   - `finalize_morning_plan(closing_message)` — closes conversation, awards +3 XP
4. On finalize: DB writes, markdown rewrite, push confirmation notification with closing message + a "✓ Go" button that dismisses, or "Break it smaller" button that reopens chat.

### 4.2 Evening review
Scheduled at `evening_cron` (default `0 21 * * *`). Same pattern, different tools:
- `mark_task_done(id, actual_minutes)` — completes a task
- `defer_task(id, destination)` — `tomorrow | open_loop | break_down | delete`
- `add_win(text, xp)` — prepends to wins.md, awards XP
- `set_reflection(text, one_percent_easier)` — fills day row
- `finalize_evening_review()` — closes, runs streak-update logic

Streak logic runs server-side, not in LLM: if both `morning_plan_completed_at` and `evening_review_completed_at` are set for today, increment `current_streak`. Grace day path: user sends message "grace day" in any chat → server sets a flag, skips streak break.

### 4.3 Unstuck
Triggered by Mert: on the dashboard (button), in chat ("I'm stuck"), or via a notification action ("Stuck, help"). Runs the task-initiation toolkit from `COACH.md` — just-open-the-file, 2-minute rule, body-double, emotional-block probe, shrink-further. No scheduler. Often short (under 5 turns). Writes to conversations table but no other side-effects unless Mert decides to break down a task, which calls `break_down_task(task_id, new_subtasks)`.

### 4.4 Weekly sweep
Scheduled Sunday 8pm, just before evening review. Scans `open_loops` for anything older than 14 days and pushes them into the conversation as candidates to decide on. Tools:
- `close_open_loop(id, resolution)` — `done | deleted | scheduled`
- `set_next_action(id, new_action)` — if the existing one rotted

### 4.5 Ad-hoc chat
Anything not covered above. Mert says "hey" or asks a random question. Protocol = conversational, no forced structure, but the coach has all the context (today's plan, open loops, recent wins). Emits the same tools if anything actionable comes up.

---

## 5. LLM routing

All protocols call the same function:

```python
async def chat(
    messages: list[Message],
    tools: list[Tool] | None = None,
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.7,
) -> ChatResponse:
    # POST to ${VERTICA_ROUTER_URL}/v1/chat/completions
    # Using the official openai-python SDK pointed at the router
    # Router decides local vs cloud based on its own policy
```

The router is the abstraction boundary. In v1 we hard-code a cloud model for the coach because the coaching quality gap between a 7B local model and Claude is still large for this use case. Over time, simpler protocol turns (ack/confirm/tiny nudges) can fall through to a local model — the router does the decision, the app doesn't care.

System prompt is assembled fresh every call:

```python
def build_system_prompt(user: User, protocol: str) -> str:
    return dedent(f"""
    {read_coach_manual()}

    ---

    Today is {today_str}. The user is {user.name}.
    Protocol: {protocol}.
    Current streak: {user.current_streak}. Level {user.level}, {user.total_xp} XP.
    Tone overrides: {user.tone_overrides or '(none)'}.

    Available tools: {tool_names}. Use them when an action is warranted.
    Do not invent your own approach — follow the coaching manual above.
    """)
```

`read_coach_manual()` reads `data/brain/COACH.md` every call. Edits are live.

---

## 6. Notifications via Home Assistant

v1 uses HA's `notify.mobile_app_<device>` service. Flow:

```
vertica-adhd  ──(POST /api/services/notify/mobile_app_merts_iphone)──▶  Home Assistant
                                                                              │
                                                                              ▼
                                                                     ┌─────────────────┐
                                                                     │  HA Companion   │
                                                                     │  app on phone   │
                                                                     │  (push via APNS │
                                                                     │   or FCM)       │
                                                                     └────────┬────────┘
                                                                              │
                                          (user taps action button)           │
                                                                              ▼
                                                                     ┌─────────────────┐
                                                                     │  Webhook to     │
                                                                     │  vertica-adhd   │
                                                                     │  /webhook/ha    │
                                                                     └─────────────────┘
```

Notification payload includes a `data.actions` array:

```json
{
  "title": "Evening review",
  "message": "Quick end-of-day — 5 min. Ready?",
  "data": {
    "url": "https://vertica.tailnet.ts.net/chat/evening",
    "push": { "interruption-level": "time-sensitive" },
    "actions": [
      { "action": "open_chat", "title": "Start review" },
      { "action": "snooze_30", "title": "Snooze 30m" },
      { "action": "skip_today", "title": "Skip today" }
    ]
  }
}
```

When Mert taps an action, HA fires a `mobile_app_notification_action` event. A simple HA automation POSTs to `https://vertica.tailnet.ts.net/webhook/ha` with the action name. The app handles three actions:
- `open_chat` — no-op, HA already deep-links via `url`
- `snooze_30` — reschedules the protocol for +30m
- `skip_today` — logs a skipped day (no shame, just data)

The one HA automation needed is a 10-line YAML snippet; documented in `README.md`.

**Critical alerts path**: for the morning plan, `interruption-level: active` is fine. For a "you haven't moved in 2 hours since the plan" nudge, we use `interruption-level: time-sensitive` to bypass focus modes when Mert has opted in.

---

## 7. Portrait dashboard UX

The 24" portrait display runs Chromium in kiosk mode pointing at `https://vertica.local/`. The page is full-screen, no chrome, auto-refresh via HTMX polling every 20s.

### Layout (1200×1920, portrait)

```
┌─────────────────────────────────────┐
│                                     │
│     ██╗  ██████╗  ██╗██████╗        │  ← massive clock (220px type)
│     ██║ ██╔═████╗██╔╝╚════██╗       │    date below in 48px
│     ██║ ██║██╔██║██║   █████╔╝      │
│     ██║ ████╔╝██║██║   ╚═══██╗      │
│     ██║ ╚██████╔╝╚██║ ██████╔╝      │
│     ╚═╝  ╚═════╝  ╚═╝ ╚═════╝       │
│                                     │
│     Thursday, April 23              │
│     ─────────────────────────────   │
│                                     │
│     TODAY'S TOP 3                   │
│                                     │
│     ● MUST  grant app → 60%         │
│       first: open doc, find §3      │
│                                     │
│     ○ SHOULD  reply to Ana          │
│                                     │
│     ○ WANT   sketch logo idea       │
│                                     │
│     ─────────────────────────────   │
│                                     │
│     RIGHT NOW                       │
│     Working: grant app              │
│     Started 10:14  ·  elapsed 34m   │
│                                     │
│     ─────────────────────────────   │
│                                     │
│     DAY 4  •  LEVEL 2  •  83 XP     │
│     ━━━━━━━━━░░  83 / 200           │
│                                     │
│     ─────────────────────────────   │
│                                     │
│     recent wins                     │
│     · closed the inbox loop         │
│     · ate lunch before 2pm          │
│     · sent that email finally       │
│     · did monday's top 3 all        │
│                                     │
└─────────────────────────────────────┘
```

Aesthetic rules: deep charcoal background (#0e0e12), warm off-white text (#f5efe6), one accent color for "MUST" (#ff6b5a), subtle hairline separators, generous whitespace. Think "Braun designed an Apple TV screensaver for a monk's cell." No gradients, no rounded-corner cards everywhere, no emoji in headings. Progress bar uses block characters, not SVG fancy stuff.

### Modes

- **Ambient** (default): read-only, glance-readable from across the room. Auto-hides the cursor. Polls every 20s for state changes.
- **Interactive** (tap/click): dimmed overlay appears with buttons — start chat, log win, I'm stuck, complete task. Goes back to ambient after 30s of no interaction.
- **Focus**: during a scheduled focus block, the whole screen becomes a giant timer. Optional, triggered manually.

---

## 8. Mobile UX

The mobile view at `https://vertica.tailnet.ts.net/m/` is a PWA-installable chat interface. Three tabs at the bottom:
- **Chat** — current conversation with the coach
- **Today** — the same data as the dashboard, compacted to mobile
- **Loops** — the open-loops list with a big "+" button

Installed to the home screen, it feels native. Works offline-read (cached last state), writes queued and sent when back online.

---

## 9. Repo layout

```
vertica-adhd/
├── README.md                    # setup, compose-up, HA automation, env vars
├── ARCHITECTURE.md              # this file
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── .gitignore
├── app/
│   ├── main.py                  # FastAPI app + lifespan
│   ├── config.py                # pydantic-settings env loader
│   ├── db.py                    # SQLite engine + session
│   ├── models.py                # SQLModel tables
│   ├── llm.py                   # openai client → router
│   ├── coach.py                 # prompt assembly, tool registry
│   ├── scheduler.py             # APScheduler + protocol jobs
│   ├── notifications.py         # HA REST client
│   ├── brain_sync.py            # markdown <-> DB
│   ├── xp.py                    # XP / streak / level engine
│   ├── protocols/
│   │   ├── morning.py
│   │   ├── evening.py
│   │   ├── unstuck.py
│   │   ├── weekly_sweep.py
│   │   └── adhoc.py
│   ├── routers/
│   │   ├── dashboard.py         # GET / — portrait view
│   │   ├── mobile.py            # GET /m, /m/chat, /m/today, /m/loops
│   │   ├── chat.py              # POST /chat/:kind, SSE stream
│   │   ├── api.py               # JSON API for integrations
│   │   └── webhooks.py          # POST /webhook/ha
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── mobile/
│       │   ├── index.html
│       │   ├── chat.html
│       │   ├── today.html
│       │   └── loops.html
│       └── partials/
│           ├── clock.html
│           ├── top3.html
│           ├── streak.html
│           ├── right_now.html
│           └── wins_ticker.html
├── static/
│   ├── css/
│   │   └── dashboard.css
│   └── js/
│       └── htmx.min.js
├── migrations/
│   └── 001_initial.sql
├── data/                        # volume-mounted, gitignored except .gitkeep
│   ├── vertica-adhd.db
│   └── brain/
│       ├── COACH.md
│       ├── README.md
│       ├── streaks.json
│       ├── open-loops.md
│       ├── wins.md
│       └── daily/
│           └── YYYY-MM-DD.md
└── scripts/
    ├── seed.py                  # create user row, load existing brain/
    └── migrate.py               # apply SQL migrations on boot
```

---

## 10. Deployment

`docker-compose.yml` fragment to paste into the homelab's main compose file:

```yaml
services:
  vertica-adhd:
    build: ./vertica-adhd
    container_name: vertica-adhd
    restart: unless-stopped
    ports:
      - "8088:8000"
    environment:
      - VERTICA_ROUTER_URL=http://vertica-router:8080
      - VERTICA_ROUTER_API_KEY=${VERTICA_ROUTER_API_KEY}
      - HA_URL=http://homeassistant:8123
      - HA_TOKEN=${HA_LONG_LIVED_TOKEN}
      - HA_NOTIFY_TARGET=mobile_app_merts_iphone
      - PUBLIC_URL=https://vertica.tailnet.ts.net
      - USER_NAME=Mert
      - USER_TIMEZONE=America/Los_Angeles
    volumes:
      - ./vertica-adhd/data:/data
    networks:
      - vertica
    depends_on:
      - vertica-router
      - homeassistant
```

Caddy fragment (already in the main plan) to expose it:

```
vertica.tailnet.ts.net {
  reverse_proxy vertica-adhd:8000
}
```

Chromium kiosk on the display:
```bash
chromium --kiosk --app=http://localhost:8088 \
         --noerrdialogs --disable-infobars \
         --check-for-update-interval=31536000
```

---

## 11. Extensibility

Two hooks are designed in from day one:

1. **New protocols**: drop a file in `app/protocols/` implementing the protocol interface (`run_scheduled`, `run_on_demand`, `tools`). Register it in `app/protocols/__init__.py`. The chat router picks it up automatically.

2. **New tools for the LLM**: add a function to `app/coach.py`'s `@tool` registry. It becomes callable from any conversation. This is how we'd add things like "start a pomodoro", "play a focus playlist via HA", "turn the portrait display red during crunch time".

Over time, three natural expansions:
- **Integrations** via HA: "did I forget to plug in my car?" — HA knows. "Is the coffee machine on?" — HA knows. The coach can pull ambient context without building integrations itself.
- **Local voice**: a Whisper container + Piper TTS in the homelab means the portrait display could be speak-to. Cheap mic array, wake-word via openWakeWord, and the coach is now a talking pillar in the room.
- **Multi-user (productization)**: the `users` table already supports it. The notification target and brain folder become per-user. A small admin page manages households.

---

## 12. Non-goals for v1

- No calendar integration (yet). Calendars are a swamp of OAuth and timezone bugs and not the bottleneck for ADHD.
- No native mobile app. PWA is good enough and works through Tailscale without App Store friction.
- No multi-tenancy. One user. Rip it out of the schema if you want — it's there for the day you productize.
- No analytics dashboards beyond what's in the mobile "Today" view. If you find yourself spending 20 minutes looking at your ADHD stats, that's itself the bug.

End of architecture.
