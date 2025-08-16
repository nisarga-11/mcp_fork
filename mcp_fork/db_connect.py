from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        sslmode=os.getenv("DB_SSLMODE", "disable")  # default to disable
    )
    print("Connected to PostgreSQL successfully!")
except Exception as e:
    print("Error connecting to database:", e)
