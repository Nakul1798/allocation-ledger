"""Rule-based automations -- no external services, no API key required.

Each function inspects the current data and returns short "notices" that
surface on the dashboard. Nothing here is stored or scheduled: notices are
computed fresh on every dashboard load, which mirrors the spirit of
Notion's Automations without needing a rules-authoring UI. Supervisor
capacity flags already have their own table on the dashboard, so this
module deliberately covers the gaps: fully-finished projects, topics that
have stalled, and open topics nobody has picked up yet.
"""
from datetime import datetime, timedelta

STALE_TOPIC_DAYS = 30


def build_dashboard_notices(projects, topics):
    """Returns a list of {"level": "success"|"info"|"warning", "text": str}."""
    notices = []

    # Macro-projects where every linked topic is Completed -- ready to close out.
    for project in projects:
        if project.topics and project.completion_velocity == 100:
            notices.append({
                "level": "success",
                "text": f'"{project.title}" has all its topics marked Completed.',
            })

    # Topics that have sat "In progress" for a while without an update.
    cutoff = datetime.utcnow() - timedelta(days=STALE_TOPIC_DAYS)
    for topic in topics:
        if topic.status == "In progress" and topic.updated_at and topic.updated_at < cutoff:
            days = (datetime.utcnow() - topic.updated_at).days
            notices.append({
                "level": "warning",
                "text": f'"{topic.title}" has been In progress for {days} days with no update.',
            })

    # Open topics with nobody assigned yet.
    unassigned_open = [t for t in topics if t.status == "OPEN" and not t.assigned_student_id]
    if unassigned_open:
        names = ", ".join(f'"{t.title}"' for t in unassigned_open[:5])
        more = f" and {len(unassigned_open) - 5} more" if len(unassigned_open) > 5 else ""
        notices.append({
            "level": "info",
            "text": f"{len(unassigned_open)} open topic(s) have no student assigned yet: {names}{more}.",
        })

    return notices
