"""Consolidation snapshots and office allocations for the institutional APP.

This module never changes an approved PPMP. An APP owns its own allocations,
while each allocation retains an immutable copy of the source that was selected.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation

from models import (
    APPItem, APPItemContribution, APPSection, PPMPOrderItem, PPMPRecordItem, db,
)

APP_REVIEW_ROLES = ('BAC CHAIRMAN', 'BUDGET', 'EO', 'ADMIN')
APP_OPEN_STATUSES = ('Draft', 'Returned', 'Submitted', 'Under Review', 'For Admin Approval')
INSTITUTION_OFFICE = 'ALL OFFICES / COLLEGES'
CENT = Decimal('0.01')


def precise_number(value, label, *, positive=False, money=False):
    """Validate the database's exact two-decimal range before any write."""
    try:
        number = Decimal(str(value))
        maximum = Decimal('9999999999999999.99' if money else '9999999999.99')
        if (isinstance(value, bool) or not number.is_finite() or number < 0
                or (positive and number <= 0) or number > maximum
                or number != number.quantize(CENT)):
            raise ValueError
        return number.quantize(CENT)
    except (InvalidOperation, ValueError, TypeError):
        qualifier = 'positive' if positive else 'nonnegative'
        raise ValueError(f'{label} must be a finite {qualifier} number with at most two decimal places.')


def _iso(value):
    return value.isoformat() if value else None


def source_snapshot(ppmp_item):
    """Prefer the approved official order, then its historical planning source."""
    order_row = PPMPOrderItem.query.filter_by(ppmp_item_id=ppmp_item.id).order_by(PPMPOrderItem.id).first()
    record_row = None if order_row else PPMPRecordItem.query.filter_by(
        ppmp_item_id=ppmp_item.id,
    ).order_by(PPMPRecordItem.id).first()
    row = order_row or record_row
    order = order_row.order if order_row else None
    quantity = precise_number(ppmp_item.quantity, 'Source quantity', positive=True)
    budget = precise_number(
        ppmp_item.authorized_budget if ppmp_item.authorized_budget is not None
        else Decimal(ppmp_item.quantity or 0) * Decimal(ppmp_item.unit_cost or 0),
        'Source budget', money=True,
    )
    return {
        'source_ppmp_item_id': ppmp_item.id,
        'source_order_id': order.id if order else None,
        'source_order_reference': order.reference_number if order else None,
        'source_record_id': record_row.ppmp_record_id if record_row else None,
        'is_official': bool(order and order.workflow_official),
        'legacy_source': not bool(order and order.workflow_official),
        'is_cse': bool(order_row and order_row.master_item_id is not None),
        'office_id': ppmp_item.college_id,
        'office_code': ppmp_item.college.code if ppmp_item.college else '',
        'office_name': ppmp_item.college.name if ppmp_item.college else '',
        'fiscal_year': ppmp_item.fiscal_year,
        'item_description': ppmp_item.item_description,
        'specifications': order_row.description if order_row else ppmp_item.item_description,
        'procurement_type': ppmp_item.procurement_type,
        'unit': ppmp_item.unit,
        'quantity': str(quantity),
        'estimated_budget': str(budget),
        'fund_source': ppmp_item.fund_source,
        'mode_of_procurement': ppmp_item.mode_of_procurement,
        'procurement_start': _iso(row.procurement_start) if row else None,
        'procurement_end': _iso(row.procurement_end) if row else None,
        'delivery_period': _iso(row.delivery_period) if row else None,
        'schedule_as_needed': bool(row.schedule_as_needed) if row else False,
        'quarter': ppmp_item.quarter,
        'pre_procurement_conference': row.pre_procurement_conference if row else None,
        'supporting_documents': row.supporting_documents if row else None,
        'remarks': ppmp_item.remarks,
    }


def strict_merge_key(snapshot):
    """Unit price and office are deliberately excluded; allocations retain both."""
    def normalized(value):
        return ' '.join(str(value or '').split()).casefold()
    key = {
        field: normalized(snapshot.get(field)) for field in (
            'fiscal_year', 'item_description', 'specifications', 'procurement_type',
            'unit', 'fund_source', 'mode_of_procurement', 'procurement_start',
            'procurement_end', 'delivery_period', 'schedule_as_needed',
        )
    }
    # Historical PPMPs may have only a quarter; never merge across quarters.
    if not any(snapshot.get(field) for field in ('procurement_start', 'procurement_end', 'delivery_period')):
        key['quarter'] = normalized(snapshot.get('quarter'))
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode('utf-8')).hexdigest()


