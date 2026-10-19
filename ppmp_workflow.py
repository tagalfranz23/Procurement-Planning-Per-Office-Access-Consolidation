"""Official office PPMPs and independent indicative report copies."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from models import (
    College, IndicativePPMPCopy, OfficialPPMP, PPMPOrder, PPMPOrderItem,
    PPMPComment, WorkflowAuditLog, WishlistItem, db,
)


def can_edit_official_ppmp(user, order):
    return bool(user and order.requested_by == user.id
                and order.office_id == user.college_id
                and order.status in {'Draft', 'Returned'})


def workflow_history(entity_type, entity_id):
    return [{
        'id': row.id, 'action': row.action, 'details': row.details,
        'author': row.performer.full_name if row.performer else 'System',
        'created_at': row.created_at.isoformat() if row.created_at else None,
    } for row in WorkflowAuditLog.query.filter_by(
        entity_type=entity_type, entity_id=entity_id,
    ).order_by(WorkflowAuditLog.id).all()]


def can_access_copy(user, copy):
    return bool(user and (user.role in {'ADMIN', 'PROCUREMENT', 'EO', 'BUDGET', 'BAC CHAIRMAN'}
                         or user.college_id == copy.office_id))


def can_edit_copy(user, copy):
    return bool(user and (user.role == 'ADMIN' or (
        user.id == copy.prepared_by and user.college_id == copy.office_id)))


def create_indicative_copy(application, user, source_order):
    """Snapshot approved data once. Subsequent opens preserve the user's saved copy."""
    official = OfficialPPMP.query.filter_by(source_order_id=source_order.id).first()
    if not official or not source_order.workflow_official:
        raise ValueError('Select the official PPMP for this office and fiscal year.')
    if source_order.status not in {'Approved', 'Processing', 'Completed'}:
        raise ValueError('An indicative copy can be generated only from an approved official PPMP.')
    if user.role != 'ADMIN' and (
        source_order.office_id != user.college_id or source_order.requested_by != user.id
    ):
        raise PermissionError('Only the preparing office or Admin can create this indicative copy.')
    existing = IndicativePPMPCopy.query.filter_by(source_order_id=source_order.id).first()
    if existing:
        return existing, False
    rows = []
    for item in source_order.items:
        row = application.ppmp_request_report_item(item, source_order)
        row['quantity'] = str(item.quantity)
        row['unit'] = item.unit
        row['estimated_budget'] = str(item.estimated_budget)
        row['source_item_id'] = item.id
        rows.append(row)
    copy = IndicativePPMPCopy(
        reference_number=f'IND-{source_order.reference_number}',
        source_order_id=source_order.id, office_id=source_order.office_id,
        fiscal_year=source_order.fiscal_year, prepared_by=source_order.requested_by,
        ppmp_document_number=source_order.ppmp_document_number,
        items=deepcopy(rows),
    )
    db.session.add(copy)
    db.session.flush()
    application.audit('indicative_ppmp', copy.id, 'INDICATIVE_COPY_CREATED', {
        'source_order_id': source_order.id, 'source_reference': source_order.reference_number,
        'items': rows,
    })
    return copy, True


def indicative_report_payload(copy, user):
    rows = deepcopy(copy.items or [])
    for row in rows:
        row['quantity'] = float(Decimal(str(row.get('quantity', 0))))
        row['estimated_budget'] = float(Decimal(str(row.get('estimated_budget', 0))))
        row['quantity_and_size'] = f"{row['quantity']:g} {row.get('unit', '')}"
    return {
        'id': copy.id, 'source_type': 'indicative', 'is_official': False,
        'source_order_id': copy.source_order_id,
        'reference_number': copy.reference_number, 'fiscal_year': copy.fiscal_year,
        'status': 'Indicative Copy', 'ppmp_document_number': copy.ppmp_document_number,
        'end_user_or_implementing_unit': copy.office.name if copy.office else '',
        'editable': can_edit_copy(user, copy), 'items': rows,
        'save_url': f'/api/ppmp-indicative-copies/{copy.id}/report',
        'open_url': f'/api/ppmp-indicative-copies/{copy.id}/report',
        'export_base': f'/api/ppmp-indicative-copies/{copy.id}/export',
        'history': workflow_history('indicative_ppmp', copy.id), 'comments': [],
    }


