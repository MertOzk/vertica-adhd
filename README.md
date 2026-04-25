# vertica-adhd

A self-hosted ADHD coaching agent. Runs on your homelab in one container. All data stays on your box.

- A FastAPI service in a single Docker container.
- A SQLite DB + a `data/brain/` folder of plain-text markdown files you can read or edit by hand anytime.
- A scheduler that pings your phone via Home Assistant at morning-plan and evening-review times, with actionable buttons.
- An always-on portrait dashboard at `http://<homelab>:8088/` — designed for a vertically-mounted 24" display.
- A mobile PWA at `http://<homelab>:8088/m/` over Tailscale or LAN.
- Pluggable LLM: speaks OpenAI-compatible API; works with `vertica-router`, LiteLLM, Ollama, vLLM, or any other compatible endpoint.

Where your data lives: everything — coaching history, tasks, wins, streaks — is written to `~/vertica/adhd/data/` on your homelab as SQLite + plain markdown. Nothing goes to any cloud. The only outbound call is to your LLM endpoint for coach replies.

## Install (one line)

On the homelab, with Docker already installed:

```bash
curl -fsSL https://raw.githubusercontent.com/MertOzk/vertica-adhd/main/install.sh | bash
```

The installer:

1. Verifies `docker` and `docker compose` are present.
2. Creates `~/vertica/adhd/` with a `data/` subfolder.
3. Asks 6–7 short questions (name, timezone, LLM endpoint, Home Assistant token, etc.).
4. Pulls the published image and starts the service.
5. Prints the dashboard URL.

Re-running it is safe — it won't overwrite an existing `.env`.

### Authenticating to the image registry (one-time)

The Docker image is published to GitHub Container Registry as a **private** package.
Before the installer can pull it, log Docker into `ghcr.io` once per machine:

1. Create a GitHub Personal Access Token (classic) with the `read:packages` scope:
   <https://github.com/settings/tokens/new?scopes=read:packages&description=ghcr-pull>
2. Copy the token, then run:
   ```bash
   docker login ghcr.io -u MertOzk
   # paste the token as the password
   ```
3. Now run the installer.

The credential is saved in `~/.docker/config.json` and reused by `docker compose pull` from
then on. If you skip this step, the installer will detect the auth failure and print these
same instructions before exiting cleanly.

### Update later

```bash
cd ~/vertica/adhd && docker compose pull && docker compose up -d
```

### Uninstall

```bash
cd ~/vertica/adhd && docker compose down
rm -rf ~/vertica/adhd      # wipes data too — back up first if you want history
```

## After install

### Point the portrait display at it

Chromium kiosk (drop into `systemd` or `.desktop` autostart on the homelab):

```bash
chromium --kiosk --app=http://localhost:8088 \
         --noerrdialogs --disable-infobars \
         --check-for-update-interval=31536000
```

### Wire up Home Assistant (for phone notifications)

Install the HA Companion app on your phone, then in HA's `configuration.yaml` (or the Automations UI):

```yaml
automation:
  - alias: "ADHD coach — relay notification actions"
    trigger:
      - platform: event
        event_type: mobile_app_notification_action
    action:
      - service: rest_command.vertica_adhd_webhook
        data:
          action: "{{ trigger.event.data.action }}"

rest_command:
  vertica_adhd_webhook:
    url: "http://vertica-adhd:8000/webhook/ha"
    method: POST
    content_type: "application/json"
    payload: '{"action": "{{ action }}"}'
```

Find your `HA_NOTIFY_TARGET` in HA → **Developer Tools → Services**, look for `notify.mobile_app_<device>`.

## Daily use

1. **Morning:** phone buzzes — "Morning plan, ready?" Tap to start. 2–5 turns of conversation set today's top 3 with a 2-minute first step for each.
2. **Throughout the day:** glance at the portrait display to know what you're doing. Tap to mark tasks done, log wins, or open an "I'm stuck" chat.
3. **Evening:** phone buzzes — "Evening review". 2–5 turns: log what moved, handle unfinished, XP and streak tick up.
4. **Editing the coach:** open `~/vertica/adhd/data/brain/COACH.md` in any editor. Changes apply on the next call. No restart.

## What gets stored, where

Everything sits in `~/vertica/adhd/data/` on your homelab:

```
data/
  app.db                   # SQLite — tasks, days, conversations, XP
  brain/
    COACH.md               # ← edit to change coaching behavior live
    daily/YYYY-MM-DD.md    # one markdown file per day, human-readable
    open-loops.md          # things you owe yourself
    wins.md                # append-only win log
    streaks.json           # current streak / level / XP
```

Want to back it up? `tar czf adhd-backup.tgz ~/vertica/adhd/data` and stash the tarball wherever you like.

---

## Build from source (devs only)

Most users want the install line above. If you want to hack on the code:

```bash
git clone https://github.com/MertOzk/vertica-adhd
cd vertica-adhd
cp .env.example .env
# edit .env
docker compose up -d --build
```

Hot-reload outside Docker:

```bash
pip install -e '.[dev]'
DATA_DIR=./dev-data uvicorn app.main:app --reload
```

Architecture and design rationale: see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Troubleshooting

- **"No user row"**: lifespan hook seeds on first boot. If you see this in a partial:
  ```bash
  docker compose exec vertica-adhd python scripts/seed.py
  ```
- **Dashboard doesn't refresh**: the `static/js/htmx.min.js` shipped in the repo is a placeholder. The published Docker image includes the real one; if you built locally, fetch it:
  ```bash
  curl -sL https://unpkg.com/htmx.org@2.0.3/dist/htmx.min.js -o static/js/htmx.min.js
  ```
- **Notifications don't arrive**: `HA_TOKEN` must be a long-lived access token. Test with curl:
  ```bash
  curl -H "Authorization: Bearer $HA_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"message":"test"}' \
       http://homeassistant:8123/api/services/notify/mobile_app_merts_iphone
  ```
- **Scheduled times feel off**: cron runs in `user.timezone` from the DB. Set `USER_TIMEZONE` in `.env` and recreate the container, or edit the `users` row directly.

## Roadmap

1. Real markdown → DB parse on startup (we write markdown now; we don't yet re-read human edits on boot).
2. Focus-mode overlay on the portrait display (giant timer, one task).
3. HA ambient context: weather, calendar density, door/lock sensors.
4. Voice loop: openWakeWord + Whisper + Piper turns the display into a talking pillar.
5. Multi-user. Schema already supports it; needs per-user brain paths and notify targets.
