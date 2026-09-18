from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def roles_required(*roles):
    """Restrict a view to the given Stakeholder.role values. Program directors are
    treated as super-admins and always pass, regardless of the roles listed.
    An anonymous visitor is sent to the login page (via @login_required) rather
    than getting a bare 403, so "sign in first" reads clearly."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role == "program_director":
                return view_func(*args, **kwargs)
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def admin_required(view_func):
    return roles_required()(view_func)
