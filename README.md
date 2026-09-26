# Allocation Ledger

A small web app that replicates the three-database thesis-allocation system from
the "Automated Organizational Memory Framework" Notion workspace, as a
self-hosted Flask app with real accounts and a Postgres database:

- **Database A â Stakeholder Directory**: the login/user table. Program
  Director, Professor, Scientific Researcher, Master Student roles; active
  capacity limit; status.
- **Database B â Macro-Projects**: owned by a supervisor, holds a Knowledge
  Vault PDF, and shows a **Completion Velocity** â computed automatically from
  its linked topics rather than typed in.
- **Database C â Micro-Topics Board**: topic title, origin pillar (the same
  four values as the source: Scientific Databases / Strategic Directives /
  Active Professor Projects / Research Candidate Sub-Task), status, assigned
  student, final PDF upload.

The automated pieces from the original thesis are reproduced as live logic
rather than a snapshot: a supervisor's status flips to **FULL CAPACITY**
automatically once their count of "In progress" topics reaches their capacity
limit, and each project's completion velocity is recalculated from its topics
on every view.

## Security

- Passwords are hashed with Werkzeug's `generate_password_hash` (never stored
  in plain text).
- CSRF protection (Flask-WTF) on every form.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- Login is throttled: 5 failed attempts locks the account for 15 minutes.
  Wrong-password and unknown-email show the same generic error, so a login
  attempt can't be used to find out which emails have accounts.
- Role-based access: Program Directors manage everyone; Professors/Researchers
  manage only their own projects and topics; Students see their own
  assignment. Every write route checks this server-side, not just in the UI.
- Uploaded files are restricted to PDF, capped at 10 MB, renamed to a random
  filename on disk, and only ever served back through an authenticated route
  (never a raw static URL).
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Content-Security-Policy`, `Referrer-Policy`) are set on every response.

## Local setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then edit .env
export $(grep -v '^#' .env | xargs)   # or use `flask run` with python-dotenv

flask init-db              # creates tables (SQLite file under instance/ by default)
flask seed-admin           # creates the first Program Director account
flask run                  # http://127.0.0.1:5000
```

Run the test suite with `pytest`.

## Local network hosting (recommended for this project)

Instead of a publicly reachable Render service, you can run this app on one
machine on your own office/campus network, with a background job that keeps
its data in sync with the source Notion workspace. Nobody who logs into the
dashboard ever needs a personal Notion token -- only the one machine running
the sync job holds it, in a local `.env` file that is never committed.

1. **One-time setup on the host machine**
   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt

   cp .env.example .env
   ```
   Edit `.env`:
   - Set a real `SECRET_KEY` (see the comment in `.env.example` for how to generate one).
   - Leave `DATABASE_URL` blank -- this uses the local SQLite file under `instance/`.
   - Set `SESSION_COOKIE_SECURE=false` (this deployment is plain `http://` on your LAN, not `https://`).
   - Set `NOTION_TOKEN` to an integration secret from https://www.notion.so/my-integrations,
     after sharing the three databases (Stakeholder Directory, Macro-Projects,
     Micro-Topics Board) with that integration via each database's "..." menu â Connections.
   - Set `ADMIN_NAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` for the first Program Director login.

2. **Create the database and the first account, then run the first sync**
   ```bash
   flask init-db
   flask seed-admin
   flask notion-sync
   ```
   `notion-sync` prints a report path (`reports/report-<timestamp>.html`) --
   open it. New stakeholder accounts each get a random password shown **once**
   in that report; pass those along to the people they belong to.

3. **Start serving the dashboard on the network**
   ```bash
   python local_server.py
   ```
   Find this machine's LAN address with `ipconfig` (Windows) or `ifconfig`/`ip addr`
   (macOS/Linux) and share `http://<that address>:5000` with your colleagues on
   the same network. This is **not** reachable from the public internet unless
   your router is separately configured to forward that port.

4. **Schedule the daily sync** (Windows Task Scheduler)
   - Action: `Start a program`
   - Program: the full path to `.venv\Scripts\flask.exe` (or `python.exe` with
     `-m flask`)
   - Arguments: `notion-sync`
   - Start in: this project's folder (so it finds `.env`)
   - Trigger: Daily, 06:00 (your local time)

   Optionally also add a trigger to start `python local_server.py` at log-on,
   so the dashboard comes back up automatically after a restart.

