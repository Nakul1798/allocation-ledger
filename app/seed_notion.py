"""One-time import of stakeholders/projects/topics from the source Notion
workspace ("Automated Organizational Memory Framework").

The actual names/emails are NOT hardcoded here (this repo is public) -- they're
passed in at deploy time via the NOTION_SEED_DATA env var (a JSON blob set
only in Render's dashboard, never committed). This function just knows how to
apply that payload to the three tables.

Idempotent and safe to call on every boot:
- No-ops if NOTION_SEED_DATA isn't set.
- No-ops if the import has already run, detected via a macro-project title
  that only this import creates.
"""

import json
import os
import secrets

from app import db
from app.models import MacroProject, MicroTopic, Stakeholder

# A distinctive project title, present exactly once in the source data, used
# purely as an "already imported?" marker -- not meaningful otherwise.
_SENTINEL_PROJECT_TITLE = "Automated Organizational Memory Framework"


def seed_notion_import():
    raw = os.environ.get("NOTION_SEED_DATA")
    if not raw:
        return

    if MacroProject.query.filter_by(title=_SENTINEL_PROJECT_TITLE).first() is not None:
        return  # already imported

    payload = json.loads(raw)

    email_to_stakeholder = {}
    for row in payload.get("stakeholders", []):
        email = row["email"].strip().lower()
        existing = Stakeholder.query.filter_by(email=email).first()
        if existing is None:
            existing = Stakeholder(
                full_name=row["full_name"],
                email=email,
                role=row["role"],
                affiliated_university=row.get("affiliated_university", "SRH"),
                active_capacity_limit=row.get("active_capacity_limit"),
                manual_status=row.get("manual_status", "ACTIVE"),
            )
            # Random, never-shared password: these are directory records carried
            # over from Notion, not ready-to-use logins. Each real person gets
            # actual access later via self-registration (once a Program
            # Director frees up their email) or an admin-issued reset.
            existing.set_password(secrets.token_urlsafe(32))
            db.session.add(existing)
            db.session.flush()
        email_to_stakeholder[email] = existing
    db.session.commit()

    projects = []
    for row in payload.get("macro_projects", []):
        project = MacroProject(
            title=row["title"],
            owner_id=email_to_stakeholder[row["owner_email"]].id,
        )
        db.session.add(project)
        db.session.flush()
        projects.append(project)
    db.session.commit()

    for row in payload.get("micro_topics", []):
        assigned_id = None
        student_email = row.get("assigned_student_email")
        if student_email:
            assigned_id = email_to_stakeholder[student_email].id
        db.session.add(MicroTopic(
            title=row["title"],
            origin_pillar=row["origin_pillar"],
            status=row["status"],
            project_id=projects[row["project_index"]].id,
            assigned_student_id=assigned_id,
        ))
    db.session.commit()
