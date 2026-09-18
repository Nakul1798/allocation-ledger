import os

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from app import db
from app.decorators import admin_required, roles_required
from app.forms import ProjectForm, StakeholderForm, TopicForm
from app.models import MacroProject, MicroTopic, Stakeholder
from app.utils import delete_upload, save_upload

main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@main_bp.route("/")
@login_required
def dashboard():
    stakeholder_count = Stakeholder.query.count()
    project_count = MacroProject.query.count()
    topics = MicroTopic.query.all()
    open_count = sum(1 for t in topics if t.status == "OPEN")
    in_progress_count = sum(1 for t in topics if t.status == "In progress")
    completed_count = sum(1 for t in topics if t.status == "Completed")

    supervisors = [s for s in Stakeholder.query.all() if s.is_supervisor]
    overloaded = [s for s in supervisors if s.is_over_capacity]

    my_topics = []
    if current_user.role == "student":
        my_topics = MicroTopic.query.filter_by(assigned_student_id=current_user.id).all()

    return render_template(
        "main/dashboard.html",
        stakeholder_count=stakeholder_count,
        project_count=project_count,
        open_count=open_count,
        in_progress_count=in_progress_count,
        completed_count=completed_count,
        total_topics=len(topics),
        overloaded=overloaded,
        my_topics=my_topics,
    )


# ---------------------------------------------------------------------------
# Database A: Stakeholder Directory
# ---------------------------------------------------------------------------

@main_bp.route("/stakeholders")
@login_required
def stakeholder_list():
    stakeholders = Stakeholder.query.order_by(Stakeholder.full_name).all()
    return render_template("main/stakeholders.html", stakeholders=stakeholders)


@main_bp.route("/stakeholders/new", methods=["GET", "POST"])
@admin_required
def stakeholder_new():
    form = StakeholderForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if Stakeholder.query.filter_by(email=email).first():
            flash("A stakeholder with that email already exists.", "error")
        elif not form.password.data:
            flash("A password is required when creating a new stakeholder.", "error")
        else:
            s = Stakeholder(
                full_name=form.full_name.data.strip(),
                email=email,
                role=form.role.data,
                affiliated_university=form.affiliated_university.data or None,
                active_capacity_limit=form.active_capacity_limit.data,
                manual_status=form.manual_status.data,
            )
            s.set_password(form.password.data)
            db.session.add(s)
            db.session.commit()
            flash(f"{s.full_name} added to the directory.", "success")
            return redirect(url_for("main.stakeholder_list"))
    return render_template("main/stakeholder_form.html", form=form, stakeholder=None)


@main_bp.route("/stakeholders/<int:stakeholder_id>/edit", methods=["GET", "POST"])
@login_required
def stakeholder_edit(stakeholder_id):
    stakeholder = db.session.get(Stakeholder, stakeholder_id) or abort(404)
    if not current_user.is_admin and current_user.id != stakeholder.id:
        abort(403)

    form = StakeholderForm(obj=stakeholder)
    if not current_user.is_admin:
        # Non-admins editing their own record can't change role, capacity or status.
        form.role.render_kw = {"disabled": True}
        form.active_capacity_limit.render_kw = {"disabled": True}
        form.manual_status.render_kw = {"disabled": True}

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing = Stakeholder.query.filter_by(email=email).first()
        if existing and existing.id != stakeholder.id:
            flash("A stakeholder with that email already exists.", "error")
        else:
            stakeholder.full_name = form.full_name.data.strip()
            stakeholder.email = email
            stakeholder.affiliated_university = form.affiliated_university.data or None
            if current_user.is_admin:
                stakeholder.role = form.role.data
                stakeholder.active_capacity_limit = form.active_capacity_limit.data
                stakeholder.manual_status = form.manual_status.data
            if form.password.data:
                stakeholder.set_password(form.password.data)
            db.session.commit()
            flash("Stakeholder updated.", "success")
            return redirect(url_for("main.stakeholder_list"))

    form.password.data = ""
    return render_template("main/stakeholder_form.html", form=form, stakeholder=stakeholder)


@main_bp.route("/stakeholders/<int:stakeholder_id>/delete", methods=["POST"])
@admin_required
def stakeholder_delete(stakeholder_id):
    stakeholder = db.session.get(Stakeholder, stakeholder_id) or abort(404)
    if stakeholder.owned_projects:
        flash("Can't delete a stakeholder who still owns macro-projects. Reassign those first.", "error")
    elif stakeholder.id == current_user.id:
        flash("You can't delete your own account.", "error")
    else:
        for topic in stakeholder.assigned_topics:
            topic.assigned_student_id = None
        db.session.delete(stakeholder)
        db.session.commit()
        flash("Stakeholder removed.", "success")
    return redirect(url_for("main.stakeholder_list"))


