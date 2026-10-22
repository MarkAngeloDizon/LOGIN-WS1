import os
import json
import shutil
import subprocess
import secrets
import tempfile
from functools import wraps
from pathlib import Path
from datetime import date, datetime, timedelta
from io import BytesIO

import mysql.connector
from mysql.connector import IntegrityError
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

load_dotenv()

ROLES = ("admin", "teacher", "student")

DASHBOARDS = {
    "admin": "admin_dashboard",
    "teacher": "teacher_dashboard",
    "student": "student_dashboard",
}

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "materials"
ALLOWED_UPLOADS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "txt", "png", "jpg", "jpeg", "zip",
}


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------


def get_db_connection():
    if os.getenv("USE_REMOTE_DB") == "1":
        config = {
            "host": os.getenv("DB_HOST"),
            "port": int(os.getenv("DB_PORT", "4000")),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "database": os.getenv("DB_NAME"),
            "ssl_verify_cert": True,
            "ssl_verify_identity": True,
            "connection_timeout": 15,
        }

        ssl_ca = os.getenv("DB_SSL_CA")
        if ssl_ca:
            config["ssl_ca"] = ssl_ca

        return mysql.connector.connect(**config)

    return mysql.connector.connect(
        host="127.0.0.1",
        user="root",
        password="",
        database="snhs_lms",
        port=3306,
    )


def query(sql, params=(), *, one=False, commit=False):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(sql, params)

        if commit:
            conn.commit()
            return cursor.lastrowid

        return cursor.fetchone() if one else cursor.fetchall()

    finally:
        cursor.close()
        conn.close()


# --------------------------------------------------
# PASSWORD HELPERS
# --------------------------------------------------

def verify_password(stored_password, supplied_password):
    """Verify a hash or temporarily support a legacy plain-text password."""
    if not stored_password:
        return False

    try:
        if check_password_hash(stored_password, supplied_password):
            return True
    except (ValueError, TypeError):
        pass

    # Temporary migration support for old plain-text passwords.
    return stored_password == supplied_password


def email_taken(email):
    return query(
        "SELECT id FROM users WHERE LOWER(email) = %s",
        (email.strip().lower(),),
        one=True,
    ) is not None


def create_user(firstname, middlename, lastname, email, password, role):
    password_hash = generate_password_hash(password)

    return query(
        """
        INSERT INTO users
            (firstname, middlename, lastname, email, password, role)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            firstname.strip(),
            middlename.strip() or None,
            lastname.strip(),
            email.strip().lower(),
            password_hash,
            role.lower(),
        ),
        commit=True,
    )


def log_audit(action, entity_type, entity_id=None, details=None,
              user_id=None, allow_anonymous=False):
    """Save an activity to the audit_logs table."""
    actor = user_id if user_id is not None else session.get("user_id")

    if actor is None and not allow_anonymous:
        return

    try:
        query(
            """
            INSERT INTO audit_logs
                (user_id, action, entity_type, entity_id, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                actor,
                action,
                entity_type,
                str(entity_id) if entity_id is not None else None,
                (details or "")[:1000] or None,
                request.remote_addr,
            ),
            commit=True,
        )
    except Exception:
        # Logging must never break the request.
        print("Audit log failed:", action)


def get_school_settings():
    rows = query(
        """
        SELECT setting_key, setting_value
        FROM school_settings
        """
    )

    settings = {
        "school_name": "Serenity National High School",
        "school_address": "",
        "school_email": "",
        "school_phone": "",
    }

    for row in rows:
        if row["setting_key"] in settings:
            settings[row["setting_key"]] = row["setting_value"] or ""

    return settings


# --------------------------------------------------
# ROLE AND SESSION HELPERS
# --------------------------------------------------

def current_role():
    return (session.get("role") or "").strip().lower()


def valid_csrf():
    supplied = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")

    return bool(expected) and secrets.compare_digest(
        supplied,
        expected,
    )


def csrf_error():
    return "Invalid or expired form token. Reload the page.", 400


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("index"))

            if current_role() != role:
                dashboard = DASHBOARDS.get(current_role())

                if dashboard:
                    return redirect(url_for(dashboard))

                session.clear()
                return redirect(url_for("index"))

            return view(*args, **kwargs)

        return wrapped

    return decorator


def alert_and_go(message, target):
    return (
        "<script>"
        f"alert({json.dumps(message)});"
        f"window.location.href={json.dumps(target)};"
        "</script>"
    )


# --------------------------------------------------
# APPLICATION
# --------------------------------------------------

