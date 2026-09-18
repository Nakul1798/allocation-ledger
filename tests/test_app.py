import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from app import create_app, db
from app.models import MacroProject, MicroTopic, Stakeholder


@pytest.fixture
def app(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_admin(app, email="director@srh.de", password="verysecurepassword"):
    with app.app_context():
        admin = Stakeholder(
            full_name="Dr. Director",
            email=email,
            role="program_director",
            manual_status="ACTIVE",
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
    return email, password


def login(client, email, password):
    resp = client.get("/auth/login")
    token = _extract_csrf(resp.data)
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=True,
    )


def _extract_csrf(html_bytes):
    html = html_bytes.decode()
    marker = 'name="csrf_token" type="hidden" value="'
    if marker not in html:
        marker = "name=\"csrf_token\" value=\""
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


# --- auth ---

def test_login_page_loads(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Allocation Ledger" in resp.data


def test_dashboard_requires_login(client):
    resp = client.get("/", follow_redirects=True)
    assert b"Please sign in" in resp.data or resp.request.path == "/auth/login"


def test_login_success_and_logout(app, client):
    email, password = make_admin(app)
    resp = login(client, email, password)
    assert resp.status_code == 200
    assert b"Overview" in resp.data

    resp = client.get("/")
    csrf_resp = client.get("/auth/change-password")
    token = _extract_csrf(csrf_resp.data)
    resp = client.post("/auth/logout", data={"csrf_token": token}, follow_redirects=True)
    assert b"signed out" in resp.data.lower() or b"sign in" in resp.data.lower()


def test_login_wrong_password_generic_error(app, client):
    email, _ = make_admin(app)
    resp = login(client, email, "totally-wrong-password")
    assert b"Incorrect email or password" in resp.data


def test_login_unknown_user_same_error(app, client):
    make_admin(app)
    resp = login(client, "nobody@srh.de", "whatever-password")
    assert b"Incorrect email or password" in resp.data


def test_account_locks_after_repeated_failures(app, client):
    email, _ = make_admin(app)
    for _ in range(5):
        login(client, email, "wrong-password-attempt")
    resp = login(client, email, "wrong-password-attempt")
    assert b"temporarily locked" in resp.data


def test_csrf_protects_post_routes(app, client):
    email, password = make_admin(app)
    login(client, email, password)
    # Posting without a csrf token must be rejected (400).
    resp = client.post("/stakeholders/new", data={"full_name": "X"})
    assert resp.status_code == 400


# --- role-based access ---

def make_student(app, email="student@srh.de", password="studentpassword1"):
    with app.app_context():
        s = Stakeholder(full_name="Stu Dent", email=email, role="student", manual_status="ACTIVE")
        s.set_password(password)
        db.session.add(s)
        db.session.commit()
    return email, password


def test_student_cannot_reach_stakeholder_new(app, client):
    email, password = make_student(app)
    login(client, email, password)
    resp = client.get("/stakeholders/new")
    assert resp.status_code == 403


def test_admin_can_create_stakeholder(app, client):
    email, password = make_admin(app)
    login(client, email, password)
    form_resp = client.get("/stakeholders/new")
    token = _extract_csrf(form_resp.data)
    resp = client.post(
        "/stakeholders/new",
        data={
            "full_name": "Prof. New",
            "email": "prof.new@srh.de",
            "role": "professor",
            "affiliated_university": "SRH",
            "active_capacity_limit": "3",
            "manual_status": "ACTIVE",
            "password": "supersecurepassword",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert Stakeholder.query.filter_by(email="prof.new@srh.de").count() == 1


# --- capacity + completion velocity logic ---

def test_capacity_flag_and_completion_velocity(app, client):
    with app.app_context():
        prof = Stakeholder(
            full_name="Prof. Load",
            email="prof.load@srh.de",
            role="professor",
            active_capacity_limit=1,
            manual_status="ACTIVE",
        )
        prof.set_password("professorpassword")
        db.session.add(prof)
        db.session.commit()

        project = MacroProject(title="Smart Buildings", owner_id=prof.id)
        db.session.add(project)
        db.session.commit()

        t1 = MicroTopic(title="Topic A", origin_pillar="1-Scientific Databases", status="In progress", project_id=project.id)
        t2 = MicroTopic(title="Topic B", origin_pillar="1-Scientific Databases", status="Completed", project_id=project.id)
        db.session.add_all([t1, t2])
        db.session.commit()

        refreshed = db.session.get(Stakeholder, prof.id)
        assert refreshed.active_load == 1
        assert refreshed.is_over_capacity is True
        assert refreshed.display_status == "FULL CAPACITY"

        refreshed_project = db.session.get(MacroProject, project.id)
        assert refreshed_project.completion_velocity == 50


# --- file upload ---

def test_pdf_upload_and_secure_download(app, client):
    email, password = make_admin(app)
    login(client, email, password)

    with app.app_context():
        prof = Stakeholder(full_name="Prof. Owner", email="owner@srh.de", role="professor", manual_status="ACTIVE")
        prof.set_password("ownerpassword1")
        db.session.add(prof)
        db.session.commit()
        prof_id = prof.id

    form_resp = client.get("/projects/new")
    token = _extract_csrf(form_resp.data)
    resp = client.post(
        "/projects/new",
        data={
            "title": "Circular Materials",
            "owner_id": str(prof_id),
            "knowledge_vault": (io.BytesIO(b"%PDF-1.4 fake pdf content"), "notes.pdf"),
            "csrf_token": token,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        project = MacroProject.query.filter_by(title="Circular Materials").first()
        assert project is not None
        assert project.knowledge_vault_filename is not None

        dl = client.get(f"/files/{project.knowledge_vault_filename}")
        assert dl.status_code == 200
        assert dl.data.startswith(b"%PDF")


def test_rejects_non_pdf_upload(app, client):
    email, password = make_admin(app)
    login(client, email, password)
    with app.app_context():
        prof = Stakeholder(full_name="Prof. Owner2", email="owner2@srh.de", role="professor", manual_status="ACTIVE")
        prof.set_password("ownerpassword2")
        db.session.add(prof)
        db.session.commit()
        prof_id = prof.id

    form_resp = client.get("/projects/new")
    token = _extract_csrf(form_resp.data)
    resp = client.post(
        "/projects/new",
        data={
            "title": "Bad Upload Project",
            "owner_id": str(prof_id),
            "knowledge_vault": (io.BytesIO(b"not a pdf"), "notes.txt"),
            "csrf_token": token,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert MacroProject.query.filter_by(title="Bad Upload Project").count() == 0
