"""One-time admin-only import of the Notion "Automated Organizational Memory
Framework" workspace data (stakeholders, macro-projects, micro-topics) into
this app's database.

Unlike the earlier migration-endpoint idea, this is a normal authenticated
admin feature: it sits behind @admin_required (a real login + CSRF, the same
trust boundary as every other admin screen in this app), not a bypass token.
It creates its own secure random passwords for new stakeholder accounts
server-side (never typed into any form by anyone) and shows each one exactly
once on the results page for the admin to pass along.

Safe to run more than once: stakeholders are matched/reused by email, and
projects/topics are skipped if a matching title already exists under the
same owner/project.
"""

import secrets

from flask import Blueprint, render_template_string
from flask_wtf import FlaskForm
from wtforms import SubmitField

from app import db
from app.decorators import admin_required
from app.models import MacroProject, MicroTopic, Stakeholder

notion_import_bp = Blueprint("notion_import", __name__)


class ConfirmImportForm(FlaskForm):
    submit = SubmitField("Run import")


# --- The dataset, pulled from the Notion workspace on 2026-09-21. -----------
# Keys (s1, p1, ...) are only used to wire up relationships during import;
# they aren't stored anywhere.

STAKEHOLDERS = [
    {"key": "s1", "full_name": "Dr.Prof. Stephan Szuppa", "email": "Stephan.Szuppa@srh-hochschulen.de",
     "role": "program_director", "affiliated_university": "SRH", "active_capacity_limit": 4, "manual_status": "ACTIVE"},
    {"key": "s2", "full_name": "Prof. Dr. Osvaldo Romero", "email": "osvaldo.romero@srh.de",
     "role": "program_director", "affiliated_university": "SRH", "active_capacity_limit": 3, "manual_status": "ACTIVE"},
    {"key": "s3", "full_name": "Dr. Katia Caraballoso Granado", "email": "Katia.CaraballosoGranado@srh-hochschulen.de",
     "role": "professor", "affiliated_university": "SRH", "active_capacity_limit": 5, "manual_status": "ACTIVE"},
    {"key": "s4", "full_name": "Prof Thomas Pfeiffer", "email": "Thomas.Pfeiffer@srh-hochschulen.de",
     "role": "researcher", "affiliated_university": "SRH", "active_capacity_limit": 2, "manual_status": "ACTIVE"},
    {"key": "s5", "full_name": "Prof. Dr.-Ing. Patrick Teuffel", "email": "Patrick.Teuffel@srh-hochschulen.de",
     "role": "professor", "affiliated_university": "SRH", "active_capacity_limit": 5, "manual_status": "ACTIVE"},
    {"key": "s6", "full_name": "Prof. Matthias Raab", "email": "Matthias.Raab.extern@srh-hochschulen.de",
     "role": "professor", "affiliated_university": "SRH", "active_capacity_limit": 5, "manual_status": "ACTIVE"},
    {"key": "s7", "full_name": "Gangesh Varma", "email": "Gangesh.PappuVarma@stud.srh-campus-berlin.de",
     "role": "student", "affiliated_university": "SRH", "active_capacity_limit": None, "manual_status": "ACTIVE"},
    {"key": "s8", "full_name": "Prof. Live Demo", "email": "prof.Demo@demo.com",
     "role": "professor", "affiliated_university": "SRH", "active_capacity_limit": 2, "manual_status": "ACTIVE"},
    {"key": "s9", "full_name": "Student Live Demo 01", "email": "Student@demo.com",
     "role": "student", "affiliated_university": "SRH", "active_capacity_limit": None, "manual_status": "IN ACTIVE"},
    {"key": "s10", "full_name": "Student Live Demo 02", "email": "Student02@demo.com",
     "role": "student", "affiliated_university": "SRH", "active_capacity_limit": None, "manual_status": "IN ACTIVE"},
]

PROJECTS = [
    {"key": "p1", "title": "Big Data & AI, Industry 4.0", "owner_key": "s3"},
    {"key": "p2", "title": "Big Data & AI, Industry 4.0 (II)", "owner_key": "s3"},
    {"key": "p3", "title": "Renewable Energy & Water Waste", "owner_key": "s3"},
    {"key": "p4", "title": "Industry 4.0 & Smart Building Technology", "owner_key": "s3"},
    {"key": "p5", "title": "Mobility & Automotive, Industry 4.0, Big Data & AI", "owner_key": "s3"},
    {"key": "p6", "title": "Industry 4.0", "owner_key": "s3"},
    {"key": "p7", "title": "Mobility & Automotive", "owner_key": "s3"},
    {"key": "p8", "title": "Big Data & AI", "owner_key": "s3"},
    {"key": "p9", "title": "Thesis Manegement Tool", "owner_key": "s3"},
    {"key": "p10", "title": "Automated Organizational Memory Framework", "owner_key": "s3"},
    {"key": "p11", "title": "Masters Thesis conceptional, practical", "owner_key": "s4"},
    {"key": "p12", "title": "Masters Thesis conceptional, design", "owner_key": "s4"},
    {"key": "p13", "title": "Smart Building Technologies", "owner_key": "s1"},
    {"key": "p14", "title": "Smart Building Technology", "owner_key": "s5"},
    {"key": "p15", "title": "Smart Architecture", "owner_key": "s6"},
    {"key": "p16", "title": "Project/Thesis Topic", "owner_key": "s2"},
    {"key": "p17", "title": "Demo Research Stream", "owner_key": "s8"},
]

