from flask import Flask, redirect, render_template, request, url_for
import mysql.connector


def create_app():
    app = Flask(__name__, template_folder='.')


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
            confirm_password = request.form.get('confirm_password')


            if password != confirm_password:
                return "Passwords do not match. Please try again."

            if not firstname or not lastname or not email or not password:
                return "Please fill in all required fields."

            conn = None
            cursor = None

            try:
                conn = mysql.connector.connect(
                    host="localhost",
                    user="root",
                    password="",
                    database="user_account"
                )

                cursor = conn.cursor()

                query = """
                    INSERT INTO users
                    (firstname, lastname, middlename, email, password)
                    VALUES (%s, %s, %s, %s, %s)
                """

                values = (
                    firstname,
                    lastname,
                    middlename,
                    email,
                    password
                )

                cursor.execute(query, values)
                conn.commit()

                print("User registered:", email)

                return redirect(url_for('index'))

            except mysql.connector.Error as e:
                print(f"Database error: {e}")
                return f"Database error: {e}"

            finally:
                if cursor:
                    cursor.close()

                if conn and conn.is_connected():
                    conn.close()

        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():

        if request.method == 'POST':

            email = request.form.get('email')
            password = request.form.get('password')

            if not email or not password:
                return "Please enter your email and password."

            conn = None
            cursor = None

            try:
                conn = mysql.connector.connect(
                    host="localhost",
                    user="root",
                    password="",
                    database="user_account"
                )

                cursor = conn.cursor()

                query = """
                    SELECT *
                    FROM users
                    WHERE email = %s AND password = %s
                """

                cursor.execute(query, (email, password))

                user = cursor.fetchone()

                if user:
                    return redirect(url_for('dashboard'))

                return "Invalid email or password."

            except mysql.connector.Error as e:
                print(f"Database error: {e}")
                return f"Database error: {e}"

            finally:
                if cursor:
                    cursor.close()

                if conn and conn.is_connected():
                    conn.close()

        return render_template('index.html')

    @app.route('/dashboard')
    @app.route('/dashboard.html')
    def dashboard():
        return render_template('dashboard.html')

    @app.route('/logout')
    def logout():
        return redirect(url_for('index'))

    return app


def main():
    app = create_app()
    app.run(debug=True)


if __name__ == '__main__':
    main()