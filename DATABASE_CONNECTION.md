# MariaDB Connection Setup

The Flask application supports SQLite, MariaDB, and PostgreSQL through SQLAlchemy. It loads settings from `ppmp/.env` when present; process environment variables take precedence. `DATABASE_URL` takes precedence over `DB_BACKEND` and the `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` values. MariaDB uses `mysql.connector`; PostgreSQL uses Psycopg 3. The MariaDB account must use a password-based authentication plugin supported by the connector.

## PostgreSQL / Render

Set `DATABASE_URL` to the Render PostgreSQL internal connection URL in the Render Web Service environment. Keep the web service and database in the same region. The application normalizes `postgres://` and `postgresql://` URLs to Psycopg 3. Run the additive schema setup with `python app.py --migrate-only`; the production WSGI module checks connectivity and schema without running migrations. This initializes the schema and a first Admin account if none exists, but it does not transfer data from SQLite or MariaDB. Set `INITIAL_ADMIN_PASSWORD` before initializing a new production database.

Do not point the production app at the new database until the existing data has been backed up, migrated, and reconciled. Never run `--reset-database` as a migration step.

On Windows, MariaDB may try password authentication and then fall back to GSSAPI when the password is not accepted. So this error can mean the app is using the wrong password as well as an account configured only for GSSAPI. First confirm that the active `.env` contains the correct `DB_USER` and `DB_PASSWORD`; the variable is `DB_PASSWORD` (not `DB_PASS`). If the user must be changed, use a dedicated application account with `mysql_native_password` as described below.

## Connection refused / Windows startup

Error 2003 / Windows 10061 means the configured endpoint refused the connection.
Check `Get-Service MariaDB`. For this installation, restore the existing service
from an Administrator PowerShell in the `ppmp` folder:

```powershell
& .\scripts\repair_mariadb_service.ps1
python app.py
```

The repair sets automatic startup and starts MariaDB; it does not change database
data. If Windows reports a service startup failure, inspect the MariaDB error log
and Windows Event Viewer before retrying. Never reset the database to fix a stopped
service. The app prints dependency-loading, database-checking, and server-starting
stages. Allow startup to finish; Ctrl+C interrupts Python and can produce
`KeyboardInterrupt` during any import, including before application code runs.

### Resolved configuration corruption (2026-09-25)

The MariaDB 12.2 `data/my.ini` file had been overwritten with unrelated text.
This caused service error 1067 and `Found option without preceding group` before
the server could start. The settings were restored to the existing 12.2 data
directory and port 3306. The service and PPMP startup were then verified.

The workspace `backups` directory contains both the original invalid file and
`mariadb-my.ini-working-20260925.ini`. Keep prose and application instructions
out of MariaDB's configuration file. Before restarting after a configuration
edit, validate its syntax without starting another database process:

```powershell
& 'C:\Program Files\MariaDB 12.2\bin\mysqld.exe' '--defaults-file=C:\Program Files\MariaDB 12.2\data\my.ini' --print-defaults
```

The working backup is specific to this installation; review paths and any later
configuration changes before restoring it.

## Fix for `auth_gssapi_client`

The `auth_gssapi_client` plugin is not supported by the configured connector. Do not use a Windows-integrated or GSSAPI-authenticated MariaDB account for this application. As a MariaDB administrator, create a dedicated least-privilege service account instead:

```sql
CREATE USER 'ppmp_user'@'localhost'
  IDENTIFIED VIA mysql_native_password USING PASSWORD('1234');
GRANT ALL PRIVILEGES ON ppmp_db.* TO 'ppmp_user'@'localhost';
FLUSH PRIVILEGES;
```

If `ppmp_user` already exists and is only used by this application, change it instead:

```sql
ALTER USER 'ppmp_user'@'localhost'
  IDENTIFIED VIA mysql_native_password USING PASSWORD('1234');
FLUSH PRIVILEGES;
```

Set `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, and `DATABASE_URL`, then run the read-only preflight:

```powershell
python scripts\db_preflight.py
```

After resolving every reported conflict and taking a verified backup, apply additive changes without starting the server:

```powershell
python app.py --migrate-only
```

Never use `python app.py --reset-database` to migrate an existing installation. That option intentionally deletes operational data and is only suitable for a disposable empty development database.

Use a different host value in the MariaDB account (for example, a specific application-server IP address) when the application and database run on different machines. Do not grant access to `%` unless that is explicitly required and protected by network controls.