5. **If something looks wrong after a sync**, the most recent file in
   `backups/` has the full prior state of all three tables (minus password
   hashes) as plain JSON, for restoring a row by hand or asking for a one-off
   restore script.

`backups/`, `reports/`, and `.env` all stay out of git (see `.gitignore`) --
none of this ever reaches the public repo.

## Deploying to Render (free tier)

This repo includes `render.yaml`, so the fastest path is Render's Blueprint
deploy:

1. Push this repo to GitHub (or GitLab/Bitbucket).
2. In Render, choose **New â Blueprint** and point it at the repo. Render
   reads `render.yaml` and provisions:
   - a **free Postgres database** (`thesis-allocation-db`)
   - a **free web service** running `gunicorn wsgi:app`, wired to that
     database via `DATABASE_URL`, with a random `SECRET_KEY` generated for
     you.
3. When prompted, fill in `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` â these
   are only used once, to seed the first account.
4. After the first deploy finishes, open the service's **Shell** tab (or use
   `render exec`) and run:
   ```bash
   flask init-db
   flask seed-admin
   ```
   `init-db` creates the tables; `seed-admin` reads the three `ADMIN_*` env
   vars you set in step 3 and creates the first Program Director login.
   (`wsgi.py` also calls `db.create_all()` on boot as a safety net, so
   `init-db` is usually redundant â but running it explicitly is quick and
   confirms the database connection works.)
5. Sign in at the service's `.onrender.com` URL with the admin email/password
   from step 3, then use **Stakeholders â Add stakeholder** to create real
   accounts for professors and students, and retire the admin password you
   used for seeding if you'd rather not keep it around.

If you'd rather click through the dashboard manually instead of using the
blueprint: create a **Postgres** free instance first, then a **Web Service**
free instance from this repo with build command `pip install -r
requirements.txt` and start command `gunicorn wsgi:app`, and add `SECRET_KEY`
and `DATABASE_URL` (the internal connection string Render shows on the
database's page) as environment variables.

### Free-tier limits worth knowing

- **Database**: Render's free Postgres is 1 GB and **expires 30 days after
  creation** (14-day grace period to upgrade before it's deleted). Fine for a
  demo or a semester pilot; for anything longer-lived, either upgrade the
  database ($7/mo Starter) before day 30, or point `DATABASE_URL` at a
  permanent free Postgres elsewhere (e.g. Neon or Supabase both offer one) â
  no code changes needed, just swap the connection string.
- **Web service**: free services spin down after ~15 minutes idle, so the
  first request after a quiet spell takes up to ~60 seconds to wake up. There's
  also a monthly instance-hour cap; if you hit it, Render pauses the service
  until next month. An always-on service starts at $7/mo (Starter plan).
- **Uploaded PDFs**: this app stores Knowledge Vault / final-report PDFs on
  the web service's own local disk. Render's **free** plan has no persistent
  disk, so uploaded files disappear on every deploy or restart (the database
  rows survive; the files don't). This matches what's realistic on a $0
  budget â if you need uploads to survive restarts, either add Render's paid
  Disk add-on, or point uploads at an external object store (e.g. an S3-
  compatible bucket) instead of local disk.

## Project layout

```
app/
  __init__.py      app factory, security headers, CLI commands
  models.py        Stakeholder / MacroProject / MicroTopic + capacity logic
  auth.py          login / logout / change password
  main.py          dashboard + CRUD for all three "databases" + file downloads
  forms.py         WTForms (CSRF-protected)
  decorators.py    role-based access control
  utils.py         safe PDF upload/delete helpers
  notion_sync.py   `flask notion-sync` -- repeatable live sync from Notion
  templates/, static/css/style.css
config.py          env-driven config (dev / test / prod)
wsgi.py            gunicorn entrypoint (Render); creates tables on boot
local_server.py    waitress entrypoint for LAN hosting (see "Local network hosting")
render.yaml         Render Blueprint (web service + free Postgres)
tests/test_app.py  auth, CSRF, roles, capacity/velocity logic, uploads
```
