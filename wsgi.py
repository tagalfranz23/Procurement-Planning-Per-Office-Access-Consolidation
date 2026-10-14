"""Production WSGI entry point used by Render and Gunicorn."""

import os

from app import app, db, ensure_department_wishlist_schema, initialize_database


# Free Render services have no pre-deploy command. Add only this revision's
# four new tables to the existing PostgreSQL database before verifying it.
with app.app_context():
    if os.environ.get('RENDER') == 'true' and db.engine.dialect.name == 'postgresql':
        ensure_department_wishlist_schema()

# Existing tables and data are checked without running unrelated migrations.
initialize_database(apply_migrations=False)
