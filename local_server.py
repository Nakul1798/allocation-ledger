"""Entry point for hosting this app on the local office/campus network.

Unlike `flask run` (a development server not meant to be exposed to other
machines) or `gunicorn` (Linux/macOS only), this uses waitress, which is a
production-grade WSGI server that also runs on Windows -- so this is the
script the local host machine actually runs, kept running (e.g. via Windows
Task Scheduler "at log on", or just left in a terminal window).

Usage:
    python local_server.py            # binds 0.0.0.0:5000

Anyone else on the same network can then open:
    http://<this-machine's-LAN-IP>:5000

Find that IP with `ipconfig` (Windows) and look for "IPv4 Address" under your
Wi-Fi/Ethernet adapter. This does NOT expose the app to the internet -- only
to other devices already on the same local network -- as long as your router
isn't separately configured to forward this port outward.
"""

import os

from dotenv import load_dotenv

# Unlike `flask <command>`, running this file directly with `python
# local_server.py` does not auto-load a local .env file -- so do it
# explicitly here, before anything reads os.environ.
load_dotenv()

from waitress import serve

from app import create_app, db
from app.seed import seed_admin

app = create_app(os.environ.get("FLASK_ENV", "production"))

with app.app_context():
    db.create_all()
    seed_admin()

if __name__ == "__main__":
    host = os.environ.get("LOCAL_HOST", "0.0.0.0")
    port = int(os.environ.get("LOCAL_PORT", "5000"))
    print(f"Serving on http://{host}:{port} (reachable from this network)")
    serve(app, host=host, port=port)
