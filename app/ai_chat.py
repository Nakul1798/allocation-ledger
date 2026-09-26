"""AI Assistant -- optional, natural-language Q&A over the current data.

Disabled unless ANTHROPIC_API_KEY is set in the environment (see
.env.example). No external request is ever made until that key is present,
so this module is safe to ship even before anyone has signed up for a key.
"""
import os

import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-3-5-haiku-20241022"
MAX_ROWS = 40


def is_configured():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _build_context(user):
    """A compact, role-scoped summary of the current data for the model to read.

    Mirrors the app's own access rules: a student only sees their own
    topics, a supervisor sees their own projects/topics, and only a Program
    Director sees everything. Imported lazily to avoid a circular import
    with app.models at module load time.
    """
    from app.models import MacroProject, MicroTopic, Stakeholder

    lines = [f"You are answering questions for {user.full_name} ({user.role_label})."]

    if user.is_admin:
        stakeholders = Stakeholder.query.order_by(Stakeholder.full_name).limit(MAX_ROWS).all()
        lines.append("\nStakeholders:")
        for s in stakeholders:
            limit = s.active_capacity_limit if s.active_capacity_limit is not None else "-"
            lines.append(f"- {s.full_name} | {s.role_label} | {s.display_status} | load {s.active_load}/{limit}")

        projects = MacroProject.query.order_by(MacroProject.title).limit(MAX_ROWS).all()
        lines.append("\nMacro-projects:")
        for p in projects:
            lines.append(f"- {p.title} | owner {p.owner.full_name} | {p.completion_velocity}% complete")

        topics = MicroTopic.query.order_by(MicroTopic.title).limit(MAX_ROWS).all()
        lines.append("\nMicro-topics:")
        for t in topics:
            assignee = t.assigned_student.full_name if t.assigned_student else "unassigned"
            lines.append(f"- {t.title} | project {t.project.title} | {t.status} | {assignee}")

    elif user.is_supervisor:
        projects = MacroProject.query.filter_by(owner_id=user.id).order_by(MacroProject.title).all()
        lines.append(f"\nYour macro-projects ({len(projects)}):")
        for p in projects:
            lines.append(f"- {p.title} | {p.completion_velocity}% complete")
            for t in p.topics[:MAX_ROWS]:
                assignee = t.assigned_student.full_name if t.assigned_student else "unassigned"
                lines.append(f"    - {t.title} | {t.status} | {assignee}")
        limit = user.active_capacity_limit if user.active_capacity_limit is not None else "no limit set"
        lines.append(f"\nYour active load: {user.active_load}/{limit}")

    else:  # student
        topics = MicroTopic.query.filter_by(assigned_student_id=user.id).all()
        lines.append(f"\nYour topics ({len(topics)}):")
        for t in topics:
            lines.append(f"- {t.title} | project {t.project.title} | {t.status}")

    return "\n".join(lines)


def answer_question(question, user):
    """Returns {"answer": str} or {"error": str} -- never raises."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "error": "The AI assistant isn't configured yet. Add ANTHROPIC_API_KEY to your "
            ".env file and restart the server to enable it."
        }

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    context = _build_context(user)
    system_prompt = (
        "You are a concise assistant embedded in the Allocation Ledger app, a thesis-allocation "
        "tracker. Answer only using the data provided below; if the answer isn't in it, say so. "
        "Keep answers short -- a few sentences or a short list.\n\n" + context
    )

    try:
        response = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 512,
                "system": system_prompt,
                "messages": [{"role": "user", "content": question}],
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"error": f"Couldn't reach the AI service: {exc}"}

    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            pass
        return {"error": f"AI service error ({response.status_code}). {detail}".strip()}

    data = response.json()
    text_parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
    answer = "\n".join(part for part in text_parts if part).strip()
    if not answer:
        return {"error": "The AI service returned an empty answer."}
    return {"answer": answer}
