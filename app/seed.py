import os

from app import db
from app.models import Stakeholder


def seed_admin():
    """Create the first Program Director account.

    Reads ADMIN_NAME / ADMIN_EMAIL / ADMIN_PASSWORD from the environment so it can
    run non-interactively during a Render deploy; falls back to interactive prompts
    for local use. No-ops if any Program Director already exists.
    """
    existing = Stakeholder.query.filter_by(role="program_director").first()
    if existing:
        print(f"A Program Director already exists ({existing.email}); nothing to do.")
        return

    name = os.environ.get("ADMIN_NAME")
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")

    if not (name and email and password):
        print("Set up the first Program Director account.")
        name = name or input("Full name: ").strip()
        email = email or input("Email: ").strip()
        import getpass

        password = password or getpass.getpass("Password (min 10 chars): ")

    if len(password) < 10:
        print("Password must be at least 10 characters. Aborting.")
        return

    admin = Stakeholder(
        full_name=name,
        email=email.strip().lower(),
        role="program_director",
        affiliated_university="SRH",
        manual_status="ACTIVE",
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    print(f"Program Director account created for {admin.email}.")