def row_allocation_totals(item):
    return (
        sum((Decimal(row.quantity) for row in item.contributions), Decimal('0.00')),
        sum((Decimal(row.estimated_budget) for row in item.contributions), Decimal('0.00')),
    )


def validate_row_allocations(item):
    if not item.contributions:
        return
    quantity, budget = row_allocation_totals(item)
    if quantity != Decimal(item.quantity or 0) or budget != Decimal(item.estimated_budget or 0):
        raise ValueError('APP row quantity and budget must equal the sum of its office contributions.')
    precise_number(quantity, 'Total quantity', positive=True)
    precise_number(budget, 'Total budget', money=True)


def prepare_contribution_update(item, data):
    entries = data.get('contributions')
    existing = {row.id: row for row in item.contributions}
    if not existing or not isinstance(entries, list) or not entries:
        raise ValueError('Provide every office contribution for this consolidated APP row.')
    if any(not isinstance(entry, dict) for entry in entries):
        raise ValueError('Every contribution must contain its id, quantity, and estimated budget.')
    ids = [entry.get('id') for entry in entries]
    if (any(type(value) is not int for value in ids)
            or len(ids) != len(set(ids)) or set(ids) != set(existing)):
        raise ValueError('Contribution IDs must match every contribution belonging to this APP row exactly once.')
    updates = []
    for entry in entries:
        updates.append((
            existing[entry['id']],
            precise_number(entry.get('quantity'), 'Office quantity', positive=True),
            precise_number(entry.get('estimated_budget', entry.get('budget')), 'Office budget', money=True),
        ))
    quantity = precise_number(sum((row[1] for row in updates), Decimal('0.00')), 'Total quantity', positive=True)
    budget = precise_number(sum((row[2] for row in updates), Decimal('0.00')), 'Total budget', money=True)
    if 'quantity' in data and precise_number(data['quantity'], 'Row quantity', positive=True) != quantity:
        raise ValueError('Row quantity must equal the sum of the office contributions.')
    supplied_budget = data.get('estimated_budget', data.get('budget'))
    if supplied_budget is not None and precise_number(supplied_budget, 'Row budget', money=True) != budget:
        raise ValueError('Row budget must equal the sum of the office contributions.')
    return updates, quantity, budget


def apply_contribution_update(item, prepared):
    updates, quantity, budget = prepared
    for contribution, office_quantity, office_budget in updates:
        contribution.quantity, contribution.estimated_budget = office_quantity, office_budget
    item.quantity, item.estimated_budget = quantity, budget


