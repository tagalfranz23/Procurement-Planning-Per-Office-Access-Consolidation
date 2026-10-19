"""Add the revised workflow schema without rewriting historical records.

Called only by the application's explicit ``--migrate-only`` path after
``metadata.create_all``. This module never connects or changes data on import.
"""

from sqlalchemy import inspect, text


WORKFLOW_REQUIRED_COLUMNS = {
    'ppmp_notifications': ('target_type', 'target_id', 'action_stage', 'resolved_at'),
    'ppmp_orders': ('workflow_official', 'return_stage'),
    'ppmp_records': ('source_order_id', 'ppmp_document_number'),
    'annual_procurement_plans': (
        'workflow_version', 'current_review_role', 'return_review_role',
        'revision', 'supplemental_parent_id',
    ),
    'app_items': ('quantity', 'unit_size', 'merge_key'),
    'app_approvals': ('reviewer_role', 'snapshot'),
}

WORKFLOW_REQUIRED_TABLES = (
    'official_ppmps', 'app_workflow_registry', 'app_batch_links',
    'app_item_contributions', 'indicative_ppmp_copies',
)

# Shared with the application's read-only startup check.
workflow_required_columns = {
    table_name: set(column_names)
    for table_name, column_names in WORKFLOW_REQUIRED_COLUMNS.items()
}


def apply_workflow_migrations(db):
    """Apply idempotent additive DDL; retain all legacy orders and APPs.

    Existing orders are intentionally left ``workflow_official = false``.
    Official registrations are created only when an office submits through the
    revised workflow. Existing APPs stay on workflow version 1.
    """
    engine = db.engine
    dialect = engine.dialect
    quote = dialect.identifier_preparer.quote
    changes = {'created_tables': [], 'added_columns': [], 'widened_columns': []}

    # ``create_all`` is also used by the caller. Keeping this step here makes
    # the helper safe to rerun independently during an explicit migration.
    existing_tables = set(inspect(engine).get_table_names())
    for name in WORKFLOW_REQUIRED_TABLES:
        if name not in existing_tables:
            db.metadata.tables[name].create(bind=engine, checkfirst=True)
            changes['created_tables'].append(name)

    with engine.begin() as connection:
        for table_name, column_names in WORKFLOW_REQUIRED_COLUMNS.items():
            existing_columns = {
                column['name'] for column in inspect(connection).get_columns(table_name)
            }
            for column_name in column_names:
                if column_name in existing_columns:
                    continue
                column = db.metadata.tables[table_name].c[column_name]
                definition = str(column.type.compile(dialect=dialect))
                if not column.nullable:
                    definition += ' NOT NULL'
                if column.server_default is not None:
                    default_value = str(column.server_default.arg)
                    if dialect.name == 'postgresql' and column.type.python_type is bool:
                        default_value = 'false' if default_value == '0' else 'true'
                    definition += ' DEFAULT ' + default_value
                # A nullable REFERENCES column can be added to SQLite without
                # a table rebuild. Other dialects get a named FK below.
                if dialect.name == 'sqlite' and column.foreign_keys:
                    foreign_key = next(iter(column.foreign_keys))
                    target = foreign_key.column
                    definition += (
                        f' REFERENCES {quote(target.table.name)} ({quote(target.name)})'
                        f' ON DELETE {foreign_key.ondelete}'
                    )
                connection.execute(text(
                    f'ALTER TABLE {quote(table_name)} ADD COLUMN {quote(column_name)} {definition}'
                ))
                changes['added_columns'].append(f'{table_name}.{column_name}')

        # A nullable unique index accepts legacy rows with no source order.
        # It prevents two indicative copies referencing the same official PPMP.
        unique_name = 'uq_ppmp_record_source_order'
        record_constraints = inspect(connection).get_unique_constraints('ppmp_records')
        record_indexes = inspect(connection).get_indexes('ppmp_records')
        has_unique_source = any(
            list(constraint.get('column_names') or []) == ['source_order_id']
            for constraint in record_constraints
        ) or any(
            index.get('unique') and list(index.get('column_names') or []) == ['source_order_id']
            for index in record_indexes
        )
        if not has_unique_source:
            connection.execute(text(
                f'CREATE UNIQUE INDEX {quote(unique_name)} ON '
                f'{quote("ppmp_records")} ({quote("source_order_id")})'
            ))

        if dialect.name != 'sqlite':
            for table_name, column_name, target_table in (
                ('ppmp_records', 'source_order_id', 'ppmp_orders'),
                ('annual_procurement_plans', 'supplemental_parent_id', 'annual_procurement_plans'),
            ):
                foreign_keys = inspect(connection).get_foreign_keys(table_name)
                if not any(
                    list(foreign_key.get('constrained_columns') or []) == [column_name]
                    for foreign_key in foreign_keys
                ):
                    constraint_name = f'fk_workflow_{table_name}_{column_name}'
                    connection.execute(text(
                        f'ALTER TABLE {quote(table_name)} ADD CONSTRAINT {quote(constraint_name)} '
                        f'FOREIGN KEY ({quote(column_name)}) REFERENCES {quote(target_table)} '
                        f'({quote("id")}) ON DELETE RESTRICT'
                    ))

        merge_indexes = inspect(connection).get_indexes('app_items')
        if not any(
            list(index.get('column_names') or []) == ['merge_key'] for index in merge_indexes
        ):
            connection.execute(text(
                f'CREATE INDEX {quote("ix_app_items_merge_key")} '
                f'ON {quote("app_items")} ({quote("merge_key")})'
            ))

        # Preserve the full official method label when copying to the PPMP or
        # APP. SQLite does not enforce VARCHAR length, so no rebuild is needed.
        if dialect.name in {'mysql', 'mariadb', 'postgresql'}:
            for table_name, column_name in (
                ('ppmp_items', 'mode_of_procurement'),
                ('ppmp_record_items', 'procurement_method'),
                ('app_items', 'mode_of_procurement'),
            ):
                columns = inspect(connection).get_columns(table_name)
                existing_column = next(column for column in columns if column['name'] == column_name)
                existing_length = getattr(existing_column['type'], 'length', None)
                if existing_length is None or existing_length >= 255:
                    continue
                if dialect.name == 'postgresql':
                    statement = (
                        f'ALTER TABLE {quote(table_name)} ALTER COLUMN {quote(column_name)} '
                        'TYPE VARCHAR(255)'
                    )
                else:
                    null_clause = 'NULL' if existing_column.get('nullable') else 'NOT NULL'
                    statement = (
                        f'ALTER TABLE {quote(table_name)} MODIFY COLUMN {quote(column_name)} '
                        f'VARCHAR(255) {null_clause}'
                    )
                connection.execute(text(statement))
                changes['widened_columns'].append(f'{table_name}.{column_name}')

    return changes
