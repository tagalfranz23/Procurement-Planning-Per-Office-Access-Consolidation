"""One-time, guarded transfer of the local PPMP SQLite data to Render Postgres.

Run from the local PPMP project with DATABASE_URL set to the Render External
Database URL. This script does not print the URL and resumes only when every
existing destination row exactly matches the local source.
"""

from __future__ import annotations

import os
import secrets
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Enum, String, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url


APP_DIR = Path(__file__).resolve().parent.parent
SOURCE_DB = APP_DIR / "ppmp.sqlite"


def abort(message: str) -> None:
    print(f"Migration stopped: {message}", file=sys.stderr)
    raise SystemExit(1)


def comparable(value):
    """Return a hashable, stable representation for cross-database row checks."""
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, Decimal):
        return ("decimal", value.normalize())
    if isinstance(value, dict):
        return ("mapping", tuple(sorted((str(key), comparable(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(comparable(item) for item in value))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ("bytes", bytes(value))
    return value


def row_key(row, primary_key_columns):
    return tuple(comparable(row[column.name]) for column in primary_key_columns)


def rows_match(left, right, column_names):
    return all(comparable(left[name]) == comparable(right[name]) for name in column_names)


def main() -> None:
    phase = "validating connection settings"
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        abort("DATABASE_URL is not set. Set it to the private Render External Database URL.")

    try:
        parsed_url = make_url(database_url)
    except Exception:
        abort("DATABASE_URL is not a valid connection URL.")

    if parsed_url.get_backend_name() != "postgresql":
        abort("The destination must be PostgreSQL.")
    if not (parsed_url.host or "").lower().endswith(".render.com"):
        abort("The destination host does not look like a Render external database host.")
    if not SOURCE_DB.is_file():
        abort(f"The local source database was not found at {SOURCE_DB}.")

    # Import the existing app configuration only after validating the destination.
    # The per-process settings below do not change the project's .env file.
    os.environ["FLASK_ENV"] = "development"
    os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_urlsafe(32))
    sys.path.insert(0, str(APP_DIR))
    try:
        from app import app, migrate_revision_schema
        from models import db
    except Exception as error:
        abort(f"Could not load the existing application dependencies ({type(error).__name__}).")

    source_engine = create_engine(
        f"sqlite:///{SOURCE_DB.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        phase = "reading the local database"
        with source_engine.connect() as source_connection:
            source_connection.exec_driver_sql("PRAGMA query_only=ON")
            source_connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            check = source_connection.exec_driver_sql("PRAGMA quick_check").scalar_one()
            if check != "ok":
                abort("The local SQLite database did not pass its integrity check.")

            model_tables = set(db.metadata.tables)
            source_tables = set(inspect(source_engine).get_table_names()) - {"sqlite_sequence"}
            if source_tables != model_tables:
                missing = sorted(model_tables - source_tables)
                extra = sorted(source_tables - model_tables)
                abort(f"Source table mismatch (missing={missing}, extra={extra}).")

            row_counts: dict[str, int] = {}
            source_rows_by_table: dict[str, list[dict]] = {}
            oversized_columns: dict[tuple[str, str], int] = {}
            for table in db.metadata.sorted_tables:
                source_columns = {
                    column["name"]
                    for column in inspect(source_engine).get_columns(table.name)
                }
                model_columns = set(table.columns.keys())
                if source_columns != model_columns:
                    abort(f"Column mismatch in the local {table.name} table.")
                row_counts[table.name] = source_connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
                source_rows_by_table[table.name] = [
                    dict(row)
                    for row in source_connection.execute(select(table)).mappings().all()
                ]
                for column in table.columns:
                    limit = getattr(column.type, "length", None)
                    if not limit or not isinstance(column.type, String) or isinstance(column.type, Enum):
                        continue
                    source_max_length = source_connection.execute(
                        select(func.max(func.length(column))).select_from(table)
                    ).scalar_one()
                    if source_max_length and source_max_length > limit:
                        oversized_columns[(table.name, column.name)] = int(source_max_length)

            active_admins = source_connection.execute(text(
                "SELECT COUNT(*) FROM users "
                "WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND is_active IS TRUE"
            )).scalar_one()
            if active_admins < 1:
                abort("The local database has no active Admin account to transfer.")

            with app.app_context():
                phase = "checking existing Render data against the local source"
                target_inspector = inspect(db.engine)
                target_tables = set(target_inspector.get_table_names())
                unexpected_tables = sorted(target_tables - model_tables)
                if unexpected_tables:
                    abort(f"The Render database contains unexpected tables: {unexpected_tables}.")

                already_present_keys: dict[str, set[tuple]] = {}
                already_present_counts: dict[str, int] = {}
                for table_name in sorted(target_tables & model_tables):
                    table = db.metadata.tables[table_name]
                    phase = f"verifying existing Render rows in {table_name}"
                    primary_key_columns = list(table.primary_key.columns)
                    if not primary_key_columns:
                        abort(f"Cannot safely resume because {table_name} has no primary key.")
                    source_rows = source_rows_by_table[table_name]
                    source_by_key = {
                        row_key(row, primary_key_columns): row for row in source_rows
                    }
                    target_rows = db.session.execute(select(table)).mappings().all()
                    existing_keys = set()
                    column_names = list(table.columns.keys())
                    for target_row in target_rows:
                        key = row_key(target_row, primary_key_columns)
                        source_row = source_by_key.get(key)
                        if source_row is None or not rows_match(target_row, source_row, column_names):
                            abort(
                                f"Render table {table_name} contains data that does not match "
                                "the local source. No rows were changed; review the destination first."
                            )
                        existing_keys.add(key)
                    already_present_keys[table_name] = existing_keys
                    already_present_counts[table_name] = len(existing_keys)

                # Build the app's existing schema and additive revisions without
                # creating a placeholder Admin that could collide with the source.
                phase = "initializing the Render schema"
                db.create_all()
                migrate_revision_schema()

                preparer = db.engine.dialect.identifier_preparer
                with db.engine.begin() as target_connection:
                    imported_counts: dict[str, int] = {}
                    for table in db.metadata.sorted_tables:
                        phase = f"importing table {table.name}"
                        source_rows = source_rows_by_table[table.name]
                        primary_key_columns = list(table.primary_key.columns)
                        existing_keys = already_present_keys.get(table.name, set())
                        rows = [
                            row for row in source_rows
                            if row_key(row, primary_key_columns) not in existing_keys
                        ]
                        if rows:
                            # SQLite does not enforce VARCHAR lengths. Widen only
                            # destination columns whose source text exceeds the
                            # model limit, preserving every character unchanged.
                            for column in table.columns:
                                required_length = oversized_columns.get((table.name, column.name))
                                if required_length:
                                    quoted_table = preparer.quote(table.name)
                                    quoted_column = preparer.quote(column.name)
                                    target_connection.execute(text(
                                        f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} "
                                        f"TYPE VARCHAR({required_length})"
                                    ))
                            target_connection.execute(table.insert(), [dict(row) for row in rows])
                        imported_counts[table.name] = len(rows)

                    # Preserve the source IDs and advance PostgreSQL identity
                    # sequences so subsequent application inserts do not collide.
                    phase = "preserving generated ID sequences"
                    for table in db.metadata.sorted_tables:
                        auto_column = getattr(table, "autoincrement_column", None)
                        if auto_column is None:
                            continue
                        max_id = target_connection.execute(
                            select(func.max(auto_column))
                        ).scalar_one()
                        if max_id is None:
                            continue
                        sequence = target_connection.execute(text(
                            "SELECT pg_get_serial_sequence(:table_name, :column_name)"
                        ), {
                            "table_name": table.name,
                            "column_name": auto_column.name,
                        }).scalar_one_or_none()
                        if sequence:
                            target_connection.execute(text(
                                "SELECT setval(CAST(:sequence_name AS regclass), :last_id, true)"
                            ), {"sequence_name": sequence, "last_id": max_id})

                    for table in db.metadata.sorted_tables:
                        phase = f"verifying table {table.name}"
                        actual_count = target_connection.execute(
                            select(func.count()).select_from(table)
                        ).scalar_one()
                        if actual_count != row_counts[table.name]:
                            raise RuntimeError(
                                f"Row count mismatch in {table.name}: "
                                f"expected {row_counts[table.name]}, got {actual_count}."
                            )

                total = sum(imported_counts.values())
                already_present_total = sum(already_present_counts.values())
                print(
                    f"Transfer completed: {total + already_present_total} records verified "
                    f"across {len(imported_counts)} tables "
                    f"({total} inserted, {already_present_total} already present and verified)."
                )
                for table_name, count in imported_counts.items():
                    if count:
                        print(f"  {table_name}: {count}")
                for (table_name, column_name), required_length in sorted(oversized_columns.items()):
                    print(
                        f"  widened {table_name}.{column_name} to VARCHAR({required_length}) "
                        "to preserve existing text"
                    )
                print("The local SQLite source was opened read-only and was not changed.")
    except SystemExit:
        raise
    except Exception as error:
        # Do not print exception text: database-driver errors can include endpoint details.
        database_error = getattr(error, "orig", error)
        sqlstate = getattr(database_error, "sqlstate", None) or getattr(database_error, "pgcode", None)
        state_detail = f", SQLSTATE {sqlstate}" if sqlstate else ""
        abort(
            f"{phase} failed ({type(database_error).__name__}{state_detail}). "
            "No partial row import was committed; review the Render database before retrying."
        )
    finally:
        source_engine.dispose()


if __name__ == "__main__":
    main()
