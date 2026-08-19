from flask import Flask, redirect, render_template, request, url_for
import mysql.connector

db_connection = mysql.connector.connect(
    host="127.0.0.1",        # Or your server IP
    user="root",    
    password="",# Your MySQL password
    database="user_account", # The database name
    port=3306
)

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

            if firstname and lastname and middlename and email and password:
                cursor = db_connection.cursor()

                query = """INSERT INTO users (firstname, lastname, middlename, email, password, role) VALUES (%s, %s, %s, %s, %s, %s)"""
                cursor.execute(query, (firstname, lastname, middlename, email, password, 'student'))

                db_connection.commit()
                cursor.close()

                return redirect(url_for('index'))

            return "Please fill in all required fields."
        
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')

            cursor = db_connection.cursor(dictionary=True)

            query = "SELECT * FROM users WHERE email = %s AND password = %s"
            cursor.execute(query, (email, password))
            user = cursor.fetchone()

            cursor.close()

            if user:
                return redirect(url_for('dashboard'))
            
            return "Invalid email or password. Please try again."
        
        return render_template('index')

    @app.route('/dashboard')
    @app.route('/dashboard.html')
    def dashboard():
        return render_template('dashboard.html')

    @app.route('/logout')
    def logout():
        return redirect(url_for('index'))


    @app.route('/reset', methods=['GET', 'POST'])
    @app.route('/reset.html', methods=['GET', 'POST'])
    def reset():
        if request.method == 'POST':
            email = request.form.get('email')
            new_password = request.form.get('new_password')

            if email and new_password:
                cursor = db_connection.cursor()

                query = "UPDATE users SET password = %s WHERE email = %s"
                cursor.execute(query, (new_password, email))

                db_connection.commit()
                cursor.close()

                return redirect(url_for('index'))

            return "Please fill in all required fields."
        
        return render_template('reset.html')
    

    return app


def main():
    app = create_app()
    app.run(debug=True)


if __name__ == '__main__':
    main()