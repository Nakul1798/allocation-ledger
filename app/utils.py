import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename


def save_upload(file_storage, subfolder):
    """Save an uploaded PDF under a random, non-guessable filename.

    Returns (stored_filename, original_filename) or (None, None) if no file was given.
    The caller is responsible for deleting the previous file, if any, once the new
    one is safely saved.
    """
    if not file_storage or not file_storage.filename:
        return None, None

    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]:
        raise ValueError("Unsupported file type.")

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(target_dir, exist_ok=True)
    file_storage.save(os.path.join(target_dir, stored_name))
    return f"{subfolder}/{stored_name}", original_name


def delete_upload(stored_path):
    if not stored_path:
        return
    full_path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_path)
    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
    except OSError:
        current_app.logger.warning("Could not remove upload %s", stored_path)
