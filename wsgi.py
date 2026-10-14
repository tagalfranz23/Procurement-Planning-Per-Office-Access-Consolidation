"""Production WSGI entry point used by Render and Gunicorn."""

from app import app, initialize_database


# The schema is migrated by Render's one-time pre-deploy command. Each server
# process performs only the normal read-only startup check here.
initialize_database(apply_migrations=False)
