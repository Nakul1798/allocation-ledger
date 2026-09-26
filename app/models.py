from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db


def utcnow():
    # Naive UTC on purpose: SQLite (used in tests/local dev) drops tzinfo on
    # round-trip, so every DateTime column here is naive-UTC and every comparison
    # in the app must also use naive-UTC (see auth.py) to stay consistent across
    # both SQLite and Postgres.
    return datetime.utcnow()


# --- Controlled vocabularies (mirrors the "select" options in the Notion source) ---

ROLES = ["program_director", "professor", "researcher", "student"]
ROLE_LABELS = {
    "program_director": "Program Director",
    "professor": "Professor",
    "researcher": "Scientific Researcher",
    "student": "Master Student",
}
SUPERVISOR_ROLES = {"program_director", "professor", "researcher"}

MANUAL_STATUSES = ["ACTIVE", "IN ACTIVE"]

ORIGIN_PILLARS = [
    "1-Scientific Databases",
    "2-Strategic Directives",
    "3-Active Professor Projects",
    "4-Research Candidate Sub-Task",
]

TOPIC_STATUSES = ["OPEN", "In progress", "Completed"]


class Stakeholder(UserMixin, db.Model):
    """Database A: Stakeholder Directory â also doubles as the login/user table."""

    __tablename__ = "stakeholders"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="student")
    affiliated_university = db.Column(db.String(120), default="SRH")
    active_capacity_limit = db.Column(db.Integer, nullable=True)
    manual_status = db.Column(db.String(20), nullable=False, default="ACTIVE")

    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Set only by the Notion sync job (app/notion_sync.py); lets a repeat sync
    # reliably match this row back to its Notion page, including when two
    # rows share the same title. Manually-created accounts leave this null.
    notion_page_id = db.Column(db.String(32), unique=True, nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utcnow)

    owned_projects = db.relationship(
        "MacroProject", back_populates="owner", foreign_keys="MacroProject.owner_id"
    )
    assigned_topics = db.relationship(
        "MicroTopic", back_populates="assigned_student", foreign_keys="MicroTopic.assigned_student_id"
    )

    # --- auth helpers ---
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def is_supervisor(self):
        return self.role in SUPERVISOR_ROLES

    @property
    def is_admin(self):
        return self.role == "program_director"

    # --- capacity / status logic (mirrors the thesis's automated capacity flagging) ---
    @property
    def active_load(self):
        if not self.is_supervisor:
            return 0
        count = 0
        for project in self.owned_projects:
            count += sum(1 for t in project.topics if t.status == "In progress")
        return count

    @property
    def is_over_capacity(self):
        if self.active_capacity_limit is None or not self.is_supervisor:
            return False
        return self.active_load >= self.active_capacity_limit

    @property
    def display_status(self):
        if self.manual_status == "IN ACTIVE":
            return "IN ACTIVE"
        if self.is_over_capacity:
            return "FULL CAPACITY"
        return "ACTIVE"

    def __repr__(self):
        return f"<Stakeholder {self.email} ({self.role})>"


class MacroProject(db.Model):
    """Database B: Macro-Projects."""

    __tablename__ = "macro_projects"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("stakeholders.id"), nullable=False)
    knowledge_vault_filename = db.Column(db.String(400), nullable=True)
    knowledge_vault_original_name = db.Column(db.String(400), nullable=True)
    notion_page_id = db.Column(db.String(32), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    owner = db.relationship("Stakeholder", back_populates="owned_projects", foreign_keys=[owner_id])
    topics = db.relationship(
        "MicroTopic", back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def completion_velocity(self):
        """Percentage of linked topics marked Completed â computed, not stored."""
        total = len(self.topics)
        if total == 0:
            return 0
        completed = sum(1 for t in self.topics if t.status == "Completed")
        return round((completed / total) * 100)

    def __repr__(self):
        return f"<MacroProject {self.title!r}>"


class MicroTopic(db.Model):
    """Database C: Micro-Topics Board."""

    __tablename__ = "micro_topics"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(400), nullable=False)
    origin_pillar = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="OPEN")
    project_id = db.Column(db.Integer, db.ForeignKey("macro_projects.id"), nullable=False)
    assigned_student_id = db.Column(db.Integer, db.ForeignKey("stakeholders.id"), nullable=True)
    final_pdf_filename = db.Column(db.String(400), nullable=True)
    final_pdf_original_name = db.Column(db.String(400), nullable=True)
    notion_page_id = db.Column(db.String(32), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    project = db.relationship("MacroProject", back_populates="topics")
    assigned_student = db.relationship(
        "Stakeholder", back_populates="assigned_topics", foreign_keys=[assigned_student_id]
    )

    def __repr__(self):
        return f"<MicroTopic {self.title!r}>"