TOPICS = [
    {"title": "AI-Assisted Research Support Platforms", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p1"},
    {"title": "Artificial Intelligence for Smart Facility and Service Management", "origin_pillar": "3-Active Professor Projects", "status": "In progress", "project_key": "p5", "assigned_student_key": "s7"},
    {"title": "Digital Twins and Intelligent Decision Support Systems", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p6"},
    {"title": "Smart Mobility, Sustainable Tourism and Digital Visitor Experience", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p7"},
    {"title": "International Digital Collaboration and Innovation Ecosystems", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p8"},
    {"title": "Smart Digital Platforms for Coworking and Collaborative Innovation Spaces", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p4"},
    {"title": "Open Data, Artificial Intelligence and Sustainable Development", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p3"},
    {"title": "Research Intelligence and Knowledge Management Systems", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p2"},
    {"title": "Automated Organizational Memory Frameworks", "origin_pillar": "3-Active Professor Projects", "status": "Completed", "project_key": "p9", "assigned_student_key": "s7"},
    {"title": "System Security Architecture", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p10"},
    {"title": "Automated NLP Topic Generation", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p10"},
    {"title": "Electro power consumption from Hydropower-Laboratories' Turbine.", "origin_pillar": "4-Research Candidate Sub-Task", "status": "OPEN", "project_key": "p11"},
    {"title": "A low-tech heat exchanger / dryer device", "origin_pillar": "4-Research Candidate Sub-Task", "status": "OPEN", "project_key": "p12"},
    {"title": "Comparision of Construction Materials w.r.t. their Carbon Footprint and LCA", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p13"},
    {"title": "GDP Growth independent Economic Models", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p13"},
    {"title": "Future Roles and Competencies of BIM Professionals in an AI-Driven Construction Industry", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p13"},
    {"title": "Cybersecurity and Privacy Risks of BIM-Enabled Autonomous Buildings", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p13"},
    {"title": "Development of a flexibility score for different use scenarios for empty buildings, with background research on reasons for deconstruction/demolition vs. building new (building mortality index), within a defined region (e.g. Germany/EU/Asia)", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p14"},
    {"title": "Extended LCA emission accounting for the design phase", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p14"},
    {"title": "Analysis of longevity of existing building materials/components as a basis for reuse, including different LCA scenarios of different building components", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p14"},
    {"title": "Evaluation of the Design for Deconstruction/Disassembly (DfD) of existing building elements", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p14"},
    {"title": "Integration of pictures in software like BIM to prepare AI-aided evaluation of materials", "origin_pillar": "3-Active Professor Projects", "status": "OPEN", "project_key": "p14"},
    {"title": "Recycling of old building materials (concrete, construction debris), recovery of steel and stone", "origin_pillar": "1-Scientific Databases", "status": "OPEN", "project_key": "p15"},
    {"title": "Recovery of salvaged building components (stairs, windows, radiators)", "origin_pillar": "1-Scientific Databases", "status": "OPEN", "project_key": "p15"},
    {"title": "Reducing building component thicknesses", "origin_pillar": "1-Scientific Databases", "status": "OPEN", "project_key": "p15"},
    {"title": "Review of calculation software for building physics analysis/building simulation regarding compliance with thermal standards.", "origin_pillar": "1-Scientific Databases", "status": "OPEN", "project_key": "p15"},
    {"title": "Refurbishment of salvaged building components or items (staircases, sanitary facilities, built-in elements/fittings, etc.)", "origin_pillar": "1-Scientific Databases", "status": "OPEN", "project_key": "p15"},
    {"title": "Circular Economy Business Models for MSMEs", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p16"},
    {"title": "Material Flow Analysis as a Decision-Support Tool for Urban Circular Economy Planning.", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p16"},
    {"title": "Decentralised Water Reuse Systems for Peri-Urban and Rural Communities.", "origin_pillar": "2-Strategic Directives", "status": "OPEN", "project_key": "p16"},
    {"title": "Demo Project 01", "origin_pillar": "3-Active Professor Projects", "status": "Completed", "project_key": "p17", "assigned_student_key": "s9"},
    {"title": "Demo Project 02", "origin_pillar": "3-Active Professor Projects", "status": "Completed", "project_key": "p17", "assigned_student_key": "s10"},
]


@notion_import_bp.route("/admin/notion-import", methods=["GET", "POST"])
@admin_required
def notion_import():
    form = ConfirmImportForm()
    results = None

    if form.validate_on_submit():
        key_to_id = {}
        new_credentials = []
        skipped_stakeholders = []

        for s in STAKEHOLDERS:
            existing = Stakeholder.query.filter_by(email=s["email"].lower()).first()
            if existing:
                key_to_id[s["key"]] = existing.id
                skipped_stakeholders.append(s["email"])
                continue
            temp_password = secrets.token_urlsafe(9)
            stakeholder = Stakeholder(
                full_name=s["full_name"],
                email=s["email"].lower(),
                role=s["role"],
                affiliated_university=s["affiliated_university"],
                active_capacity_limit=s["active_capacity_limit"],
                manual_status=s["manual_status"],
            )
            stakeholder.set_password(temp_password)
            db.session.add(stakeholder)
            db.session.flush()  # assign stakeholder.id
            key_to_id[s["key"]] = stakeholder.id
            new_credentials.append((s["full_name"], s["email"], temp_password))
        db.session.commit()

        projects_created = 0
        for p in PROJECTS:
            owner_id = key_to_id.get(p["owner_key"])
            existing = MacroProject.query.filter_by(title=p["title"], owner_id=owner_id).first()
            if existing:
                key_to_id[p["key"]] = existing.id
                continue
            project = MacroProject(title=p["title"], owner_id=owner_id)
            db.session.add(project)
            db.session.flush()
            key_to_id[p["key"]] = project.id
            projects_created += 1
        db.session.commit()

        topics_created = 0
        for t in TOPICS:
            project_id = key_to_id.get(t["project_key"])
            existing = MicroTopic.query.filter_by(title=t["title"], project_id=project_id).first()
            if existing:
                continue
            assigned_student_id = key_to_id.get(t.get("assigned_student_key"))
            topic = MicroTopic(
                title=t["title"],
                origin_pillar=t["origin_pillar"],
                status=t["status"],
                project_id=project_id,
                assigned_student_id=assigned_student_id,
            )
            db.session.add(topic)
            topics_created += 1
        db.session.commit()

        results = {
            "new_credentials": new_credentials,
            "skipped_stakeholders": skipped_stakeholders,
            "projects_created": projects_created,
            "topics_created": topics_created,
        }

    return render_template_string(_TEMPLATE, form=form, results=results,
                                   stakeholders=STAKEHOLDERS, projects=PROJECTS, topics=TOPICS)


_TEMPLATE = """
{% extends "base.html" %}
{% block title %}Import Notion data{% endblock %}
{% block content %}
<header class="page-head"><h1>Import Notion workspace data</h1></header>
<div class="panel">
  {% if results %}
    <p class="field-hint">Import complete.</p>
    <ul>
      <li>{{ results.new_credentials|length }} new stakeholder account(s) created</li>
      <li>{{ results.skipped_stakeholders|length }} already existed and were reused: {{ results.skipped_stakeholders|join(', ') or '—' }}</li>
      <li>{{ results.projects_created }} macro-project(s) created</li>
      <li>{{ results.topics_created }} micro-topic(s) created</li>
    </ul>
    {% if results.new_credentials %}
    <h2>Temporary passwords (shown once — copy these now)</h2>
    <table class="table">
      <thead><tr><th>Name</th><th>Email</th><th>Temporary password</th></tr></thead>
      <tbody>
        {% for name, email, pw in results.new_credentials %}
        <tr><td>{{ name }}</td><td>{{ email }}</td><td><code>{{ pw }}</code></td></tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="field-hint">Share each password with that person out of band and ask them to change it after they log in (Edit profile).</p>
    {% endif %}
  {% else %}
    <p>This will import from the Notion workspace: <strong>{{ stakeholders|length }}</strong> stakeholders,
      <strong>{{ projects|length }}</strong> macro-projects, <strong>{{ topics|length }}</strong> micro-topics.</p>
    <p class="field-hint">Safe to run more than once — existing stakeholders (matched by email) are reused rather than duplicated, and projects/topics that already exist under the same owner/project are skipped.</p>
    <form method="post" novalidate>
      {{ form.hidden_tag() }}
      {{ form.submit(class="btn btn-primary") }}
    </form>
  {% endif %}
</div>
{% endblock %}
"""
