<<<<<<< HEAD
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

try:
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        ssl_ca=os.getenv("DB_SSL_CA")
    )

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    result = cursor.fetchone()

    print("AIVEN CONNECTION SUCCESSFUL")
    print("Users:", result[0])

    cursor.close()
    conn.close()

except Exception as e:
    print("CONNECTION FAILED")
=======
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

try:
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        ssl_ca=os.getenv("DB_SSL_CA")
    )

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    result = cursor.fetchone()

    print("AIVEN CONNECTION SUCCESSFUL")
    print("Users:", result[0])

    cursor.close()
    conn.close()

except Exception as e:
    print("CONNECTION FAILED")
>>>>>>> 7e8d52789239d111f3726d5c7e448b6538d7f1a9
    print(e)