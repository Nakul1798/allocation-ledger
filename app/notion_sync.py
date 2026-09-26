"""Repeatable, live sync from the source Notion workspace ("Automated
Organizational Memory Framework") into this app's own database.

This is the automated counterpart to the one-time `notion_import.py`: instead
of a hardcoded snapshot, it calls the Notion REST API directly every time it
runs (typically once a day, from Windows Task Scheduler or `cron`) and
reconciles the three tables against the three source databases.

Design rules, carried over from the earlier one-time import and from a real
incident earlier in this project (a stakeholder's own role got clobbered by
an automated script): this sync is deliberately conservative.

- It reads the Notion integration token from the `NOTION_TOKEN` environment
  variable only. That variable lives in this machine's local `.env` file,
  which is git-ignored -- it is never read by the web app itself, never sent
  to a browser, and never seen by anyone who logs into the dashboard. That is
  what "abstracts the API authentication": one server-held credential, used
  only by this background job.
- It matches existing rows by a stored Notion page id first, then by email
  (for stakeholders) as a fallback for the very first run.
- For a stakeholder that already exists, it NEVER changes `role` or the
  password. Capacity limit and active/inactive status are the only fields it
  will update on an existing account. If a role looks out of date, that is
  reported under "needs attention" for a human (a Program Director) to fix by
  hand from the app's own Stakeholders screen.
- For a brand-new stakeholder it creates the account with a random password
  (never typed anywhere, never emailed by this script) and prints it exactly
  once in the run's report for a Program Director to pass along.
- Project/topic titles and stakeholder names are cleaned of stray Notion
  formatting artifacts (`**bold**` markers, literal `<br>` tags) that show up
  in a few source rows.
- Two known junk/test rows in the source Stakeholder Directory ("TEST",
  "TEST PROf") are always skipped.
- Before making any change, it backs up the three tables' current contents to
  a timestamped JSON file so a bad run can be undone by hand.

Run it with:  flask notion-sync
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from app import db
from app.models import MacroProject, MicroTopic, Stakeholder

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DATABASE_STAKEHOLDERS = "f0ae3052-885c-8377-8515-011077c8c338"
DATABASE_PROJECTS = "466e3052-885c-83f7-8a94-01dc625a14d4"
DATABASE_TOPICS = "d5fe3052-885c-82ef-863b-815c23a319cb"

ROLE_MAP = {
    "Program Director": "program_director",
    "Professor": "professor",
    "Scientific Researcher": "researcher",
    "Master Student": "student",
}
STATUS_MAP = {
    "ACTIVE": "ACTIVE",
    "FULL CAPACITY": "ACTIVE",  # computed in-app; not a distinct stored state
    "IN ACTIVE": "IN ACTIVE",
}
JUNK_NAMES = {"TEST", "TEST PROF"}

_MD_MARKERS = re.compile(r"\*\*")
_BR_TAGS = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = _BR_TAGS.sub(" ", value)
    value = _MD_MARKERS.sub("", value)
    return _WHITESPACE.sub(" ", value).strip()


def normalize_page_id(page_id: str) -> str:
    return page_id.replace("-", "").lower()


class NotionAuthError(RuntimeError):
    pass


def _notion_headers():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise NotionAuthError(
            "NOTION_TOKEN is not set. Add it to this machine's local .env file "
            "(never commit it) and re-run."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def query_database(database_id: str) -> list[dict]:
    """Fetch every row of a Notion database via the classic query endpoint."""
    headers = _notion_headers()
    results = []
    payload = {"page_size": 100}
    while True:
        resp = requests.post(
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return results


# --- Notion property extractors ---------------------------------------------

def prop_title(page: dict, name: str) -> str:
    parts = page["properties"].get(name, {}).get("title", [])
    return "".join(p.get("plain_text", "") for p in parts)


def prop_email(page: dict, name: str) -> str | None:
    return page["properties"].get(name, {}).get("email")


def prop_select(page: dict, name: str) -> str | None:
    sel = page["properties"].get(name, {}).get("select")
    return sel["name"] if sel else None


def prop_status(page: dict, name: str) -> str | None:
    st = page["properties"].get(name, {}).get("status")
    return st["name"] if st else None


def prop_number(page: dict, name: str):
    return page["properties"].get(name, {}).get("number")


def prop_relation_ids(page: dict, name: str) -> list[str]:
    rels = page["properties"].get(name, {}).get("relation", [])
    return [normalize_page_id(r["id"]) for r in rels]


@dataclass
class SyncReport:
    started_at: datetime = field(default_factory=datetime.utcnow)
    stakeholders_created: list[str] = field(default_factory=list)
    stakeholders_updated: list[str] = field(default_factory=list)
    stakeholders_skipped_junk: list[str] = field(default_factory=list)
    new_credentials: list[tuple[str, str]] = field(default_factory=list)  # (email, password)
    projects_created: list[str] = field(default_factory=list)
    projects_updated: list[str] = field(default_factory=list)
    topics_created: list[str] = field(default_factory=list)
    topics_updated: list[str] = field(default_factory=list)
    needs_attention: list[str] = field(default_factory=list)

    def as_html(self) -> str:
        def li(items):
            return "".join(f"<li>{i}</li>" for i in items) or "<li><em>none</em></li>"

        creds_rows = "".join(
            f"<tr><td>{email}</td><td><code>{pw}</code></td></tr>"
            for email, pw in self.new_credentials
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Notion sync report {self.started_at:%Y-%m-%d %H:%M} UTC</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
h2{{border-bottom:1px solid #ddd;padding-bottom:.3rem;margin-top:2rem}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}}
code{{background:#f4f4f4;padding:.1rem .3rem;border-radius:3px}}
.needs-attention{{background:#fff8e1}}
</style></head><body>
<h1>Notion sync report</h1>
<p>Run started {self.started_at:%Y-%m-%d %H:%M UTC}.</p>

<h2>New stakeholder accounts &amp; passwords (shown once)</h2>
<p>Pass these along to each person directly. They will not appear in any later report.</p>
<table><tr><th>Email</th><th>Temporary password</th></tr>{creds_rows}</table>

<h2>Stakeholders</h2>
<p>Created: {len(self.stakeholders_created)} &middot; Updated (capacity/status only): {len(self.stakeholders_updated)} &middot; Skipped as junk/test rows: {len(self.stakeholders_skipped_junk)}</p>
<ul>{li(self.stakeholders_created)}</ul>

<h2>Macro-Projects</h2>
<p>Created: {len(self.projects_created)} &middot; Updated: {len(self.projects_updated)}</p>

<h2>Micro-Topics</h2>
<p>Created: {len(self.topics_created)} &middot; Updated: {len(self.topics_updated)}</p>

<h2 class="needs-attention">Skipped / needs attention</h2>
<p>Nothing here was changed automatically -- review and fix by hand in the app.</p>
<ul>{li(self.needs_attention)}</ul>
</body></html>"""


