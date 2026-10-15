"""Production WSGI entry point used by Render and Gunicorn."""

from app import app, initialize_database


# Existing tables and data are checked without running schema migrations.
initialize_database(apply_migrations=False)