def materialize_batch_sources(plan, batch_sources, creator):
    """Append approved snapshots; merge only rows that still have matching source fields."""
    from datetime import date
    sections = {section.name: section for section in plan.sections}
    section = sections.get('Consolidated Approved PPMP Items')
    if section is None:
        section = APPSection(app=plan, name='Consolidated Approved PPMP Items', sort_order=10, created_by=creator.id)
        db.session.add(section)
        db.session.flush()
    rows_by_key = {item.merge_key: item for item in plan.items if item.merge_key}
    snapshots = []
    for source in batch_sources:
        ppmp = source.ppmp_item
        if ppmp.status != 'Approved' or ppmp.fiscal_year != plan.fiscal_year:
            raise ValueError('Every consolidation source must remain an approved PPMP item in the APP fiscal year.')
        snapshot = source_snapshot(ppmp)
        if plan.workflow_version == 2 and not snapshot['is_official']:
            raise ValueError('Only designated official approved PPMPs can supply new consolidated APPs.')
        if snapshot['is_official']:
            order = PPMPOrderItem.query.filter_by(ppmp_item_id=ppmp.id).first().order
            if order.status != 'Approved' or order.ppmp_document_number != 2:
                raise ValueError('Only an approved Final PPMP No. 2 can be consolidated into the APP.')
        key = strict_merge_key(snapshot)
        item = rows_by_key.get(key)
        if item is None:
            item = APPItem(
                app=plan, section=section, source_ppmp_item_id=ppmp.id,
                project_title=snapshot['item_description'],
                implementing_unit=snapshot['office_code'] or snapshot['office_name'],
                general_description=snapshot['procurement_type'],
                # The PPMP recommendation remains in the immutable snapshot and
                # merge key. BAC Chairman sets the APP's procurement decision.
                mode_of_procurement='',
                early_procurement_activity=None, bid_evaluation_criteria=None,
                procurement_start=date.fromisoformat(snapshot['procurement_start']) if snapshot['procurement_start'] else None,
                procurement_end=date.fromisoformat(snapshot['procurement_end']) if snapshot['procurement_end'] else None,
                source_of_fund=snapshot['fund_source'], quantity=Decimal('0.00'),
                unit_size=snapshot['unit'], merge_key=key, estimated_budget=Decimal('0.00'),
                remarks=snapshot['remarks'], created_by=creator.id,
            )
            db.session.add(item)
            db.session.flush()
            rows_by_key[key] = item
        quantity, budget = Decimal(snapshot['quantity']), Decimal(snapshot['estimated_budget'])
        contribution = APPItemContribution(
            app_item=item, source_ppmp_item_id=ppmp.id, office_id=ppmp.college_id,
            original_quantity=quantity, original_budget=budget, quantity=quantity,
            estimated_budget=budget, source_snapshot=snapshot,
        )
        db.session.add(contribution)
        item.quantity = precise_number(Decimal(item.quantity or 0) + quantity, 'Merged quantity', positive=True)
        item.estimated_budget = precise_number(Decimal(item.estimated_budget or 0) + budget, 'Merged budget', money=True)
        office_codes = sorted({row.office.code for row in item.contributions if row.office} | {snapshot['office_code']})
        office_label = ', '.join(filter(None, office_codes))
        item.implementing_unit = office_label if len(office_label) <= 200 else 'Multiple Offices / Colleges (see contributions)'
        snapshots.append(snapshot)
    db.session.flush()
    for item in plan.items:
        validate_row_allocations(item)
    return snapshots


def app_snapshot(plan):
    """Capture exact rows and original/revised allocations at an approval or change."""
    rows = []
    for item in plan.items:
        row = item.to_dict()
        row['quantity'], row['estimated_budget'] = str(item.quantity or 0), str(item.estimated_budget or 0)
        row['contributions'] = []
        for allocation in item.contributions:
            value = allocation.to_dict()
            for field in ('quantity', 'estimated_budget', 'original_quantity', 'original_budget'):
                value[field] = str(getattr(allocation, field))
            row['contributions'].append(value)
        rows.append(row)
    return {
        'app_id': plan.id, 'fiscal_year': plan.fiscal_year, 'revision': plan.revision,
        'status': plan.status, 'current_review_role': plan.current_review_role,
        'return_review_role': plan.return_review_role,
        'rows': rows, 'item_count': len(rows),
        'sections': [{'id': section.id, 'name': section.name} for section in plan.sections],
        'batch_ids': [link.batch_id for link in plan.batch_links],
        'totals': {'overall': str(sum((Decimal(row.estimated_budget or 0) for row in plan.items), Decimal('0.00')))},
    }


def export_project_title(item):
    if not item.contributions:
        return item.project_title
    return f'{item.project_title}\nQuantity: {Decimal(item.quantity or 0):g} {item.unit_size or ""}'.strip()


def app_timeline_label(item, field):
    value = getattr(item, field)
    if value:
        return APPItem.month_label(value)
    if (not item.procurement_start and not item.procurement_end and item.contributions
            and all(row.source_snapshot.get('schedule_as_needed') for row in item.contributions)):
        return 'As Needed'
    return None


def export_office_contributions(item):
    if not item.contributions:
        return item.implementing_unit
    return '\n'.join(
        f'{row.office.code if row.office else row.office_id}: {Decimal(row.quantity):g} {item.unit_size or ""}; PHP {Decimal(row.estimated_budget):,.2f}'
        for row in item.contributions
    )