# ---------------------------------------------------------------------------
# Database B: Macro-Projects
# ---------------------------------------------------------------------------

def _supervisor_choices():
    return [
        (s.id, f"{s.full_name} ({s.role_label})")
        for s in Stakeholder.query.order_by(Stakeholder.full_name).all()
        if s.is_supervisor
    ]


@main_bp.route("/projects")
@login_required
def project_list():
    projects = MacroProject.query.order_by(MacroProject.title).all()
    return render_template("main/projects.html", projects=projects)


@main_bp.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = db.session.get(MacroProject, project_id) or abort(404)
    return render_template("main/project_detail.html", project=project)


def _can_manage_project(project=None):
    if current_user.is_admin:
        return True
    if not current_user.is_supervisor:
        return False
    return project is None or project.owner_id == current_user.id


@main_bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def project_new():
    if not _can_manage_project():
        abort(403)
    form = ProjectForm()
    form.owner_id.choices = _supervisor_choices()
    if not current_user.is_admin:
        form.owner_id.data = current_user.id

    if form.validate_on_submit():
        owner_id = form.owner_id.data if current_user.is_admin else current_user.id
        project = MacroProject(title=form.title.data.strip(), owner_id=owner_id)
        try:
            stored, original = save_upload(form.knowledge_vault.data, "knowledge_vault")
        except ValueError:
            flash("Unsupported file type for the Knowledge Vault upload.", "error")
            return render_template("main/project_form.html", form=form, project=None)
        project.knowledge_vault_filename = stored
        project.knowledge_vault_original_name = original
        db.session.add(project)
        db.session.commit()
        flash("Macro-project created.", "success")
        return redirect(url_for("main.project_detail", project_id=project.id))

    return render_template("main/project_form.html", form=form, project=None)


@main_bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def project_edit(project_id):
    project = db.session.get(MacroProject, project_id) or abort(404)
    if not _can_manage_project(project):
        abort(403)

    form = ProjectForm(obj=project)
    form.owner_id.choices = _supervisor_choices()
    if not current_user.is_admin:
        form.owner_id.render_kw = {"disabled": True}

    if form.validate_on_submit():
        project.title = form.title.data.strip()
        if current_user.is_admin:
            project.owner_id = form.owner_id.data
        if form.knowledge_vault.data and form.knowledge_vault.data.filename:
            try:
                stored, original = save_upload(form.knowledge_vault.data, "knowledge_vault")
            except ValueError:
                flash("Unsupported file type for the Knowledge Vault upload.", "error")
                return render_template("main/project_form.html", form=form, project=project)
            delete_upload(project.knowledge_vault_filename)
            project.knowledge_vault_filename = stored
            project.knowledge_vault_original_name = original
        db.session.commit()
        flash("Macro-project updated.", "success")
        return redirect(url_for("main.project_detail", project_id=project.id))

    return render_template("main/project_form.html", form=form, project=project)


@main_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@admin_required
def project_delete(project_id):
    project = db.session.get(MacroProject, project_id) or abort(404)
    delete_upload(project.knowledge_vault_filename)
    for topic in project.topics:
        delete_upload(topic.final_pdf_filename)
    db.session.delete(project)
    db.session.commit()
    flash("Macro-project and its topics were deleted.", "success")
    return redirect(url_for("main.project_list"))


# ---------------------------------------------------------------------------
# Database C: Micro-Topics Board
# ---------------------------------------------------------------------------

@main_bp.route("/topics")
@login_required
def topic_list():
    status_filter = request.args.get("status")
    query = MicroTopic.query
    if status_filter in {"OPEN", "In progress", "Completed"}:
        query = query.filter_by(status=status_filter)
    topics = query.order_by(MicroTopic.title).all()
    return render_template("main/topics.html", topics=topics, status_filter=status_filter)


def _student_choices():
    choices = [(0, "— Unassigned —")]
    choices += [
        (s.id, f"{s.full_name} ({s.affiliated_university or 'external'})")
        for s in Stakeholder.query.filter_by(role="student").order_by(Stakeholder.full_name).all()
    ]
    return choices


def _can_manage_topic(topic=None, project=None):
    if current_user.is_admin:
        return True
    if not current_user.is_supervisor:
        return False
    owner_id = topic.project.owner_id if topic else (project.owner_id if project else None)
    return owner_id == current_user.id


