from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from app.models import MANUAL_STATUSES, ORIGIN_PILLARS, ROLE_LABELS, Stakeholder, TOPIC_STATUSES

# Self-registration deliberately excludes "program_director" — that's the
# super-admin role, and letting anyone grant it to themselves at signup would
# be a privilege-escalation hole. New Program Directors are promoted by an
# existing one via the Stakeholders admin screen instead.
SELF_REGISTER_ROLE_CHOICES = [
    (value, label) for value, label in ROLE_LABELS.items() if value != "program_director"
]


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")


class RegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=SELF_REGISTER_ROLE_CHOICES, validators=[DataRequired()])
    affiliated_university = StringField(
        "Affiliated university", validators=[Optional(), Length(max=120)], default="SRH"
    )
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(min=10, message="Use at least 10 characters.")]
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")

    def validate_email(self, field):
        email = field.data.strip().lower()
        if Stakeholder.query.filter_by(email=email).first() is not None:
            raise ValidationError("An account with that email already exists.")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=10, message="Use at least 10 characters.")]
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Update password")


class StakeholderForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=list(ROLE_LABELS.items()), validators=[DataRequired()])
    affiliated_university = StringField("Affiliated university", validators=[Optional(), Length(max=120)])
    active_capacity_limit = IntegerField(
        "Active capacity limit", validators=[Optional()], description="Max concurrent theses a supervisor can carry."
    )
    manual_status = SelectField(
        "Status", choices=[(s, s) for s in MANUAL_STATUSES], validators=[DataRequired()]
    )
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=10, message="Use at least 10 characters.")],
        description="Leave blank to keep the current password when editing.",
    )
    submit = SubmitField("Save")

    def validate_active_capacity_limit(self, field):
        if field.data is not None and field.data < 0:
            raise ValidationError("Capacity can't be negative.")


class ProjectForm(FlaskForm):
    title = StringField("Project title", validators=[DataRequired(), Length(max=300)])
    owner_id = SelectField("Owner", coerce=int, validators=[DataRequired()])
    knowledge_vault = FileField(
        "Knowledge Vault file (PDF)", validators=[Optional(), FileAllowed(["pdf"], "PDF files only.")]
    )
    submit = SubmitField("Save")


class TopicForm(FlaskForm):
    title = TextAreaField("Topic title", validators=[DataRequired(), Length(max=1000)])
    origin_pillar = SelectField("Origin pillar", choices=[(p, p) for p in ORIGIN_PILLARS], validators=[DataRequired()])
    status = SelectField("Status", choices=[(s, s) for s in TOPIC_STATUSES], validators=[DataRequired()])
    project_id = SelectField("Macro-project", coerce=int, validators=[DataRequired()])
    assigned_student_id = SelectField("Assigned student", coerce=int, validators=[Optional()])
    final_pdf = FileField(
        "Final PDF upload", validators=[Optional(), FileAllowed(["pdf"], "PDF files only.")]
    )
    submit = SubmitField("Save")
