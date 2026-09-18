import os

from app import create_app, db
from app.seed import seed_admin

app = create_app(os.environ.get("FLASK_ENV", "production"))

# Ensure tables exist on boot. This is intentionally simple (no migration engine
# required) so the app comes up cleanly on a fresh free-tier Postgres database;
# swap for `flask db upgrade` if you introduce Flask-Migrate migrations later.
#
# Also seed the first Program Director account here, since Render's free tier
# has no shell/exec access to run `flask seed-admin` manually after deploy.
# seed_admin() is idempotent (no-ops once any Program Director exists), so it's
# safe to call on every boot.
with app.app_context():
    db.create_all()
    seed_admin()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
