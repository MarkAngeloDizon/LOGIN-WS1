
import os
from datetime import date, datetime
from functools import wraps

import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)
from flask import (
    Flask,
    redirect,
    render_template,
    request,
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


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_db_connection():
    if os.getenv("USE_REMOTE_DB") == "1":
        config = {
            "host": os.getenv("DB_HOST"),
            "port": int(os.getenv("DB_PORT", "3306")),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "database": os.getenv("DB_NAME"),
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


# --------------------------------------------------
# ROLE AND SESSION HELPERS
# --------------------------------------------------

def current_role():
    return (session.get("role") or "").strip().lower()


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
    import json

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

            create_user(
                firstname,
                middlename,
                lastname,
                email,
                password,
                "student",
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

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = query(
            """
            SELECT id, firstname, middlename, lastname,
                   email, password, role
            FROM users
            WHERE LOWER(email) = %s
            """,
            (email,),
            one=True,
        )

        if not user or not verify_password(user["password"], password):
            return alert_and_go(
                "Invalid email or password.",
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
            check_password_hash(user["password"], password)
            is_hashed = check_password_hash(user["password"], password)
        except (ValueError, TypeError):
            is_hashed = False

        if not is_hashed:
            query(
                "UPDATE users SET password = %s WHERE id = %s",
                (generate_password_hash(password), user["id"]),
                commit=True,
            )

        session.clear()
        session["user_id"] = user["id"]
        session["firstname"] = user["firstname"]
        session["middlename"] = user["middlename"]
        session["lastname"] = user["lastname"]
        session["role"] = role

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

            # Replace this temporary route with verified password recovery.
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
        session.clear()
        return redirect(url_for("index"))

    # --------------------------------------------------
    # STUDENT DASHBOARD
    # --------------------------------------------------

    @app.route("/student-dashboard")
    @app.route("/student-dashboard.html")
    @role_required("student")
    def student_dashboard():
        return render_template("student-dashboard.html")

    # --------------------------------------------------
    # TEACHER HELPERS
    # --------------------------------------------------

    def teacher_owns_class(class_id):
        return query(
            """
            SELECT id
            FROM classes
            WHERE id = %s AND teacher_id = %s
            """,
            (class_id, session["user_id"]),
            one=True,
        ) is not None

    # --------------------------------------------------
    # TEACHER DASHBOARD
    # --------------------------------------------------

    @app.route("/teacher-dashboard")
    @app.route("/teacher-dashboard.html")
    @role_required("teacher")
    def teacher_dashboard():
        classes = query(
            """
            SELECT id, class_name, subject
            FROM classes
            WHERE teacher_id = %s
            ORDER BY class_name
            """,
            (session["user_id"],),
        )

        assignments = query(
            """
            SELECT a.id, a.class_id, a.title, a.instructions,
                   a.due_date, a.points, c.class_name, c.subject
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            WHERE c.teacher_id = %s
            ORDER BY a.id DESC
            """,
            (session["user_id"],),
        )

        selected_class = request.args.get("class_id", type=int)
        attendance_date = request.args.get(
            "date", date.today().isoformat()
        )

        students = []
        attendance_map = {}

        if selected_class and teacher_owns_class(selected_class):
            students = query(
                """
                SELECT u.id, u.firstname, u.lastname
                FROM class_students cs
                JOIN users u ON u.id = cs.student_id
                WHERE cs.class_id = %s
                  AND LOWER(u.role) = 'student'
                ORDER BY u.lastname, u.firstname
                """,
                (selected_class,),
            )

            records = query(
                """
                SELECT student_id, status
                FROM attendance
                WHERE class_id = %s AND attendance_date = %s
                """,
                (selected_class, attendance_date),
            )

            attendance_map = {
                row["student_id"]: row["status"]
                for row in records
            }

        return render_template(
            "teacher-dashboard.html",
            classes=classes,
            assignments=assignments,
            students=students,
            attendance_map=attendance_map,
            selected_class=selected_class,
            attendance_date=attendance_date,
        )

    # --------------------------------------------------
    # CREATE ASSIGNMENT
    # --------------------------------------------------

    @app.route("/teacher/assignments/create", methods=["POST"])
    @role_required("teacher")
    def create_assignment():
        class_id = request.form.get("class_id", type=int)
        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()
        due_date = request.form.get("due_date", "").strip()
        points = request.form.get("points", 100, type=int)

        if not class_id or not teacher_owns_class(class_id):
            return "Invalid class or access denied.", 403

        if not title or points is None or points < 1:
            return "Enter a title and valid points.", 400

        due_date = due_date.replace("T", " ") if due_date else None

        if due_date and len(due_date) == 16:
            due_date += ":00"

        query(
            """
            INSERT INTO assignments
                (class_id, title, instructions, due_date, points)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                class_id,
                title,
                instructions or None,
                due_date,
                points,
            ),
            commit=True,
        )

        return redirect(url_for("teacher_dashboard") + "#assignment")

    # --------------------------------------------------
    # EDIT ASSIGNMENT
    # --------------------------------------------------

    @app.route(
        "/teacher/assignments/<int:assignment_id>/edit",
        methods=["POST"],
    )
    @role_required("teacher")
    def edit_assignment(assignment_id):
        assignment = query(
            """
            SELECT a.id
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            WHERE a.id = %s AND c.teacher_id = %s
            """,
            (assignment_id, session["user_id"]),
            one=True,
        )

        if not assignment:
            return "Assignment not found or access denied.", 404

        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()
        due_date = request.form.get("due_date", "").strip()
        points = request.form.get("points", 100, type=int)

        if not title or points is None or points < 1:
            return "Enter a title and valid points.", 400

        due_date = due_date.replace("T", " ") if due_date else None

        if due_date and len(due_date) == 16:
            due_date += ":00"

        query(
            """
            UPDATE assignments
            SET title = %s,
                instructions = %s,
                due_date = %s,
                points = %s
            WHERE id = %s
            """,
            (
                title,
                instructions or None,
                due_date,
                points,
                assignment_id,
            ),
            commit=True,
        )

        return redirect(url_for("teacher_dashboard") + "#assignment")

    # --------------------------------------------------
    # DELETE ASSIGNMENT
    # --------------------------------------------------

    @app.route(
        "/teacher/assignments/<int:assignment_id>/delete",
        methods=["POST"],
    )
    @role_required("teacher")
    def delete_assignment(assignment_id):
        query(
            """
            DELETE a
            FROM assignments a
            JOIN classes c ON c.id = a.class_id
            WHERE a.id = %s AND c.teacher_id = %s
            """,
            (assignment_id, session["user_id"]),
            commit=True,
        )

        return redirect(url_for("teacher_dashboard") + "#assignment")

    # --------------------------------------------------
    # SAVE ATTENDANCE
    # --------------------------------------------------

    @app.route("/teacher/attendance/save", methods=["POST"])
    @role_required("teacher")
    def save_attendance():
        class_id = request.form.get("class_id", type=int)
        attendance_date = request.form.get(
            "attendance_date", ""
        ).strip()

        if not class_id or not teacher_owns_class(class_id):
            return "Invalid class or access denied.", 403

        try:
            date.fromisoformat(attendance_date)
        except (ValueError, TypeError):
            return "Invalid attendance date.", 400

        students = query(
            """
            SELECT u.id
            FROM class_students cs
            JOIN users u ON u.id = cs.student_id
            WHERE cs.class_id = %s
              AND LOWER(u.role) = 'student'
            """,
            (class_id,),
        )

        allowed_statuses = {"Present", "Absent", "Late", "Excused"}

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            for student in students:
                student_id = student["id"]
                status = request.form.get(f"status_{student_id}", "")

                if status not in allowed_statuses:
                    continue

                cursor.execute(
                    """
                    INSERT INTO attendance
                        (class_id, student_id, attendance_date,
                         status, marked_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        marked_by = VALUES(marked_by)
                    """,
                    (
                        class_id,
                        student_id,
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

        return redirect(
            url_for(
                "teacher_dashboard",
                class_id=class_id,
                date=attendance_date,
            ) + "#attendance"
        )

    # --------------------------------------------------
    # ADMIN DASHBOARD - LIVE MYSQL DATA
    # --------------------------------------------------

    @app.route("/admin-dashboard")
    @app.route("/admin-dashboard.html")
    @role_required("admin")
    def admin_dashboard():
        users = query(
            """
            SELECT
                id,
                firstname,
                middlename,
                lastname,
                email,
                LOWER(role) AS role
            FROM users
            ORDER BY id DESC
            """
        )

        counts = {
            "admin": 0,
            "teacher": 0,
            "student": 0,
        }

        for user in users:
            role = (user.get("role") or "").strip().lower()

            if role in counts:
                counts[role] += 1

        stats = {
            "total_users": len(users),
            "admins": counts["admin"],
            "teachers": counts["teacher"],
            "students": counts["student"],
        }

        return render_template(
            "admin-dashboard.html",
            users=users,
            counts=counts,
            stats=stats,
            account_count=len(users),
            current_year=datetime.now().year,
        )

    # --------------------------------------------------
    # ADMIN ACCOUNT MANAGEMENT
    # --------------------------------------------------

    def admin_create(role):
        firstname = request.form.get("firstname", "").strip()
        middlename = request.form.get("middlename", "").strip()
        lastname = request.form.get("lastname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not (firstname and lastname and email and password):
            return alert_and_go(
                "Please fill in all required fields.",
                "/admin-dashboard",
            )

        if role not in ("teacher", "student"):
            return alert_and_go(
                "Invalid account role.",
                "/admin-dashboard",
            )

        if email_taken(email):
            return alert_and_go(
                "That email is already registered.",
                "/admin-dashboard",
            )

        create_user(
            firstname,
            middlename,
            lastname,
            email,
            password,
            role,
        )

        return redirect(url_for("admin_dashboard"))

    @app.route("/adduser", methods=["POST"])
    @role_required("admin")
    def add_user():
        return admin_create("student")

    @app.route("/addteacher", methods=["POST"])
    @role_required("admin")
    def add_teacher():
        return admin_create("teacher")

    @app.route("/deleteuser/<int:user_id>", methods=["POST"])
    @role_required("admin")
    def delete_user(user_id):
        if user_id == session["user_id"]:
            return alert_and_go(
                "You cannot delete your own account.",
                "/admin-dashboard",
            )

        target = query(
            "SELECT id, role FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

        if not target:
            return alert_and_go(
                "Account not found.",
                "/admin-dashboard",
            )

        query(
            "DELETE FROM users WHERE id = %s",
            (user_id,),
            commit=True,
        )

        return redirect(url_for("admin_dashboard"))

    return app


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

def main():
    app = create_app()
    app.run(debug=True)


if __name__ == "__main__":
    main()
