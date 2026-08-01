import os
import sqlite3

db_path = os.path.join(os.path.dirname(__file__), "server", "pool.db")
if os.path.exists(db_path):
    os.remove(db_path)
    print(f"Removed old database {db_path}")
