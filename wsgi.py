import os

from app import create_app, db

app = create_app(os.environ.get("FLASK_ENV", "production"))

# Ensure tables exist on boot. This is intentionally simple (no migration engine
# required) so the app comes up cleanly on a fresh free-tier Postgres database;
# swap for `flask db upgrade` if you introduce Flask-Migrate migrations later.
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
