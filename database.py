import psycopg2
from config import DATABASE_URL

def get_connection():
	return psycopg2.connect(DATABASE_URL)

def create_tables():
	conn = get_connection()
	cursor = conn.cursor()

	cursor.execute("DROP TABLE IF EXISTS messages")
	cursor.execute("DROP TABLE IF EXISTS moods")
	cursor.execute("DROP TABLE IF EXISTS users")

	cursor.execute("""
		CREATE TABLE users(
			telegram_id BIGINT PRIMARY KEY,
			name TEXT
		)
	""")

	cursor.execute("""
		CREATE TABLE messages (
			id SERIAL PRIMARY KEY,
			telegram_id BIGINT,
			role TEXT,
			content TEXT,
			created_at TIMESTAMP DEFAULT NOW()
		)
	""")

	conn.commit()
	cursor.close()
	conn.close()
	print("Таблицы сощданы успешно")

if __name__ == "__main__":
	create_tables()