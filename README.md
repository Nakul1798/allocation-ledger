# Allocation Ledger

A small web app that replicates the three-database thesis-allocation system from
the "Automated Organizational Memory Framework" Notion workspace, as a
self-hosted Flask app with real accounts and a Postgres database:

- **Database A → Stakeholder Directory**: the login/user table. Program
  Director, Professor, Scientific Researcher, Master Student roles; active
  capacity limit; status.
- **Database B → Macro-Projects**: owned by a supervisor, holds a Knowledge
  Vault PDF, and shows a **Completion Velocity** — computed automatically from
  its linked topics rather than typed in.
- **Database C → Micro-Topics Board**: topic title, origin pillar (the same
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

## Deploying to Render (free tier)

This repo includes `render.yaml`, so the fastest path is Render's Blueprint
deploy:

1. Push this repo to GitHub (or GitLab/Bitbucket).
2. In Render, choose **New → Blueprint** and point it at the repo. Render
   reads `render.yaml` and provisions:
   - a **free Postgres database** (`thesis-allocation-db`)
   - a **free web service** running `gunicorn wsgi:app`, wired to that
     database via `DATABASE_URL`, with a random `SECRET_KEY` generated for
     you.
3. When prompted, fill in `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` — these
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
   `init-db` is usually redundant — but running it explicitly is quick and
   confirms the database connection works.)
5. Sign in at the service's `.onrender.com` URL with the admin email/password
   from step 3, then use **Stakeholders → Add stakeholder** to create real
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
  permanent free Postgres elsewhere (e.g. Neon or Supabase both offer one) —
  no code changes needed, just swap the connection string.
- **Web service**: free services spin down after ~15 minutes idle, so the
  first request after a quiet spell takes up to ~60 seconds to wake up. There's
  also a monthly instance-hour cap; if you hit it, Render pauses the service
  until next month. An always-on service starts at $7/mo (Starter plan).
- **Uploaded PDFs**: this app stores Knowledge Vault / final-report PDFs on
  the web service's own local disk. Render's **free** plan has no persistent
  disk, so uploaded files disappear on every deploy or restart (the database
  rows survive; the files don't). This matches what's realistic on a $0
  budget — if you need uploads to survive restarts, either add Render's paid
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
  templates/, static/css/style.css
config.py          env-driven config (dev / test / prod)
wsgi.py            gunicorn entrypoint; creates tables on boot
render.yaml         Render Blueprint (web service + free Postgres)
tests/test_app.py  auth, CSRF, roles, capacity/velocity logic, uploads
```
