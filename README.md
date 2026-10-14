# PPMP Management System

The Flask application stores PPMP, consolidation, and APP data in SQLite by default (`ppmp.sqlite` beside `app.py`). MariaDB and PostgreSQL are also supported as explicit database backends. The app does not create sample colleges, departments, PPMP/APP items, budgets, approvals, notifications, reports, or dashboard statistics.

## Current APP workflow

Procurement creates an APP or APP (CSE) draft only from a non-empty, same-year consolidation batch containing approved PPMP items for the selected office. The draft uses relational sections and the official 12-column APP table. BAC Chairman, EO, Budget, and Administrator decisions are recorded in sequence; Administrator can inspect/approve/finalize but cannot create the operational draft. Authorized users can export the same APP record as PDF or Excel.

Registration creates a PENDING inactive account. A signed Login-page registration reference provides system-only Pending/Approved/Rejected status without approval email or SMS. The one-account/one-role database rule remains enforced.

## Configure SQLite

SQLite is the default. The database file must be on persistent storage and its directory must be writable by the application. Set `DATABASE_URL` explicitly when deployment uses a mounted persistent directory, for example:

```text
DATABASE_URL=sqlite:////srv/ppmp/data/ppmp.sqlite
```

To use MariaDB instead, set `DB_BACKEND=mariadb` to select the retained `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` settings, or set `DATABASE_URL` to a MariaDB URL. `DATABASE_URL` takes precedence over `DB_BACKEND`.

Switching the active connection does not copy MariaDB records into SQLite. Keep the MariaDB database and SQL dumps untouched until a controlled data migration has been completed and checked. Do not run `--reset-database` against either database to perform a conversion.

Install the Python packages:

```powershell
pip install -r requirements.txt
```

## Deploy to Render with PostgreSQL

The application supports Render PostgreSQL through `DATABASE_URL`. The URL is normalized to the Psycopg 3 SQLAlchemy driver. Keep the active source database and a verified backup until the production data migration has been completed and checked; provisioning a new Render database creates a schema but does not copy local records.

In Render, create a paid Web Service and a managed PostgreSQL database in the same region. Leave the Web Service root directory blank because the GitHub repository root contains `app.py` and `requirements.txt`, then configure:

| Setting | Value |
| --- | --- |
| Build command | `pip install -r requirements.txt` |
| Pre-deploy command | `python app.py --migrate-only` |
| Start command | `gunicorn --bind 0.0.0.0:$PORT wsgi:app` |

Add these Web Service environment variables in the Render dashboard:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | The database's internal connection URL from Render; keep the Web Service and database in the same region. |
| `FLASK_ENV` | `production` |
| `FLASK_DEBUG` | `0` |
| `FLASK_SECRET_KEY` | A unique, randomly generated secret. Do not use the development placeholder. |
| `INITIAL_ADMIN_PASSWORD` | A private, strong password. Required only when initializing a new database without an existing Admin account. |

The pre-deploy command applies the existing additive schema migrations. The WSGI entry point performs a read-only schema and connectivity check before serving requests. Do not use `--reset-database` for deployment or data migration. Import the backed-up production records into Render PostgreSQL and reconcile table counts and key workflows before directing users to the Render URL.

Render's free web services do not support persistent disks, and free PostgreSQL databases expire after 30 days. A service with an attached persistent disk cannot scale to multiple instances; a managed PostgreSQL database is the recommended relational-data option. See [Render's free instance limits](https://render.com/docs/free), [PostgreSQL guide](https://render.com/docs/postgresql), and [persistent disk limitations](https://render.com/docs/disks).

## Database reset (disposable installations only)

Do not run this on an existing or production installation. It permanently removes all operational data and recreates only the administrator account. Use the safe migration instructions below for deployment.

```powershell
python app.py --reset-database
```

Then start the application:

```powershell
python app.py
```

Initial administrator: `admin` / `admin1234`. Change the password after login/password management is implemented.

## Safe migration and verification

For a new SQLite file, initialize the schema and initial administrator with:

```powershell
python app.py --migrate-only
```

For subsequent schema updates, back up the active database, then run additive migrations without deleting existing data:

```powershell
python app.py --migrate-only
python scripts\validate_templates.py
python -m unittest discover -s tests -v
node tests\check_template_scripts.js
```

After every verified feature, fix, removal, workflow, permission, database, security, UI, or report revision, update `..\SYSTEM_REVISION_RECORD.md`, the living Markdown manual, and `CHANGELOG.md`, then regenerate the controlled PDF:

```powershell
python scripts\generate_documentation.py
```

See `..\SYSTEM_REVISION_RECORD.md` for the authoritative revision history, `..\SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` for the editable complete feature manual, and `..\SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.pdf` for its generated controlled copy. `CHANGELOG.md` remains a concise historical source.

