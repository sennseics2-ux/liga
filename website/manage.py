"""Commands to initialize the database and create the first league administrator."""
import argparse
import getpass
import sqlite3

import database as store


def main():
    parser = argparse.ArgumentParser(description="Manage the Chess Fantasy League")
    parser.add_argument("command", choices=["init", "create-admin"])
    parser.add_argument("--username", help="Admin username for create-admin")
    args = parser.parse_args()
    store.init_db()
    if args.command == "init":
        print(f"Database ready: {store.DB_PATH}")
        return
    username = (args.username or input("Admin username: ")).strip()
    try:
        store.validate_username(username)
    except ValueError as exc:
        parser.error(str(exc))
    password = getpass.getpass("Admin password (12–256 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if not 12 <= len(password) <= 256 or password != confirmation:
        parser.error("Passwords must match and contain 12–256 characters")
    try:
        with store.transaction() as db:
            db.execute("INSERT INTO users (username,password_hash,role,created_at,name) VALUES (?,?,'admin',?,?)",
                       (username, store.hash_password(password), store.iso(store.now_utc()),username))
    except sqlite3.IntegrityError:
        parser.error("Username already exists")
    print(f"Administrator '{username}' created successfully.")


if __name__ == '__main__':
    main()