def positive_decimal(value, label, *, allow_zero=False, precision=2):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be numeric.')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{label} must be numeric.') from None
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f'{label} must be {"zero or greater" if allow_zero else "greater than zero"}.')
    if number > Decimal('9999999999.99') or number != number.quantize(Decimal(10) ** -precision):
        raise ValueError(f'{label} must have at most {precision} decimal places and be within the supported range.')
    return number


def extended_report_changes(application, data):
    """Validate the editable snapshot fields; master catalog entries are never modified."""
    extra = {'general_description', 'quantity', 'unit', 'unit_size', 'estimated_budget', 'supporting_documents'}
    if not isinstance(data, dict) or not data:
        raise ValueError('Provide report fields to update.')
    controlled = {key: value for key, value in data.items() if key not in extra}
    changes = application.ppmp_request_report_item_changes(controlled) if controlled else {}
    for field, maximum in (('general_description', 300), ('unit', 60), ('unit_size', 60), ('supporting_documents', 5000)):
        if field in data:
            value = str(data[field] or '').strip()
            if (field != 'supporting_documents' and not value) or len(value) > maximum:
                raise ValueError(f'{field.replace("_", " ").capitalize()} is required and must not exceed {maximum} characters.')
            changes['unit' if field == 'unit_size' else field] = value
    if 'quantity' in data:
        changes['quantity'] = positive_decimal(data['quantity'], 'Quantity')
    if 'estimated_budget' in data:
        changes['estimated_budget'] = positive_decimal(data['estimated_budget'], 'Estimated budget', allow_zero=True)
    return changes


def validate_report_timeline(item, changes):
    get_value = lambda key: changes.get(key, getattr(item, key, None))
    start, end, delivery = (get_value(key) for key in ('procurement_start', 'procurement_end', 'delivery_period'))
    if start and end and end < start:
        raise ValueError('Procurement end cannot be earlier than procurement start.')
    if end and delivery and delivery < end:
        raise ValueError('Expected delivery cannot be earlier than procurement end.')


def copy_document_adapter(copy):
    rows = []
    for saved in copy.items or []:
        row = dict(saved)
        row.update(item_name=row.get('general_description', ''), unit=row.get('unit', ''),
                   quantity=Decimal(str(row.get('quantity', 0))),
                   estimated_budget=Decimal(str(row.get('estimated_budget', 0))))
        row['pre_procurement_conference'] = (
            True if row.get('pre_procurement_conference') == 'Yes'
            else False if row.get('pre_procurement_conference') == 'No' else None)
        for key in ('procurement_start', 'procurement_end', 'delivery_period'):
            row[key] = datetime.strptime(row[key], '%Y-%m').date() if row.get(key) else None
        rows.append(SimpleNamespace(**row))
    return SimpleNamespace(
        id=copy.id, reference_number=copy.reference_number, fiscal_year=copy.fiscal_year,
        ppmp_document_number=copy.ppmp_document_number, office=copy.office, items=rows,
    )


