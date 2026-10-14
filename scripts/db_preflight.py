"""Read-only MariaDB migration preflight. This script never changes data."""
import os
import sys

import mysql.connector


def rows(cursor, statement):
    cursor.execute(statement)
    return cursor.fetchall()


def user_reference_counts(cursor, user_id):
    """Return non-empty foreign-key references without changing the account or history."""
    foreign_keys = rows(cursor, """
        SELECT k.TABLE_NAME AS table_name, k.COLUMN_NAME AS column_name,
               r.DELETE_RULE AS delete_rule
        FROM information_schema.KEY_COLUMN_USAGE AS k
        JOIN information_schema.REFERENTIAL_CONSTRAINTS AS r
          ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
         AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME
         AND r.TABLE_NAME = k.TABLE_NAME
        WHERE k.CONSTRAINT_SCHEMA = DATABASE()
          AND k.REFERENCED_TABLE_NAME = 'users'
        ORDER BY k.TABLE_NAME, k.COLUMN_NAME
    """)
    references = []
    for foreign_key in foreign_keys:
        table_name = foreign_key['table_name'].replace('`', '``')
        column_name = foreign_key['column_name'].replace('`', '``')
        cursor.execute(
            f'SELECT COUNT(1) AS count FROM `{table_name}` WHERE `{column_name}` = %s',
            (user_id,),
        )
        count = cursor.fetchone()['count']
        if count:
            references.append({**foreign_key, 'count': count})
    return references


def main():
    connection = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', '123'),
        database=os.getenv('DB_NAME', 'ppmp_db'),
        connection_timeout=5,
    )
    cursor = connection.cursor(dictionary=True)
    cursor.execute('SELECT DATABASE() AS db, VERSION() AS version')
    print('Connection:', cursor.fetchone())
    tables = {next(iter(row.values())) for row in rows(cursor, 'SHOW TABLES')}
    print('Tables:', len(tables), ', '.join(sorted(tables)))
    blockers = []
    if 'users' in tables:
        role_column = rows(cursor, "SHOW COLUMNS FROM users LIKE 'role'")[0]
        print('Role column:', role_column)
        role_counts = rows(cursor, 'SELECT role, COUNT(1) AS count FROM users WHERE role IS NOT NULL GROUP BY role ORDER BY role')
        duplicate_roles = [row for row in role_counts if row['count'] > 1]
        duplicate_emails = rows(cursor, 'SELECT email, COUNT(1) AS count FROM users GROUP BY email HAVING COUNT(1) > 1')
        legacy_roles = [row for row in role_counts if row['role'] and row['role'].lower() in {'ppmp_user', 'app_user', 'office_user', 'college_encoder', 'viewer', 'budget_officer'}]
        print('Role counts:', role_counts)
        print('Duplicate emails:', duplicate_emails)
        print('Legacy placeholder roles:', legacy_roles)
        if legacy_roles:
            placeholders = ','.join("'" + row['role'].replace("'", "''") + "'" for row in legacy_roles)
            accounts = rows(cursor, f'SELECT id, username, email, office, college_id, role, is_active FROM users WHERE role IN ({placeholders})')
            print('Accounts requiring role mapping:', accounts)
            for account in accounts:
                print(
                    f"Historical references for user {account['id']} ({account['username']}):",
                    user_reference_counts(cursor, account['id']),
                )
        blockers.extend(('duplicate roles', duplicate_roles) if duplicate_roles else ())
        blockers.extend(('duplicate emails', duplicate_emails) if duplicate_emails else ())
        blockers.extend(('legacy roles', legacy_roles) if legacy_roles else ())
    if 'annual_procurement_plans' in tables:
        app_count = rows(cursor, 'SELECT COUNT(1) AS count FROM annual_procurement_plans')[0]['count']
        print('Existing APP records:', app_count)
        columns = {row['Field'] for row in rows(cursor, 'SHOW COLUMNS FROM annual_procurement_plans')}
        if 'consolidation_batch_id' in columns:
            if 'source_type' in columns:
                external = rows(cursor, """
                    SELECT COUNT(1) AS count FROM annual_procurement_plans
                    WHERE consolidation_batch_id IS NULL
                      AND source_type IN ('REFERENCE_IMAGES', 'REFERENCE_DOCUMENTS')
                """)[0]['count']
                unlinked = rows(cursor, """
                    SELECT COUNT(1) AS count FROM annual_procurement_plans
                    WHERE consolidation_batch_id IS NULL
                      AND source_type NOT IN ('REFERENCE_IMAGES', 'REFERENCE_DOCUMENTS')
                """)[0]['count']
                print('Authorized external-source APP records:', external)
                print('APP records requiring batch reconciliation:', unlinked)
            else:
                unlinked = rows(cursor, 'SELECT COUNT(1) AS count FROM annual_procurement_plans WHERE consolidation_batch_id IS NULL')[0]['count']
                print('APP records requiring batch reconciliation:', unlinked)
        else:
            print('APP consolidation column: not installed yet')
    connection.close()
    if blockers:
        print('Migration readiness: BLOCKED — reconcile the findings above first.')
        return 2
    print('Migration readiness: no read-only conflicts detected.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
