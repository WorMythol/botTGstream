# StreamBot — Telegram Stream Notification Bot

Multi-platform Telegram bot that monitors YouTube, Twitch, and VK for live streams and sends unified notifications to configured channels.

---

## Features

- **Multi-platform monitoring**: YouTube (quota-aware), Twitch (rate-limit-aware), VK
- **Unified notifications**: One message per streamer aggregating all live platforms
- **Smart cooldown**: Avoids duplicate alerts if a stream restarts within 30 minutes
- **Live notification editing**: When a new platform comes online mid-stream, existing notifications are edited — not spammed
- **Role-based access**: Owner → Admin → Streamer hierarchy
- **Viewer threshold filtering**: Per-channel minimum viewer count suppresses small streams
- **System health dashboard**: API quota status, last poll times, error rates
- **Test notifications**: Send test messages before activating a streamer
- **Full stream history & analytics**: Per-streamer and global statistics
- **FastAPI-ready service layer**: All business logic decoupled from the bot for future VK Mini App integration

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL 14+
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Platform API credentials (see below)

### 2. Install

```bash
git clone <repo>
cd botTGstream
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

Generate an encryption key for stored API credentials:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Paste the output as `ENCRYPTION_KEY` in `.env`.

### 4. Database setup

Create the database:
```sql
CREATE DATABASE streambot;
CREATE USER botuser WITH PASSWORD 'botpassword';
GRANT ALL PRIVILEGES ON DATABASE streambot TO botuser;
```

Run migrations:
```bash
alembic upgrade head
```

### 5. Run

```bash
python -m bot.main
```

Or for development with auto-reload:
```bash
watchmedo auto-restart --patterns="*.py" --recursive -- python -m bot.main
```

---

## Platform API Setup

### YouTube Data API v3
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable "YouTube Data API v3"
3. Create an API Key → restrict to YouTube Data API v3
4. Set `YOUTUBE_API_KEY` in `.env`

**Quota note**: Default quota is 10,000 units/day. `search.list` costs 100 units; `videos.list` costs 1 unit. The bot minimizes quota by using `videos.list` once a live stream is known.

### Twitch API
1. Go to [Twitch Dev Console](https://dev.twitch.tv/console/apps)
2. Register a new application (set OAuth Redirect URL to `http://localhost`)
3. Note the Client ID and generate a Client Secret
4. Set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` in `.env`

### VK API
1. Go to [VK Apps](https://vk.com/apps?act=manage)
2. Create a "Standalone" application
3. Go to Settings → copy the Service Access Key
4. Set `VK_ACCESS_TOKEN` in `.env`

---

## Bot Commands Reference

### All users
| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Show available commands |
| `/cancel` | Cancel current operation |

### Streamer role
| Command | Description |
|---------|-------------|
| `/my_streamers` | List assigned streamers |
| `/edit_template` | Edit notification message template |
| `/my_stats` | Personal streamer statistics |
| `/global_stats` | Global leaderboard |
| `/stream_history` | Recent stream history |

### Admin role (includes Streamer commands)
| Command | Description |
|---------|-------------|
| `/add_streamer` | Add new streamer (wizard) |
| `/list_streamers` | Manage all streamers |
| `/add_channel` | Register a Telegram channel |
| `/list_channels` | List registered channels |
| `/assign_channel` | Link streamer → channel with template |
| `/test_notification` | Send test notification to channel |
| `/poll_now` | Manually trigger stream check |
| `/health` | System health dashboard |
| `/update_api_key` | Update platform API credentials |
| `/stream_stats` | Global statistics |
| `/manage_user` | Add/modify user roles |

### Owner role (includes Admin commands)
| Command | Description |
|---------|-------------|
| `/add_admin` | Grant admin role |
| `/remove_admin` | Revoke admin role |
| `/list_admins` | List all admins |

---

## Message Template Variables

Templates use Jinja2 syntax. Available variables:

| Variable | Description |
|----------|-------------|
| `{{ streamer_name }}` | Streamer display name |
| `{{ stream_title }}` | Current stream title |
| `{{ viewer_count }}` | Current viewer count (formatted: 1.2K, 3.4M) |
| `{{ platform_links }}` | List of `{platform, url}` objects |

**Example template:**
```jinja
🔴 *{{ streamer_name }}* is LIVE!

📺 {{ stream_title }}
👥 {{ viewer_count | format_viewers }} viewers

{% for link in platform_links %}▶️ [{{ link.platform }}]({{ link.url }})
{% endfor %}
```

---

## Architecture

```
bot/              — aiogram handlers, FSM states, keyboards, middleware
services/         — pure business logic (platform-agnostic, FastAPI-ready)
  stream_service     — stream lifecycle, cooldown, multi-platform aggregation
  notification_service — send/edit/delete via injected callables
  streamer_service   — CRUD + pause/resume + assignments
  analytics_service  — stats queries
  template_service   — Jinja2 rendering
integrations/     — YouTube, Twitch, VK API clients
scheduler/        — APScheduler polling engine (per-platform jobs)
db/
  models.py        — SQLAlchemy ORM (platform-agnostic schema)
  repositories/    — data access layer
migrations/       — Alembic migrations
```

### Service layer API contract

All services accept an `AsyncSession` and return plain Python objects. To expose them via FastAPI:

```python
from fastapi import FastAPI, Depends
from db.database import get_session_dependency
from services.streamer_service import StreamerService

app = FastAPI()

@app.get("/streamers")
async def list_streamers(session = Depends(get_session_dependency)):
    return await StreamerService(session).list_streamers()
```

### Database schema highlights

- `streamers` — platform-agnostic streamer entity
- `platform_accounts` — per-platform IDs (YouTube channel, Twitch login, VK group)
- `streams` — one session per broadcast, spans all concurrent platforms
- `platform_streams` — per-platform data within a stream session
- `notifications` — tracks every sent message with `telegram_message_id` for edit/delete
- `streamer_channel_assignments` — configures which channels a streamer posts to, with per-assignment templates and viewer thresholds

---

## Additional Features Implemented

### 1. Smart Cooldown + Notification Editing
When a stream restarts within 30 minutes of ending (configurable via `STREAM_COOLDOWN_SECONDS`), the existing notification is reactivated and edited rather than sending a new one. This prevents spam during technical difficulties. When a new platform goes live mid-session (e.g. streamer starts a Twitch stream while already live on YouTube), all existing notifications for that session are edited to include the new platform link.

### 2. System Health Dashboard (`/health`)
Admins can check real-time API status: YouTube quota remaining, last poll times per platform, rate-limit windows, and aggregate stream statistics. Quota exhaustion automatically notifies all admins.

### 3. Viewer Threshold Filtering
Per assignment (streamer ↔ channel pair), admins can set a minimum viewer count. Notifications for streams below the threshold are suppressed. This prevents notification fatigue from tiny test streams. Configured during `/assign_channel` setup.

---

## Environment Variables

See `.env.example` for all variables with descriptions.

---

## Production Checklist

- [ ] Set `LOG_FORMAT=json` and ship logs to aggregator
- [ ] Use `alembic upgrade head` (not `init_db()`) for schema management  
- [ ] Set PostgreSQL connection pool size appropriate to load
- [ ] Monitor YouTube quota daily — set up alerts at 80% threshold
- [ ] Store `.env` secrets in a secrets manager (AWS Secrets Manager, Vault, etc.)
- [ ] Run behind a process supervisor (systemd, Docker, PM2)
- [ ] Set up database backups