def register_ppmp_workflow_routes(application):
    app = application.app

    @app.before_request
    def validate_workflow_json_body():
        if request.method not in {'POST', 'PUT'} or not request.path.startswith((
            '/api/ppmp-orders', '/api/ppmp-indicative-copies', '/api/consolidation-batches',
            '/api/apps', '/api/reports/ppmp-orders',
        )):
            return None
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Provide a JSON object for this workflow action.'}), 400
        if 'action' in data and not isinstance(data['action'], str):
            return jsonify({'error': 'The workflow action must be a string.'}), 400
        if 'note' in data and data['note'] is not None and not isinstance(data['note'], str):
            return jsonify({'error': 'The review note must be text.'}), 400
        return None

    @app.route('/api/ppmp-orders/<int:order_id>/items', methods=['POST'])
    @application.permission_required('ppmp.order.create')
    def append_official_ppmp_items(order_id):
        order = PPMPOrder.query.filter_by(id=order_id).with_for_update().one_or_none()
        user = application.current_session_user()
        if not order:
            return jsonify({'error': 'Official PPMP not found.'}), 404
        if not order.workflow_official or not can_edit_official_ppmp(user, order):
            return jsonify({'error': 'Only the creator can add items to their Draft or Returned official PPMP.'}), 403
        data = request.get_json(silent=True)
        rows = data.get('items') if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows or len(rows) + len(order.items) > 100:
            return jsonify({'error': 'An official PPMP must contain between 1 and 100 items.'}), 400
        existing_master_ids = {item.master_item_id for item in order.items if item.master_item_id}
        validated = []
        try:
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('Each selected item must be an object.')
                quantity = positive_decimal(row.get('quantity'), 'Quantity')
                master_id = row.get('master_item_id')
                if master_id is not None:
                    if type(master_id) is not int or master_id in existing_master_ids:
                        raise ValueError('A catalog item can appear only once in the PPMP.')
                    master = db.session.get(WishlistItem, master_id)
                    if not master or master.status != 'Available':
                        raise ValueError('Select an available CSE Master List item.')
                    existing_master_ids.add(master_id)
                    values = dict(item_name=master.item_description, description=master.remarks,
                                  unit=master.unit, category=master.category,
                                  estimated_unit_cost=Decimal(master.estimated_cost),
                                  master_item_id=master_id, is_custom_item=False)
                else:
                    values = {key: str(row.get(key) or '').strip() for key in ('item_name', 'unit', 'category', 'description')}
                    if not values['item_name'] or len(values['item_name']) > 300 or not values['unit'] or len(values['unit']) > 60:
                        raise ValueError('Provide an item name (up to 300 characters) and unit (up to 60 characters).')
                    if values['category'] not in application.PPMP_ORDER_CATEGORIES or len(values['description']) > 5000:
                        raise ValueError('Select a valid item category and description.')
                    values.update(estimated_unit_cost=positive_decimal(row.get('estimated_unit_cost'), 'Unit cost', allow_zero=True),
                                  is_custom_item=True)
                budget = (quantity * values['estimated_unit_cost']).quantize(Decimal('.01'))
                if budget > Decimal('9999999999999999.99'):
                    raise ValueError('The estimated budget exceeds the supported range.')
                validated.append(dict(values, quantity=quantity, estimated_budget=budget))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        for values in validated:
            db.session.add(PPMPOrderItem(order_id=order.id, created_by=user.id, **values))
        db.session.flush()
        application.audit('ppmp_order', order.id, 'OFFICIAL_ITEMS_ADDED', {'count': len(validated), 'status': order.status})
        db.session.commit()
        return jsonify(application.ppmp_request_report_payload(order, user)), 201

    @app.route('/api/ppmp-orders/<int:order_id>/items/<int:item_id>', methods=['DELETE'])
    @application.permission_required('ppmp.order.create')
    def remove_official_ppmp_item(order_id, item_id):
        order = PPMPOrder.query.filter_by(id=order_id).with_for_update().one_or_none()
        user = application.current_session_user()
        if not order:
            return jsonify({'error': 'Official PPMP not found.'}), 404
        if not order.workflow_official or not can_edit_official_ppmp(user, order):
            return jsonify({'error': 'Only the creator can remove items from their Draft or Returned PPMP.'}), 403
        item = next((row for row in order.items if row.id == item_id), None)
        if not item:
            return jsonify({'error': 'This item does not belong to the selected PPMP.'}), 404
        if len(order.items) <= 1:
            return jsonify({'error': 'Keep at least one item in the official PPMP.'}), 409
        if item.ppmp_item_id:
            return jsonify({'error': 'An approved source item cannot be removed.'}), 409
        application.audit('ppmp_order', order.id, 'OFFICIAL_ITEM_REMOVED', {'item': application.ppmp_request_report_item(item, order)})
        db.session.delete(item)
        db.session.commit()
        return jsonify({'deleted': item_id})

    @app.route('/api/ppmp-orders/<int:order_id>/designate-official', methods=['POST'])
    @application.permission_required('admin.manage')
    def designate_official_ppmp(order_id):
        user = application.current_session_user()
        if user.role != 'ADMIN':
            return jsonify({'error': 'Only Admin can designate an existing official PPMP.'}), 403
        order = PPMPOrder.query.filter_by(id=order_id).with_for_update().one_or_none()
        if not order:
            return jsonify({'error': 'PPMP not found.'}), 404
        if not order.office_id or order.status == 'Rejected':
            return jsonify({'error': 'Choose a PPMP linked to an office that has not been rejected.'}), 409
        registry = OfficialPPMP.query.filter_by(office_id=order.office_id, fiscal_year=order.fiscal_year).first()
        if registry and registry.source_order_id != order.id:
            return jsonify({'error': 'This office already has an official PPMP for that fiscal year.'}), 409
        if not registry:
            db.session.add(OfficialPPMP(office_id=order.office_id, fiscal_year=order.fiscal_year, source_order_id=order.id))
        order.workflow_official = True
        if order.status == 'Requested':
            order.status = 'Draft'
        application.audit('ppmp_order', order.id, 'OFFICIAL_PPMP_DESIGNATED', {'fiscal_year': order.fiscal_year, 'office_id': order.office_id})
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'An official PPMP was already assigned. Refresh the records list.'}), 409
        return jsonify(order.to_dict())

    @app.route('/api/ppmp-indicative-copies', methods=['GET', 'POST'])
    @application.permission_required('ppmp.record.view')
    def indicative_copies():
        user = application.current_session_user()
        if request.method == 'GET':
            query = IndicativePPMPCopy.query
            if application.is_ppmp_office_role(user.role):
                query = query.filter_by(office_id=user.college_id) if user.college_id else query.filter(db.false())
            return jsonify([dict(copy.to_dict(), source_type='indicative', editable=can_edit_copy(user, copy), can_delete=can_edit_copy(user, copy),
                                 open_url=f'/api/ppmp-indicative-copies/{copy.id}/report')
                            for copy in query.order_by(IndicativePPMPCopy.created_at.desc()).all()])
        return create_copy_response(application, user)

    @app.route('/api/ppmp-indicative-copies/<int:copy_id>', methods=['DELETE'])
    @application.permission_required('ppmp.record.view')
    def delete_indicative_copy(copy_id):
        copy = db.session.get(IndicativePPMPCopy, copy_id)
        user = application.current_session_user()
        if not copy:
            return jsonify({'error': 'Indicative copy not found.'}), 404
        if not can_edit_copy(user, copy):
            return jsonify({'error': 'Only the copy owner or Admin can delete this indicative copy.'}), 403
        application.audit('indicative_ppmp', copy.id, 'INDICATIVE_COPY_DELETED', {
            'reference_number': copy.reference_number, 'source_order_id': copy.source_order_id,
            'items': deepcopy(copy.items),
        })
        db.session.delete(copy)
        db.session.commit()
        return jsonify({'deleted': copy_id})

    @app.route('/api/ppmp-orders/<int:order_id>/indicative-copy', methods=['POST'])
    @application.permission_required('ppmp.record.view')
    def copy_from_order(order_id):
        return create_copy_response(application, application.current_session_user(), order_id)

    @app.route('/api/ppmp-indicative-copies/<int:copy_id>/report', methods=['GET', 'PUT'])
    @application.permission_required('ppmp.record.view')
    def indicative_report(copy_id):
        copy = db.session.get(IndicativePPMPCopy, copy_id)
        user = application.current_session_user()
        if not copy:
            return jsonify({'error': 'Indicative copy not found.'}), 404
        if not can_access_copy(user, copy):
            return jsonify({'error': 'You cannot access another office\'s indicative copy.'}), 403
        if request.method == 'PUT':
            if not can_edit_copy(user, copy):
                return jsonify({'error': 'Only the copy owner or Admin can edit this indicative copy.'}), 403
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) - {'items', 'ppmp_document_number'} or not isinstance(data.get('items'), list):
                return jsonify({'error': 'Provide valid indicative report changes.'}), 400
            number = data.get('ppmp_document_number', copy.ppmp_document_number)
            if type(number) is not int or not 1 <= number <= 999999999:
                return jsonify({'error': 'PPMP document number must be a positive whole number.'}), 400
            rows = deepcopy(copy.items or [])
            by_id = {row['id']: row for row in rows}
            seen = set()
            try:
                for change in data['items']:
                    if not isinstance(change, dict) or set(change) != {'id', 'fields'}:
                        raise ValueError('Each report change needs an id and fields.')
                    row_id = change['id']
                    if type(row_id) is not int or row_id not in by_id or row_id in seen:
                        raise ValueError('Each changed row must belong to this copy and appear once.')
                    seen.add(row_id)
                    changes = extended_report_changes(application, change['fields'])
                    saved = by_id[row_id]
                    dates = {key: datetime.strptime(saved[key], '%Y-%m').date() if saved.get(key) else None
                             for key in ('procurement_start', 'procurement_end', 'delivery_period')}
                    validate_report_timeline(SimpleNamespace(**dates), changes)
                    for key, value in changes.items():
                        if key in dates:
                            value = value.isoformat()[:7] if value else ''
                        elif key == 'pre_procurement_conference':
                            value = 'Yes' if value is True else 'No' if value is False else ''
                        elif isinstance(value, Decimal):
                            value = str(value)
                        saved[key] = value or ''
            except (ValueError, TypeError) as error:
                return jsonify({'error': str(error)}), 400
            before = {'ppmp_document_number': copy.ppmp_document_number, 'items': deepcopy(copy.items)}
            copy.items, copy.ppmp_document_number = rows, number
            copy.updated_at = datetime.utcnow()
            application.audit('indicative_ppmp', copy.id, 'INDICATIVE_COPY_SAVED', {
                'before': before, 'after': {'ppmp_document_number': number, 'items': rows},
                'source_order_id': copy.source_order_id,
            })
            db.session.commit()
        payload = indicative_report_payload(copy, user)
        payload.update(procurement_types=application.PPMP_ORDER_TYPES,
                       procurement_methods=application.PPMP_REPORT_PROCUREMENT_METHODS,
                       fund_sources=application.PPMP_ORDER_FUND_SOURCES)
        return jsonify(payload)

    @app.route('/api/ppmp-indicative-copies/<int:copy_id>/export/<format_name>')
    @application.permission_required('ppmp.export')
    def export_indicative_copy(copy_id, format_name):
        copy = db.session.get(IndicativePPMPCopy, copy_id)
        user = application.current_session_user()
        if not copy:
            return jsonify({'error': 'Indicative copy not found.'}), 404
        if not can_access_copy(user, copy):
            return jsonify({'error': 'You cannot export another office\'s indicative copy.'}), 403
        document = copy_document_adapter(copy)
        if format_name == 'pdf':
            return application.export_selected_ppmp_request_pdf.__wrapped__(document=document, indicative=True)
        if format_name == 'excel':
            return application.export_selected_ppmp_request_excel.__wrapped__(document=document, indicative=True)
        return jsonify({'error': 'Choose PDF or Excel.'}), 400