def _backup_tables(backups_dir: Path):
    backups_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "stakeholders": [
            {c.name: getattr(s, c.name) for c in Stakeholder.__table__.columns if c.name != "password_hash"}
            for s in Stakeholder.query.all()
        ],
        "macro_projects": [
            {c.name: getattr(p, c.name) for c in MacroProject.__table__.columns}
            for p in MacroProject.query.all()
        ],
        "micro_topics": [
            {c.name: getattr(t, c.name) for c in MicroTopic.__table__.columns}
            for t in MicroTopic.query.all()
        ],
    }

    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = backups_dir / f"backup-{stamp}.json"
    path.write_text(json.dumps(snapshot, indent=2, default=_default))

    # Keep only the last 30 backups.
    backups = sorted(backups_dir.glob("backup-*.json"))
    for old in backups[:-30]:
        old.unlink()


def run_notion_sync(project_root: Path | None = None) -> SyncReport:
    project_root = project_root or Path(__file__).resolve().parent.parent
    report = SyncReport()

    _backup_tables(project_root / "backups")

    # --- Stage 1: Stakeholder Directory ---
    stakeholder_pages = query_database(DATABASE_STAKEHOLDERS)
    notion_id_to_local_id: dict[str, int] = {}

    for page in stakeholder_pages:
        notion_id = normalize_page_id(page["id"])
        name = clean_text(prop_title(page, "Full Name"))
        email_raw = prop_email(page, "Contact Email")
        email = (email_raw or "").strip().lower()

        if name.upper() in JUNK_NAMES or not email:
            report.stakeholders_skipped_junk.append(f"{name or '(no name)'} ({email_raw!r})")
            continue

        notion_role = prop_select(page, "Role")
        role = ROLE_MAP.get(notion_role)
        notion_status = prop_status(page, "Status")
        manual_status = STATUS_MAP.get(notion_status, "ACTIVE")
        affiliated_university = prop_select(page, "Affiliated University") or "SRH"
        active_capacity_limit = prop_number(page, "Active Capacity Limit")

        existing = Stakeholder.query.filter_by(notion_page_id=notion_id).first()
        if existing is None:
            existing = Stakeholder.query.filter_by(email=email).first()

        if existing is not None:
            existing.notion_page_id = notion_id
            existing.active_capacity_limit = active_capacity_limit
            existing.manual_status = manual_status
            if role and role != existing.role:
                report.needs_attention.append(
                    f"Stakeholder '{name}' <{email}>: Notion role is '{notion_role}' but the app "
                    f"has '{existing.role_label}'. Role was left unchanged -- update it by hand if "
                    f"this is a real promotion/change."
                )
            report.stakeholders_updated.append(f"{name} <{email}>")
            notion_id_to_local_id[notion_id] = existing.id
            continue

        if role is None:
            report.needs_attention.append(
                f"Stakeholder '{name}' <{email}>: no recognized Role in Notion ({notion_role!r}) -- "
                f"account not created. Add a Role in Notion and re-run."
            )
            continue

        new_password = secrets.token_urlsafe(12)
        stakeholder = Stakeholder(
            full_name=name,
            email=email,
            role=role,
            affiliated_university=affiliated_university,
            active_capacity_limit=active_capacity_limit,
            manual_status=manual_status,
            notion_page_id=notion_id,
        )
        stakeholder.set_password(new_password)
        db.session.add(stakeholder)
        db.session.flush()
        notion_id_to_local_id[notion_id] = stakeholder.id
        report.stakeholders_created.append(f"{name} <{email}> [{role}]")
        report.new_credentials.append((email, new_password))

    db.session.commit()

    # --- Stage 2: Macro-Projects ---
    project_pages = query_database(DATABASE_PROJECTS)
    project_notion_id_to_local_id: dict[str, int] = {}

    for page in project_pages:
        notion_id = normalize_page_id(page["id"])
        title = clean_text(prop_title(page, "Project Title")) or "(untitled project)"
        owner_ids = prop_relation_ids(page, "Owner")
        owner_local_id = notion_id_to_local_id.get(owner_ids[0]) if owner_ids else None

        if owner_local_id is None:
            report.needs_attention.append(
                f"Project '{title}': no resolvable Owner in Notion -- skipped this run."
            )
            continue

        existing = MacroProject.query.filter_by(notion_page_id=notion_id).first()
        if existing is not None:
            existing.title = title
            existing.owner_id = owner_local_id
            report.projects_updated.append(title)
        else:
            existing = MacroProject(title=title, owner_id=owner_local_id, notion_page_id=notion_id)
            db.session.add(existing)
            db.session.flush()
            report.projects_created.append(title)
        project_notion_id_to_local_id[notion_id] = existing.id

    db.session.commit()

    # --- Stage 3: Micro-Topics Board ---
    topic_pages = query_database(DATABASE_TOPICS)

    for page in topic_pages:
        notion_id = normalize_page_id(page["id"])
        title = clean_text(prop_title(page, "Topic Title")) or "(untitled topic)"
        origin_pillar = prop_select(page, "Origin Pillar")
        status = prop_status(page, "Status") or "OPEN"
        project_ids = prop_relation_ids(page, "Database B: Macro-Projects")
        project_local_id = project_notion_id_to_local_id.get(project_ids[0]) if project_ids else None
        student_ids = prop_relation_ids(page, "Assigned Student")
        assigned_student_id = notion_id_to_local_id.get(student_ids[0]) if student_ids else None

        if project_local_id is None:
            report.needs_attention.append(
                f"Topic '{title}': no resolvable parent Macro-Project in Notion -- skipped this run."
            )
            continue
        if not origin_pillar:
            report.needs_attention.append(f"Topic '{title}': missing Origin Pillar in Notion -- skipped this run.")
            continue
        if student_ids and assigned_student_id is None:
            report.needs_attention.append(
                f"Topic '{title}': Assigned Student in Notion does not match any synced stakeholder."
            )

        existing = MicroTopic.query.filter_by(notion_page_id=notion_id).first()
        if existing is not None:
            existing.title = title
            existing.origin_pillar = origin_pillar
            existing.status = status
            existing.project_id = project_local_id
            existing.assigned_student_id = assigned_student_id
            report.topics_updated.append(title)
        else:
            db.session.add(MicroTopic(
                title=title,
                origin_pillar=origin_pillar,
                status=status,
                project_id=project_local_id,
                assigned_student_id=assigned_student_id,
                notion_page_id=notion_id,
            ))
            report.topics_created.append(title)

    db.session.commit()
    return report


def write_report(report: SyncReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"report-{stamp}.html"
    path.write_text(report.as_html())
    return path