@main_bp.route("/topics/new", methods=["GET", "POST"])
@login_required
def topic_new():
    if not current_user.is_supervisor and not current_user.is_admin:
        abort(403)
    form = TopicForm()
    form.project_id.choices = [(p.id, p.title) for p in MacroProject.query.order_by(MacroProject.title).all()]
    if not current_user.is_admin:
        form.project_id.choices = [
            (p.id, p.title) for p in MacroProject.query.filter_by(owner_id=current_user.id).order_by(MacroProject.title)
        ]
        if not form.project_id.choices:
            flash("Create a macro-project you own before adding topics to it.", "error")
            return redirect(url_for("main.project_new"))
    form.assigned_student_id.choices = _student_choices()

    if form.validate_on_submit():
        project = db.session.get(MacroProject, form.project_id.data) or abort(404)
        if not _can_manage_topic(project=project):
            abort(403)
        topic = MicroTopic(
            title=form.title.data.strip(),
            origin_pillar=form.origin_pillar.data,
            status=form.status.data,
            project_id=project.id,
            assigned_student_id=form.assigned_student_id.data or None,
        )
        try:
            stored, original = save_upload(form.final_pdf.data, "final_pdf")
        except ValueError:
            flash("Unsupported file type for the final PDF upload.", "error")
            return render_template("main/topic_form.html", form=form, topic=None)
        topic.final_pdf_filename = stored
        topic.final_pdf_original_name = original
        db.session.add(topic)
        db.session.commit()
        flash("Topic added to the board.", "success")
        return redirect(url_for("main.topic_list"))

    return render_template("main/topic_form.html", form=form, topic=None)


@main_bp.route("/topics/<int:topic_id>/edit", methods=["GET", "POST"])
@login_required
def topic_edit(topic_id):
    topic = db.session.get(MicroTopic, topic_id) or abort(404)
    if not _can_manage_topic(topic=topic):
        abort(403)

    form = TopicForm(obj=topic)
    if current_user.is_admin:
        form.project_id.choices = [(p.id, p.title) for p in MacroProject.query.order_by(MacroProject.title).all()]
    else:
        form.project_id.choices = [
            (p.id, p.title) for p in MacroProject.query.filter_by(owner_id=current_user.id).order_by(MacroProject.title)
        ]
    form.assigned_student_id.choices = _student_choices()
    if request.method == "GET":
        form.assigned_student_id.data = topic.assigned_student_id or 0

    if form.validate_on_submit():
        new_project = db.session.get(MacroProject, form.project_id.data) or abort(404)
        if not _can_manage_topic(project=new_project):
            abort(403)
        topic.title = form.title.data.strip()
        topic.origin_pillar = form.origin_pillar.data
        topic.status = form.status.data
        topic.project_id = new_project.id
        topic.assigned_student_id = form.assigned_student_id.data or None
        if form.final_pdf.data and form.final_pdf.data.filename:
            try:
                stored, original = save_upload(form.final_pdf.data, "final_pdf")
            except ValueError:
                flash("Unsupported file type for the final PDF upload.", "error")
                return render_template("main/topic_form.html", form=form, topic=topic)
            delete_upload(topic.final_pdf_filename)
            topic.final_pdf_filename = stored
            topic.final_pdf_original_name = original
        db.session.commit()
        flash("Topic updated.", "success")
        return redirect(url_for("main.topic_list"))

    return render_template("main/topic_form.html", form=form, topic=topic)


@main_bp.route("/topics/<int:topic_id>/delete", methods=["POST"])
@login_required
def topic_delete(topic_id):
    topic = db.session.get(MicroTopic, topic_id) or abort(404)
    if not _can_manage_topic(topic=topic):
        abort(403)
    delete_upload(topic.final_pdf_filename)
    db.session.delete(topic)
    db.session.commit()
    flash("Topic removed from the board.", "success")
    return redirect(url_for("main.topic_list"))


# ---------------------------------------------------------------------------
# Secure file downloads
# ---------------------------------------------------------------------------

@main_bp.route("/files/<path:stored_path>")
@login_required
def download_file(stored_path):
    # stored_path looks like "knowledge_vault/<uuid>.pdf" or "final_pdf/<uuid>.pdf".
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    full_path = os.path.normpath(os.path.join(upload_folder, stored_path))
    if not full_path.startswith(os.path.normpath(upload_folder)):
        abort(404)

    directory, filename = os.path.split(full_path)
    owning_project = MacroProject.query.filter_by(knowledge_vault_filename=stored_path).first()
    owning_topic = MicroTopic.query.filter_by(final_pdf_filename=stored_path).first()
    if owning_project is None and owning_topic is None:
        abort(404)

    download_name = "document.pdf"
    if owning_project:
        download_name = owning_project.knowledge_vault_original_name or download_name
    if owning_topic:
        download_name = owning_topic.final_pdf_original_name or download_name

    return send_from_directory(directory, filename, as_attachment=True, download_name=download_name)