def create_copy_response(application, user, order_id=None):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'Provide a fiscal year or an official PPMP.'}), 400
    order_id = order_id or data.get('source_order_id')
    if order_id is None:
        try:
            year = int(data.get('fiscal_year'))
        except (TypeError, ValueError, OverflowError):
            return jsonify({'error': 'Select a fiscal year from an approved official PPMP.'}), 400
        if isinstance(data.get('fiscal_year'), bool) or (isinstance(data.get('fiscal_year'), float) and data['fiscal_year'] != year):
            return jsonify({'error': 'Fiscal year must be a whole year.'}), 400
        official = OfficialPPMP.query.filter_by(office_id=user.college_id, fiscal_year=year).first()
        order_id = official.source_order_id if official else None
    order = db.session.get(PPMPOrder, order_id) if type(order_id) is int else None
    if not order:
        return jsonify({'error': 'No approved official PPMP exists for that office and fiscal year.'}), 409
    try:
        copy, created = create_indicative_copy(application, user, order)
        db.session.commit()
    except PermissionError as error:
        db.session.rollback()
        return jsonify({'error': str(error)}), 403
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        return jsonify({'error': str(error) if isinstance(error, ValueError) else 'An indicative copy already exists; refresh the list.'}), 409
    return jsonify(dict(copy.to_dict(), source_type='indicative',
                        open_url=f'/api/ppmp-indicative-copies/{copy.id}/report')), 201 if created else 200