def create_app():
    app = Flask(__name__, template_folder=".")

    app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

    @app.before_request
    def ensure_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)

    @app.before_request
    def block_disabled_accounts():
        """Sign out anyone whose account was disabled while logged in."""
        if request.endpoint in (None, "static"):
            return None

        if "user_id" not in session:
            return None

        row = query(
            "SELECT is_active FROM users WHERE id = %s",
            (session["user_id"],),
            one=True,
        )

        if not row or not row["is_active"]:
            session.clear()
            return alert_and_go(
                "Your account is disabled or no longer exists.",
                "/",
            )

        return None

    # --------------------------------------------------
    # CURRENT USER TEMPLATE DATA
    # --------------------------------------------------

    @app.context_processor
    def inject_current_user():
        if "user_id" not in session:
            return {"current_user": None}

        first = (session.get("firstname") or "").strip()
        middle = (session.get("middlename") or "").strip()
        last = (session.get("lastname") or "").strip()
        role = current_role()

        return {
            "current_user": {
                "id": session["user_id"],
                "firstname": first,
                "middlename": middle,
                "lastname": last,
                "full_name": " ".join(
                    part for part in (first, middle, last) if part
                ),
                "role": role,
                "role_label": role.capitalize(),
                "initials": (first[:1] + last[:1]).upper() or "?",
            }
        }

    # --------------------------------------------------
    # CSRF TOKEN FOR TEMPLATES + UPLOAD SIZE ERROR
    # --------------------------------------------------

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": session.get("csrf_token", "")}

    @app.errorhandler(413)
    def file_too_large(_error):
        dashboard = DASHBOARDS.get(current_role())
        target = url_for(dashboard) if dashboard else "/"
        return alert_and_go(
            "That file is too large. The limit is 20 MB.", target
        ), 413

    # --------------------------------------------------
    # PUBLIC PAGES
    # --------------------------------------------------

    @app.route("/")
    @app.route("/index")
    @app.route("/index.html")
    def index():
        return render_template("index.html")

    # --------------------------------------------------
    # REGISTER
    # --------------------------------------------------

    @app.route("/register", methods=["GET", "POST"])
    @app.route("/register.html", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            firstname = request.form.get("firstname", "").strip()
            middlename = request.form.get("middlename", "").strip()
            lastname = request.form.get("lastname", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm-password", "")

            if not (firstname and lastname and email and password):
                return alert_and_go(
                    "Please fill in all required fields.",
                    "/register",
                )

            if password != confirm:
                return alert_and_go(
                    "Passwords do not match.",
                    "/register",
                )

            if email_taken(email):
                return alert_and_go(
                    "That email is already registered.",
                    "/register",
                )

            new_id = create_user(
                firstname,
                middlename,
                lastname,
                email,
                password,
                "student",
            )

            log_audit(
                "REGISTER",
                "user",
                new_id,
                f"Student self-registered: {email}",
                user_id=new_id,
            )

            session.clear()

            return alert_and_go(
                "Registration successful. Please log in.",
                "/",
            )

        return render_template("register.html")

    # --------------------------------------------------
    # LOGIN
    # --------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            if "user_id" in session:
                dashboard = DASHBOARDS.get(current_role())
                if dashboard:
                    return redirect(url_for(dashboard))

            return render_template("index.html")

        # Validate the CSRF token before processing credentials.
        if not valid_csrf():
            app.logger.warning(
                "Login rejected: invalid CSRF token. "
                "Session token exists: %s; form token exists: %s",
                bool(session.get("csrf_token")),
                bool(request.form.get("csrf_token")),
            )
            return csrf_error()

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = query(
            """
            SELECT id, firstname, middlename, lastname,
                   email, password, role, is_active
            FROM users
            WHERE LOWER(email) = %s
            """,
            (email,),
            one=True,
        )

        if not user or not verify_password(user["password"], password):
            log_audit(
                "LOGIN_FAILED",
                "user",
                user["id"] if user else None,
                f"Failed login attempt for {email}",
                user_id=user["id"] if user else None,
                allow_anonymous=True,
            )
            return alert_and_go(
                "Invalid email or password.",
                "/",
            )

        # Correct password, but the administrator disabled this account.
        if not user["is_active"]:
            log_audit(
                "LOGIN_BLOCKED",
                "user",
                user["id"],
                f"Disabled account tried to log in: {email}",
                user_id=user["id"],
                allow_anonymous=True,
            )
            return alert_and_go(
                "Your account has been disabled. "
                "Please contact the administrator.",
                "/",
            )

        role = (user.get("role") or "").strip().lower()
        dashboard = DASHBOARDS.get(role)

        if not dashboard:
            return alert_and_go(
                "Your account has an invalid role. Contact the administrator.",
                "/",
            )

        # Upgrade legacy plain-text passwords after successful login.
        try:
            is_hashed = check_password_hash(
                user["password"],
                password,
            )
        except (ValueError, TypeError):
            is_hashed = False

        if not is_hashed:
            query(
                "UPDATE users SET password = %s WHERE id = %s",
                (
                    generate_password_hash(password),
                    user["id"],
                ),
                commit=True,
            )

        # Clear old session data and rotate the CSRF token.
        session.clear()
        session["csrf_token"] = secrets.token_urlsafe(32)
        session["user_id"] = user["id"]
        session["firstname"] = user["firstname"]
        session["middlename"] = user["middlename"]
        session["lastname"] = user["lastname"]
        session["role"] = role

        log_audit(
            "LOGIN",
            "user",
            user["id"],
            f"{role.capitalize()} logged in: {email}",
        )

        return redirect(url_for(dashboard))

    # --------------------------------------------------
    # PASSWORD RESET
    # --------------------------------------------------

    @app.route("/reset", methods=["GET", "POST"])
    @app.route("/reset.html", methods=["GET", "POST"])
    def reset():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            new_password = request.form.get("new_password", "")

            # WARNING: this temporary route lets anyone reset any account's
            # password. Replace it with verified password recovery
            # (emailed token) before the app is exposed to real users.
            if email and new_password:
                user = query(
                    "SELECT id FROM users WHERE LOWER(email) = %s",
                    (email,),
                    one=True,
                )

                if user:
                    query(
                        "UPDATE users SET password = %s WHERE id = %s",
                        (
                            generate_password_hash(new_password),
                            user["id"],
                        ),
                        commit=True,
                    )

                return alert_and_go(
                    "If the account exists, the request was processed.",
                    "/",
                )

            return alert_and_go(
                "Please fill in all required fields.",
                "/reset",
            )

        return render_template("reset.html")

    # --------------------------------------------------
    # LOGOUT
    # --------------------------------------------------

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        if "user_id" in session:
            log_audit(
                "LOGOUT",
                "user",
                session["user_id"],
                f"{current_role().capitalize()} logged out",
            )

        session.clear()
        return redirect(url_for("index"))

    # --------------------------------------------------
    # STUDENT DASHBOARD
    # --------------------------------------------------

    @app.route("/student-dashboard")
    @app.route("/student-dashboard.html")
    @role_required("student")
    def student_dashboard():
        student_id = session["user_id"]

        # Get the student's enrolled classes.
        # Supports both class_students and enrollments.
        subjects = query(
            """
            SELECT DISTINCT
                c.id,
                c.class_name,
                c.grade_level,
                c.section_name,
                c.school_year,
                c.room,
                s.subject_name,
                s.subject_code,
                t.firstname AS teacher_firstname,
                t.lastname AS teacher_lastname
            FROM classes c
            JOIN subjects s ON s.id = c.subject_id
            JOIN users t ON t.id = c.teacher_id
            WHERE
                EXISTS (
                    SELECT 1
                    FROM class_students cs
                    WHERE cs.class_id = c.id
                    AND cs.student_id = %s
                )
                OR EXISTS (
                    SELECT 1
                    FROM enrollments e
                    WHERE e.class_id = c.id
                    AND e.student_id = %s
                    AND e.status = 'enrolled'
                )
            ORDER BY s.subject_name, c.class_name
            """,
            (student_id, student_id),
        )

        # Get assignments only from classes this student is enrolled in.
        assignments = query(
            """
            SELECT DISTINCT
                a.id,
                a.title,
                a.instructions,
                a.due_date,
                a.points,
                a.created_at,
                c.id AS class_id,
                c.class_name,
                s.subject_name
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            JOIN subjects s ON s.id = c.subject_id
            WHERE
                EXISTS (
                    SELECT 1
                    FROM class_students cs
                    WHERE cs.class_id = c.id
                    AND cs.student_id = %s
                )
                OR EXISTS (
                    SELECT 1
                    FROM enrollments e
                    WHERE e.class_id = c.id
                    AND e.student_id = %s
                    AND e.status = 'enrolled'
                )
            ORDER BY
                (a.due_date IS NULL),
                a.due_date ASC,
                a.created_at DESC
            """,
            (student_id, student_id),
        )

        # Get the student's weekly class schedule.
        schedule = query(
            """
            SELECT
                cs.id AS schedule_id,
                cs.day_of_week,
                cs.start_time,
                cs.end_time,
                c.id AS class_id,
                c.class_name,
                c.grade_level,
                c.section_name,
                c.room,
                s.subject_name
            FROM class_schedules cs
            JOIN classes c ON c.id = cs.class_id
            JOIN subjects s ON s.id = c.subject_id
            WHERE
                EXISTS (
                    SELECT 1
                    FROM class_students st
                    WHERE st.class_id = c.id
                    AND st.student_id = %s
                )
                OR EXISTS (
                    SELECT 1
                    FROM enrollments e
                    WHERE e.class_id = c.id
                    AND e.student_id = %s
                    AND e.status = 'enrolled'
                )
            ORDER BY
                FIELD(
                    cs.day_of_week,
                    'Monday', 'Tuesday', 'Wednesday',
                    'Thursday', 'Friday', 'Saturday', 'Sunday'
                ),
                cs.start_time
            """,
            (student_id, student_id),
        )

        today = date.today()
        now = datetime.now()
        today_name = today.strftime("%A")
        week_end = now + timedelta(days=7)

        # Today's classes.
        today_schedule = [
            item for item in schedule
            if item["day_of_week"] == today_name
        ]

        # No submission table exists in the schema yet, so these are
        # assigned tasks, not verified unsubmitted work.
        upcoming_deadlines = [
            item for item in assignments
            if item["due_date"] is not None
            and now <= item["due_date"] <= week_end
        ]

        # Group weekly classes by weekday.
        weekdays = [
            "Monday", "Tuesday", "Wednesday",
            "Thursday", "Friday", "Saturday", "Sunday"
        ]

        weekly_schedule = {
            day: [
                item for item in schedule
                if item["day_of_week"] == day
            ]
            for day in weekdays
        }

        return render_template(
            "student-dashboard.html",
            subjects=subjects,
            assignments=assignments,
            schedule=schedule,
            today_schedule=today_schedule,
            upcoming_deadlines=upcoming_deadlines,
            weekly_schedule=weekly_schedule,
            weekdays=weekdays,
            today=today,
            today_name=today_name,
            current_time=now,
        )

    # --------------------------------------------------
    # TEACHER HELPERS
    # --------------------------------------------------

    def teacher_owns_class(class_id):
        return query(
            "SELECT id FROM classes WHERE id = %s AND teacher_id = %s",
            (class_id, session["user_id"]),
            one=True,
        ) is not None

    def teacher_lesson(lesson_id):
        return query(
            """
            SELECT l.id, l.class_id
            FROM lessons l
            JOIN classes c ON c.id = l.class_id
            WHERE l.id = %s AND c.teacher_id = %s
            """,
            (lesson_id, session["user_id"]),
            one=True,
        )

    def teacher_material(material_id):
        return query(
            """
            SELECT m.id, m.lesson_id, m.file_name, m.file_path
            FROM class_materials m
            JOIN classes c ON c.id = m.class_id
            WHERE m.id = %s AND c.teacher_id = %s
            """,
            (material_id, session["user_id"]),
            one=True,
        )

    def class_students_list(class_id):
        """Active students in a class (class_students or enrollments)."""
        return query(
            """
            SELECT DISTINCT u.id, u.firstname, u.lastname
            FROM users u
            WHERE LOWER(u.role) = 'student'
              AND u.is_active = 1
              AND (
                  EXISTS (
                      SELECT 1 FROM class_students cs
                      WHERE cs.class_id = %s AND cs.student_id = u.id
                  )
                  OR EXISTS (
                      SELECT 1 FROM enrollments e
                      WHERE e.class_id = %s AND e.student_id = u.id
                        AND e.status = 'enrolled'
                  )
              )
            ORDER BY u.lastname, u.firstname
            """,
            (class_id, class_id),
        )

    def teacher_back(anchor, **params):
        return redirect(url_for("teacher_dashboard", **params) + anchor)

    def teacher_fail(message, anchor):
        return alert_and_go(message, url_for("teacher_dashboard") + anchor)

    def parse_due(value):
        """Return (mysql_datetime_or_None, error_or_None)."""
        value = (value or "").strip()
        if not value:
            return None, None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None, "Enter a valid due date."
        return parsed.strftime("%Y-%m-%d %H:%M:%S"), None

    def read_assignment_form():
        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()
        points = request.form.get("points", type=int)
        due_date, error = parse_due(request.form.get("due_date"))

        if error:
            return None, error
        if not title:
            return None, "Enter an assignment title."
        if len(title) > 200:
            return None, "The title must not exceed 200 characters."
        if points is None or not 1 <= points <= 10000:
            return None, "Total points must be between 1 and 10000."

        return {
            "title": title,
            "instructions": instructions or None,
            "due_date": due_date,
            "points": points,
        }, None

    def read_lesson_form():
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        content = request.form.get("lesson_content", "").strip()
        raw_date = request.form.get("lesson_date", "").strip()

        lesson_date = None
        if raw_date:
            try:
                lesson_date = date.fromisoformat(raw_date)
            except ValueError:
                return None, "Enter a valid lesson date."

        if not title:
            return None, "Enter a lesson title."
        if len(title) > 200:
            return None, "The title must not exceed 200 characters."

        return {
            "title": title,
            "description": description or None,
            "lesson_content": content or None,
            "lesson_date": lesson_date,
        }, None

    def store_upload(file_storage):
        """Save an uploaded file. Return (info_dict, error_or_None)."""
        original = secure_filename(file_storage.filename or "")
        extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""

        if not original or extension not in ALLOWED_UPLOADS:
            return None, (
                "That file type is not allowed. Allowed: "
                + ", ".join(sorted(ALLOWED_UPLOADS)) + "."
            )

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored = f"{secrets.token_hex(16)}.{extension}"
        file_storage.save(UPLOAD_DIR / stored)

        return {
            "original": original,
            "stored": stored,
            "type": file_storage.mimetype or None,
        }, None

    def remove_upload(stored_name):
        if not stored_name:
            return
        try:
            (UPLOAD_DIR / Path(stored_name).name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            app.logger.warning("Could not remove upload %s", stored_name)

    def add_material(lesson_id, class_id, stored):
        return query(
            """
            INSERT INTO class_materials
                (lesson_id, class_id, uploaded_by, title,
                 file_name, file_path, file_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                lesson_id,
                class_id,
                session["user_id"],
                stored["original"][:200],
                stored["original"][:255],
                stored["stored"],
                (stored["type"] or "")[:100] or None,
            ),
            commit=True,
        )

    # --------------------------------------------------
    # TEACHER DASHBOARD
    # --------------------------------------------------

    @app.route("/teacher-dashboard")
    @app.route("/teacher-dashboard.html")
    @role_required("teacher")
    def teacher_dashboard():
        teacher_id = session["user_id"]

        classes = query(
            """
            SELECT c.id, c.class_name,
                   COALESCE(s.subject_name, c.subject) AS subject
            FROM classes c
            LEFT JOIN subjects s ON s.id = c.subject_id
            WHERE c.teacher_id = %s
            ORDER BY c.class_name, subject
            """,
            (teacher_id,),
        )

        assignments = query(
            """
            SELECT a.id, a.class_id, a.title, a.instructions,
                   a.due_date, a.points, c.class_name,
                   COALESCE(s.subject_name, c.subject) AS subject
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            LEFT JOIN subjects s ON s.id = c.subject_id
            WHERE c.teacher_id = %s
            ORDER BY a.id DESC
            """,
            (teacher_id,),
        )

        lessons = query(
            """
            SELECT l.id, l.class_id, l.title, l.description,
                   l.lesson_content, l.lesson_date, c.class_name,
                   COALESCE(s.subject_name, c.subject) AS subject
            FROM lessons l
            JOIN classes c ON c.id = l.class_id
            LEFT JOIN subjects s ON s.id = c.subject_id
            WHERE c.teacher_id = %s
            ORDER BY (l.lesson_date IS NULL), l.lesson_date DESC, l.id DESC
            """,
            (teacher_id,),
        )

        materials = query(
            """
            SELECT m.id, m.lesson_id, m.title, m.file_name, m.uploaded_at
            FROM class_materials m
            JOIN classes c ON c.id = m.class_id
            WHERE c.teacher_id = %s AND m.lesson_id IS NOT NULL
            ORDER BY m.id DESC
            """,
            (teacher_id,),
        )

        materials_by_lesson = {}
        for item in materials:
            materials_by_lesson.setdefault(item["lesson_id"], []).append(item)

        selected_class = request.args.get("class_id", type=int)

        try:
            attendance_date = date.fromisoformat(
                request.args.get("date", "")
            ).isoformat()
        except ValueError:
            attendance_date = date.today().isoformat()

        students = []
        attendance_map = {}

        if selected_class and teacher_owns_class(selected_class):
            students = class_students_list(selected_class)

            records = query(
                """
                SELECT student_id, status
                FROM attendance
                WHERE class_id = %s AND attendance_date = %s
                """,
                (selected_class, attendance_date),
            )

            # The table stores lowercase; the page uses Present/Absent/...
            attendance_map = {
                row["student_id"]: (row["status"] or "").capitalize()
                for row in records
            }

        return render_template(
            "teacher-dashboard.html",
            classes=classes,
            assignments=assignments,
            lessons=lessons,
            materials_by_lesson=materials_by_lesson,
            students=students,
            attendance_map=attendance_map,
            selected_class=selected_class,
            attendance_date=attendance_date,
        )

    # --------------------------------------------------
    # ASSIGNMENTS: CREATE / EDIT / DELETE
    # --------------------------------------------------

    @app.route("/teacher/assignments/create", methods=["POST"])
    @role_required("teacher")
    def create_assignment():
        anchor = "#assignments"

        if not valid_csrf():
            return csrf_error()

        class_id = request.form.get("class_id", type=int)

        if not class_id or not teacher_owns_class(class_id):
            return teacher_fail("Choose one of your own classes.", anchor)

        data, error = read_assignment_form()
        if error:
            return teacher_fail(error, anchor)

        assignment_id = query(
            """
            INSERT INTO assignments
                (class_id, title, instructions, due_date, points)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                class_id,
                data["title"],
                data["instructions"],
                data["due_date"],
                data["points"],
            ),
            commit=True,
        )

        log_audit(
            "CREATE_ASSIGNMENT",
            "assignment",
            assignment_id,
            f"Created assignment '{data['title']}' for class {class_id}",
        )

        return teacher_back(anchor)

    @app.route(
        "/teacher/assignments/<int:assignment_id>/edit",
        methods=["POST"],
    )
    @role_required("teacher")
    def edit_assignment(assignment_id):
        anchor = "#assignments"

        if not valid_csrf():
            return csrf_error()

        owned = query(
            """
            SELECT a.id
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            WHERE a.id = %s AND c.teacher_id = %s
            """,
            (assignment_id, session["user_id"]),
            one=True,
        )

        if not owned:
            return teacher_fail("Assignment not found or access denied.", anchor)

        data, error = read_assignment_form()
        if error:
            return teacher_fail(error, anchor)

        query(
            """
            UPDATE assignments
            SET title = %s, instructions = %s, due_date = %s, points = %s
            WHERE id = %s
            """,
            (
                data["title"],
                data["instructions"],
                data["due_date"],
                data["points"],
                assignment_id,
            ),
            commit=True,
        )

        log_audit(
            "EDIT_ASSIGNMENT",
            "assignment",
            assignment_id,
            f"Edited assignment '{data['title']}'",
        )

        return teacher_back(anchor)

    @app.route(
        "/teacher/assignments/<int:assignment_id>/delete",
        methods=["POST"],
    )
    @role_required("teacher")
    def delete_assignment(assignment_id):
        anchor = "#assignments"

        if not valid_csrf():
            return csrf_error()

        owned = query(
            """
            SELECT a.id
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            WHERE a.id = %s AND c.teacher_id = %s
            """,
            (assignment_id, session["user_id"]),
            one=True,
        )

        if not owned:
            return teacher_fail("Assignment not found or access denied.", anchor)

        query(
            "DELETE FROM assignments WHERE id = %s",
            (assignment_id,),
            commit=True,
        )

        log_audit(
            "DELETE_ASSIGNMENT",
            "assignment",
            assignment_id,
            "Deleted assignment",
        )

        return teacher_back(anchor)

    # --------------------------------------------------
    # COURSE CONTENT: LESSONS
    # --------------------------------------------------

    @app.route("/teacher/lessons/create", methods=["POST"])
    @role_required("teacher")
    def create_lesson():
        anchor = "#course-content"

        if not valid_csrf():
            return csrf_error()

        class_id = request.form.get("class_id", type=int)

        if not class_id or not teacher_owns_class(class_id):
            return teacher_fail("Choose one of your own classes.", anchor)

        data, error = read_lesson_form()
        if error:
            return teacher_fail(error, anchor)

        stored = None
        upload = request.files.get("material")

        if upload and upload.filename:
            stored, error = store_upload(upload)
            if error:
                return teacher_fail(error, anchor)

        try:
            lesson_id = query(
                """
                INSERT INTO lessons
                    (class_id, teacher_id, title, description,
                     lesson_content, lesson_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    class_id,
                    session["user_id"],
                    data["title"],
                    data["description"],
                    data["lesson_content"],
                    data["lesson_date"],
                ),
                commit=True,
            )

            if stored:
                add_material(lesson_id, class_id, stored)
        except Exception:
            if stored:
                remove_upload(stored["stored"])
            raise

        log_audit(
            "CREATE_LESSON",
            "lesson",
            lesson_id,
            f"Created lesson '{data['title']}' for class {class_id}",
        )

        return teacher_back(anchor)

    @app.route("/teacher/lessons/<int:lesson_id>/edit", methods=["POST"])
    @role_required("teacher")
    def edit_lesson(lesson_id):
        anchor = "#course-content"

        if not valid_csrf():
            return csrf_error()

        if not teacher_lesson(lesson_id):
            return teacher_fail("Lesson not found or access denied.", anchor)

        data, error = read_lesson_form()
        if error:
            return teacher_fail(error, anchor)

        query(
            """
            UPDATE lessons
            SET title = %s, description = %s,
                lesson_content = %s, lesson_date = %s
            WHERE id = %s
            """,
            (
                data["title"],
                data["description"],
                data["lesson_content"],
                data["lesson_date"],
                lesson_id,
            ),
            commit=True,
        )

        log_audit(
            "EDIT_LESSON",
            "lesson",
            lesson_id,
            f"Edited lesson '{data['title']}'",
        )

        return teacher_back(anchor)

    @app.route("/teacher/lessons/<int:lesson_id>/delete", methods=["POST"])
    @role_required("teacher")
    def delete_lesson(lesson_id):
        anchor = "#course-content"

        if not valid_csrf():
            return csrf_error()

        if not teacher_lesson(lesson_id):
            return teacher_fail("Lesson not found or access denied.", anchor)

        files = query(
            "SELECT file_path FROM class_materials WHERE lesson_id = %s",
            (lesson_id,),
        )

        # The foreign key only detaches materials, so delete them explicitly.
        query(
            "DELETE FROM class_materials WHERE lesson_id = %s",
            (lesson_id,),
            commit=True,
        )
        query(
            "DELETE FROM lessons WHERE id = %s",
            (lesson_id,),
            commit=True,
        )

        for row in files:
            remove_upload(row["file_path"])

        log_audit(
            "DELETE_LESSON",
            "lesson",
            lesson_id,
            "Deleted lesson and its materials",
        )

        return teacher_back(anchor)

    # --------------------------------------------------
    # COURSE CONTENT: MATERIALS
    # --------------------------------------------------

    @app.route(
        "/teacher/lessons/<int:lesson_id>/materials/upload",
        methods=["POST"],
    )
    @role_required("teacher")
    def upload_material(lesson_id):
        anchor = "#course-content"

        if not valid_csrf():
            return csrf_error()

        lesson = teacher_lesson(lesson_id)
        if not lesson:
            return teacher_fail("Lesson not found or access denied.", anchor)

        upload = request.files.get("material")
        if not upload or not upload.filename:
            return teacher_fail("Choose a file to upload.", anchor)

        stored, error = store_upload(upload)
        if error:
            return teacher_fail(error, anchor)

        try:
            material_id = add_material(lesson_id, lesson["class_id"], stored)
        except Exception:
            remove_upload(stored["stored"])
            raise

        log_audit(
            "UPLOAD_MATERIAL",
            "class_material",
            material_id,
            f"Uploaded '{stored['original']}' to lesson {lesson_id}",
        )

        return teacher_back(anchor)

    @app.route(
        "/teacher/materials/<int:material_id>/download",
    )
    @role_required("teacher")
    def download_material(material_id):
        material = teacher_material(material_id)

        if not material:
            abort(404)

        return send_from_directory(
            UPLOAD_DIR,
            Path(material["file_path"]).name,
            as_attachment=True,
            download_name=material["file_name"],
        )

    @app.route(
        "/teacher/materials/<int:material_id>/delete",
        methods=["POST"],
    )
    @role_required("teacher")
    def delete_material(material_id):
        anchor = "#course-content"

        if not valid_csrf():
            return csrf_error()

        material = teacher_material(material_id)
        if not material:
            return teacher_fail("Material not found or access denied.", anchor)

        query(
            "DELETE FROM class_materials WHERE id = %s",
            (material_id,),
            commit=True,
        )
        remove_upload(material["file_path"])

        log_audit(
            "DELETE_MATERIAL",
            "class_material",
            material_id,
            f"Deleted material '{material['file_name']}'",
        )

        return teacher_back(anchor)

    # --------------------------------------------------
    # SAVE ATTENDANCE
    # --------------------------------------------------

    @app.route("/teacher/attendance/save", methods=["POST"])
    @role_required("teacher")
    def save_attendance():
        if not valid_csrf():
            return csrf_error()

        class_id = request.form.get("class_id", type=int)
        attendance_date = request.form.get("attendance_date", "").strip()

        if not class_id or not teacher_owns_class(class_id):
            return teacher_fail(
                "Invalid class or access denied.", "#attendance"
            )

        try:
            date.fromisoformat(attendance_date)
        except (ValueError, TypeError):
            return teacher_fail("Invalid attendance date.", "#attendance")

        students = class_students_list(class_id)
        allowed_statuses = {"present", "absent", "late", "excused"}

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            for student in students:
                status = (
                    request.form.get(f"status_{student['id']}", "")
                    .strip()
                    .lower()
                )

                if status not in allowed_statuses:
                    continue

                cursor.execute(
                    """
                    INSERT INTO attendance
                        (class_id, student_id, attendance_date,
                         status, recorded_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        recorded_by = VALUES(recorded_by)
                    """,
                    (
                        class_id,
                        student["id"],
                        attendance_date,
                        status,
                        session["user_id"],
                    ),
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            cursor.close()
            conn.close()

        log_audit(
            "SAVE_ATTENDANCE",
            "attendance",
            class_id,
            f"Saved attendance for class {class_id} on {attendance_date}",
        )

        return teacher_back(
            "#attendance", class_id=class_id, date=attendance_date
        )

    # --------------------------------------------------
    # ADMIN DASHBOARD
    # --------------------------------------------------

    @app.route("/admin-dashboard")
    @app.route("/admin-dashboard.html")
    @role_required("admin")
    def admin_dashboard():
        users = query(
            """
            SELECT id, firstname, middlename, lastname, email,
                   LOWER(role) AS role, is_active
            FROM users
            ORDER BY id DESC
            """
        )

        counts = {"admin": 0, "teacher": 0, "student": 0}
        for user in users:
            role = (user.get("role") or "").lower()
            if role in counts:
                counts[role] += 1

        stats = {
            "total_users": len(users),
            "admins": counts["admin"],
            "teachers": counts["teacher"],
            "students": counts["student"],
        }

        audit_logs = query(
            """
            SELECT
                a.id, a.action, a.entity_type, a.entity_id,
                a.details, a.ip_address, a.created_at,
                u.firstname, u.lastname, u.email
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 200
            """
        )

        school_years = query(
            """
            SELECT id, year_label, start_date, end_date,
                   is_active, created_at
            FROM school_years
            ORDER BY start_date DESC
            """
        )

        active_school_year = query(
            """
            SELECT id, year_label, start_date, end_date
            FROM school_years
            WHERE is_active = 1
            LIMIT 1
            """,
            one=True,
        )

        backup_history = query(
            """
            SELECT a.id, a.action, a.details, a.ip_address, a.created_at,
                   u.firstname, u.lastname
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.action IN ('DATABASE_BACKUP', 'DATABASE_RESTORE')
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 20
            """
        )

        school_settings = get_school_settings()

        return render_template(
            "admin-dashboard.html",
            users=users,
            counts=counts,
            stats=stats,
            audit_logs=audit_logs,
            school_years=school_years,
            active_school_year=active_school_year,
            backup_history=backup_history,
            school_settings=school_settings,
            csrf_token=session["csrf_token"],
            current_year=datetime.now().year,
        )

    # --------------------------------------------------
    # SCHOOL SETTINGS: SAVE
    # --------------------------------------------------

    @app.route("/admin/school-settings/save", methods=["POST"])
    @role_required("admin")
    def save_school_settings():
        if not valid_csrf():
            return csrf_error()

        back = "/admin-dashboard#school-settings"

        school_name = request.form.get("school_name", "").strip()
        school_address = request.form.get("school_address", "").strip()
        school_email = request.form.get("school_email", "").strip().lower()
        school_phone = request.form.get("school_phone", "").strip()

        if not school_name:
            return alert_and_go("School name is required.", back)

        if len(school_name) > 255:
            return alert_and_go(
                "School name must not exceed 255 characters.", back
            )

        if len(school_address) > 1000:
            return alert_and_go("School address is too long.", back)

        if len(school_email) > 254 or len(school_phone) > 50:
            return alert_and_go(
                "Please check the school email and phone number.", back
            )

        settings = {
            "school_name": school_name,
            "school_address": school_address,
            "school_email": school_email,
            "school_phone": school_phone,
        }

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            for key, value in settings.items():
                cursor.execute(
                    """
                    INSERT INTO school_settings
                        (setting_key, setting_value, updated_by)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        setting_value = VALUES(setting_value),
                        updated_by = VALUES(updated_by)
                    """,
                    (key, value, session["user_id"]),
                )

            cursor.execute(
                """
                INSERT INTO audit_logs
                    (user_id, action, entity_type, details, ip_address)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    session["user_id"],
                    "UPDATE_SCHOOL_SETTINGS",
                    "school_settings",
                    "Updated school information",
                    request.remote_addr,
                ),
            )

            conn.commit()

        except Exception:
            conn.rollback()
            app.logger.exception("Failed to save school settings")
            return "Could not save school settings. Check the server log.", 500

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("admin_dashboard") + "#school-settings")

    # --------------------------------------------------
    # CREATE ACCOUNT
    # --------------------------------------------------

    def admin_create(role):
        if not valid_csrf():
            return csrf_error()

        back = "/admin-dashboard#accounts"

        firstname = request.form.get("firstname", "").strip()
        middlename = request.form.get("middlename", "").strip()
        lastname = request.form.get("lastname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not all([firstname, lastname, email, password]):
            return alert_and_go("Please fill in all required fields.", back)

        if role not in ("teacher", "student"):
            return "Invalid account role.", 400

        if len(password) < 8:
            return alert_and_go(
                "Password must be at least 8 characters.", back
            )

        if email_taken(email):
            return alert_and_go("That email is already registered.", back)

        try:
            user_id = create_user(
                firstname, middlename, lastname, email, password, role
            )
            log_audit(
                "CREATE_ACCOUNT",
                "user",
                user_id,
                f"Created {role} account for {email}",
            )
        except IntegrityError:
            return alert_and_go(
                "Could not create the account. Check whether the email "
                "already exists.",
                back,
            )

        return redirect(url_for("admin_dashboard") + "#accounts")

    @app.route("/adduser", methods=["POST"])
    @role_required("admin")
    def add_user():
        return admin_create("student")

    @app.route("/addteacher", methods=["POST"])
    @role_required("admin")
    def add_teacher():
        return admin_create("teacher")

    # --------------------------------------------------
    # DISABLE / ENABLE ACCOUNT (accounts are never deleted)
    # --------------------------------------------------

    def set_user_active(user_id, make_active):
        if not valid_csrf():
            return csrf_error()

        back = "/admin-dashboard#accounts"

        if user_id == session["user_id"] and not make_active:
            return alert_and_go(
                "You cannot disable your own account.", back
            )

        target = query(
            "SELECT id, email, role, is_active FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

        if not target:
            return alert_and_go("Account not found.", back)

        # Nothing to change.
        if bool(target["is_active"]) == make_active:
            return redirect(url_for("admin_dashboard") + "#accounts")

        # Never lock the school out of the admin dashboard.
        if not make_active and target["role"] == "admin":
            remaining = query(
                """
                SELECT COUNT(*) AS n
                FROM users
                WHERE role = 'admin' AND is_active = 1 AND id <> %s
                """,
                (user_id,),
                one=True,
            )

            if remaining["n"] == 0:
                return alert_and_go(
                    "You cannot disable the last active administrator.",
                    back,
                )

        query(
            "UPDATE users SET is_active = %s WHERE id = %s",
            (1 if make_active else 0, user_id),
            commit=True,
        )

        log_audit(
            "ENABLE_ACCOUNT" if make_active else "DISABLE_ACCOUNT",
            "user",
            user_id,
            f"{'Enabled' if make_active else 'Disabled'} "
            f"{target['role']} account: {target['email']}",
        )

        return redirect(url_for("admin_dashboard") + "#accounts")

    @app.route("/admin/users/<int:user_id>/disable", methods=["POST"])
    @role_required("admin")
    def disable_user(user_id):
        return set_user_active(user_id, False)

    @app.route("/admin/users/<int:user_id>/enable", methods=["POST"])
    @role_required("admin")
    def enable_user(user_id):
        return set_user_active(user_id, True)

    # --------------------------------------------------
    # SCHOOL YEAR: CREATE
    # --------------------------------------------------

    @app.route("/admin/school-years/create", methods=["POST"])
    @role_required("admin")
    def create_school_year():
        if not valid_csrf():
            return csrf_error()

        back = "/admin-dashboard#school-year"

        label = request.form.get("year_label", "").strip()
        start = request.form.get("start_date", "").strip()
        end = request.form.get("end_date", "").strip()

        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except (ValueError, TypeError):
            return alert_and_go("Enter valid school-year dates.", back)

        if not label or end_date <= start_date:
            return alert_and_go(
                "Enter a label and an end date after the start date.", back
            )

        if len(label) > 20:
            return alert_and_go(
                "School year label must be 20 characters or fewer.", back
            )

        try:
            year_id = query(
                """
                INSERT INTO school_years
                    (year_label, start_date, end_date, created_by)
                VALUES (%s, %s, %s, %s)
                """,
                (label, start_date, end_date, session["user_id"]),
                commit=True,
            )
        except IntegrityError:
            return alert_and_go(
                "That school-year label already exists.", back
            )

        log_audit(
            "CREATE_SCHOOL_YEAR",
            "school_year",
            year_id,
            f"Created school year {label}",
        )

        return redirect(url_for("admin_dashboard") + "#school-year")

    # --------------------------------------------------
    # SCHOOL YEAR: ACTIVATE
    # --------------------------------------------------

    @app.route(
        "/admin/school-years/<int:year_id>/activate",
        methods=["POST"],
    )
    @role_required("admin")
    def activate_school_year(year_id):
        if not valid_csrf():
            return csrf_error()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Lock the year records while changing the active year.
            cursor.execute(
                "SELECT id, year_label FROM school_years "
                "WHERE id = %s FOR UPDATE",
                (year_id,),
            )
            target = cursor.fetchone()

            if not target:
                conn.rollback()
                return alert_and_go(
                    "School year not found.",
                    "/admin-dashboard#school-year",
                )

            cursor.execute("UPDATE school_years SET is_active = 0")
            cursor.execute(
                "UPDATE school_years SET is_active = 1 WHERE id = %s",
                (year_id,),
            )

            cursor.execute(
                """
                INSERT INTO audit_logs
                    (user_id, action, entity_type, entity_id,
                     details, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    session["user_id"],
                    "ACTIVATE_SCHOOL_YEAR",
                    "school_year",
                    str(year_id),
                    f"Activated school year {target['year_label']}",
                    request.remote_addr,
                ),
            )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("admin_dashboard") + "#school-year")

    # --------------------------------------------------
    # DATABASE CLI CONFIGURATION
    # --------------------------------------------------

    def mysql_cli_settings():
        if os.getenv("USE_REMOTE_DB") == "1":
            host = os.getenv("DB_HOST", "")
            port = os.getenv("DB_PORT", "3306")
            user = os.getenv("DB_USER", "")
            password = os.getenv("DB_PASSWORD", "")
            database = os.getenv("DB_NAME", "")
        else:
            host = "127.0.0.1"
            port = "3306"
            user = "root"
            password = ""
            database = "snhs_lms"

        if not all([host, user, database]):
            raise RuntimeError("Database CLI configuration is incomplete.")

        mysql_bin = os.getenv("MYSQL_BIN_DIR", r"C:\xampp\mysql\bin")
        mysql_exe = Path(mysql_bin) / "mysql.exe"
        dump_exe = Path(mysql_bin) / "mysqldump.exe"

        if not mysql_exe.exists():
            found = shutil.which("mysql")
            if found:
                mysql_exe = Path(found)

        if not dump_exe.exists():
            found = shutil.which("mysqldump")
            if found:
                dump_exe = Path(found)

        if not mysql_exe.exists() or not dump_exe.exists():
            raise RuntimeError(
                "MySQL command-line tools were not found. Set MYSQL_BIN_DIR "
                "to your XAMPP mysql/bin directory."
            )

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "mysql": str(mysql_exe),
            "mysqldump": str(dump_exe),
        }

    # --------------------------------------------------
    # DATABASE BACKUP: DOWNLOAD SQL
    # --------------------------------------------------

    @app.route("/admin/backup", methods=["POST"])
    @role_required("admin")
    def database_backup():
        if not valid_csrf():
            return csrf_error()

        try:
            config = mysql_cli_settings()

            command = [
                config["mysqldump"],
                "--host", config["host"],
                "--port", config["port"],
                "--user", config["user"],
                "--single-transaction",
                "--routines",
                "--triggers",
                config["database"],
            ]

            env = os.environ.copy()
            if config["password"]:
                env["MYSQL_PWD"] = config["password"]

            result = subprocess.run(
                command,
                capture_output=True,
                check=True,
                env=env,
                timeout=120,
            )

            log_audit(
                "DATABASE_BACKUP",
                "database",
                config["database"],
                "Created SQL database backup",
            )

            return send_file(
                BytesIO(result.stdout),
                mimetype="application/sql",
                as_attachment=True,
                download_name=(
                    f"snhs_lms_backup_{datetime.now():%Y%m%d_%H%M%S}.sql"
                ),
            )

        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            app.logger.exception("Database backup failed")
            return f"Backup failed: {exc}", 500

    # --------------------------------------------------
    # DATABASE RESTORE: UPLOADED SQL FILE
    # --------------------------------------------------

    @app.route("/admin/restore", methods=["POST"])
    @role_required("admin")
    def database_restore():
        if not valid_csrf():
            return csrf_error()

        back = "/admin-dashboard#backup-restore"

        if request.form.get("confirm_restore", "").strip() != "YES":
            return alert_and_go("Restore was not confirmed.", back)

        backup = request.files.get("backup_file")

        if not backup or not backup.filename:
            return alert_and_go("Choose a SQL backup file first.", back)

        if not backup.filename.lower().endswith(".sql"):
            return alert_and_go("Only .sql backup files are accepted.", back)

        content = backup.read()

        if not content or len(content) > 20 * 1024 * 1024:
            return alert_and_go(
                "The backup file is empty or exceeds 20 MB.", back
            )

        # Restoring SQL executes database statements. Only restore a
        # trusted backup that belongs to this application/database.
        temp_path = None

        try:
            config = mysql_cli_settings()

            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".sql", delete=False
            ) as temp:
                temp.write(content)
                temp_path = temp.name

            command = [
                config["mysql"],
                "--host", config["host"],
                "--port", config["port"],
                "--user", config["user"],
                config["database"],
            ]

            env = os.environ.copy()
            if config["password"]:
                env["MYSQL_PWD"] = config["password"]

            with open(temp_path, "rb") as sql_file:
                subprocess.run(
                    command,
                    stdin=sql_file,
                    capture_output=True,
                    check=True,
                    env=env,
                    timeout=180,
                )

            # log_audit never raises, so a missing admin row after the
            # restore cannot hide a successful restore.
            log_audit(
                "DATABASE_RESTORE",
                "database",
                config["database"],
                "Restored a SQL backup file",
            )

            return alert_and_go("Database restore completed.", "/")

        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            app.logger.exception("Database restore failed")
            return f"Restore failed: {exc}", 500

        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    return app


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

app = create_app()

if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1"
    )