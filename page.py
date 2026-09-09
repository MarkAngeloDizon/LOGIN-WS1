from flask import Flask, redirect, render_template, request, url_for, session
import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host="127.0.0.1",
        user="root",
        password="",
        database="user_account",
        port=3306
    )

def create_app():
    app = Flask(__name__, template_folder='.')
    app.secret_key = 'your-secret-key'


    @app.route('/')
    @app.route('/index')
    @app.route('/index.html')
    def index():
        return render_template('index.html')


    @app.route('/register', methods=['GET', 'POST'])
    @app.route('/register.html', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            firstname = request.form.get('firstname')
            lastname = request.form.get('lastname')
            middlename = request.form.get('middlename')
            email = request.form.get('email')
            password = request.form.get('password')

            if firstname and lastname and middlename and email and password:
                db_connection = get_db_connection()
                cursor = db_connection.cursor()

                query = """INSERT INTO users (firstname, lastname, middlename, email, password, role) VALUES (%s, %s, %s, %s, %s, %s)"""
                cursor.execute(query, (firstname, lastname, middlename, email, password, 'student'))

                db_connection.commit()
                cursor.close()
                db_connection.close()

                return redirect(url_for('index'))

            return "Please fill in all required fields."
        
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')

            db_connection = get_db_connection()
            cursor = db_connection.cursor(dictionary=True)

            query = "SELECT * FROM users WHERE email = %s AND password = %s"
            cursor.execute(query, (email, password))
            user = cursor.fetchone()

            cursor.close()
            db_connection.close()

            if user:
                session['user_id'] = user['id']
                session['firstname'] = user['firstname']
                session['middlename'] = user['middlename']
                session['lastname'] = user['lastname']
                session['role'] = user['role']

            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))

            elif user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            
            elif user['role'] == 'Admin':
                return redirect(url_for('admin_dashboard'))
            
            return redirect(url_for('index'))
        
        return render_template('index.html')

    @app.route('/student-dashboard')
    @app.route('/student-dashboard.html')
    def student_dashboard():
        if 'user_id' not in session:
            return redirect(url_for('index'))

        if session.get('role') != 'student':
            return redirect(url_for('index'))
        
        return render_template(
            'student-dashboard.html',
            firstname = session.get('firstname'),
            middlename = session.get('middlename'),
            lastname = session.get('lastname')
        )

    @app.route('/teacher-dashboard')
    @app.route('/teacher-dashboard.html')
    def teacher_dashboard():
        if 'user_id' not in session:
            return redirect(url_for('index'))

        if session.get('role') != 'teacher':
            return redirect(url_for('index'))
        
        return render_template(
            'teacher-dashboard.html',
            firstname = session.get('firstname'),
            middlename = session.get('middlename'),
            lastname = session.get('lastname'),
            role = session.get('role')
        )

    @app.route('/admin-dashboard')
    @app.route('/admin-dashboard.html')
    def admin_dashboard():
        if 'user_id' not in session:
            return redirect(url_for('index'))

        if session.get('role') !='Admin':
            return redirect(url_for('index'))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Fetch total user count
        cursor.execute("SELECT COUNT(*) AS total_users FROM users")
        account_count = cursor.fetchone()['total_users']

        cursor.execute("SELECT id, firstname, middlename, lastname, email, role FROM users")
        user_list = cursor.fetchall()

        cursor.execute("SELECT course_id, course_code, course_name, course_description FROM courses")
        course_list =cursor.fetchall()

        cursor.close()
        conn.close()


        return render_template(
            'admin-dashboard.html',
            firstname = session.get('firstname'),
            middlename = session.get('middlename'),
            lastname = session.get('lastname'),
            role = session.get('role'),
            user_id = session.get('id'),
            users=user_list,
            account_count=account_count,
            course_list=course_list
        )

    @app.route('/addcourse', methods=['POST'])
    def add_course():
        code = request.form.get('course_code')
        name = request.form.get('course_name')
        desc = request.form.get('course_description')

        if code and name:
            conn = get_db_connection()
            cursor = conn.cursor()

            query = "INSERT INTO courses (course_code, course_name, course_description) VALUES (%s, %s, %s)"
            values = (code, name, desc)

            cursor.execute(query, values)
            conn.commit()

            cursor.close()
            conn.close()

        return redirect(url_for('admin_dashboard'))

    @app.route('/reset', methods=['GET', 'POST'])
    @app.route('/reset.html', methods=['GET', 'POST'])
    def reset():
        if request.method == 'POST':
            email = request.form.get('email')
            new_password = request.form.get('new_password')

            if email and new_password:
                db_connection = get_db_connection()
                cursor = db_connection.cursor()

                query = "UPDATE users SET password = %s WHERE email = %s"
                cursor.execute(query, (new_password, email))

                db_connection.commit()
                cursor.close()
                db_connection.close()

                return redirect(url_for('index'))

            return "Please fill in all required fields."
        
        return render_template('reset.html')


    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))
    

    return app


def main():
    app = create_app()
    app.run(debug=True)


if __name__ == '__main__':
    main()