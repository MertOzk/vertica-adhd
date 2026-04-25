-- Initial schema. Applied idempotently on boot by scripts/migrate.py.

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
  morning_cron TEXT NOT NULL DEFAULT '0 9 * * *',
  evening_cron TEXT NOT NULL DEFAULT '0 21 * * *',
  quiet_hours_start TEXT DEFAULT '22:30',
  quiet_hours_end TEXT DEFAULT '08:00',
  ha_notify_target TEXT,
  current_streak INTEGER DEFAULT 0,
  longest_streak INTEGER DEFAULT 0,
  total_xp INTEGER DEFAULT 0,
  level INTEGER DEFAULT 1,
  grace_days_used_this_month INTEGER DEFAULT 0,
  grace_days_month TEXT,
  last_checkin_date TEXT,
  tone_overrides TEXT
);

CREATE TABLE IF NOT EXISTS days (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  date TEXT NOT NULL,
  energy INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_days_date ON days(user_id, date);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  parent_day_id INTEGER REFERENCES days(id),
  completed_on_day_id INTEGER REFERENCES days(id),
  text TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('must','should','want','extra','adhoc')),
  estimate_minutes INTEGER,
  actual_minutes INTEGER,
  first_2min_step TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','in_progress','done','moved','deleted')),
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_day ON tasks(parent_day_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(user_id, status);

CREATE TABLE IF NOT EXISTS open_loops (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  text TEXT NOT NULL,
  next_action TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  source_task_id INTEGER REFERENCES tasks(id),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS wins (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  day_id INTEGER REFERENCES days(id),
  text TEXT NOT NULL,
  xp_awarded INTEGER NOT NULL DEFAULT 1,
  logged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  day_id INTEGER REFERENCES days(id),
  kind TEXT NOT NULL CHECK(kind IN ('morning','evening','unstuck','adhoc','weekly_sweep')),
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
  content TEXT NOT NULL,
  tool_calls TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
