"""Import the FY 2026 APP transcribed from the four user-provided images.

This importer is intentionally narrow and idempotent.  It never creates PPMP
items, consolidation batches, approval actions, users, or offices.  A conflicting
existing APP causes a rollback instead of an overwrite.
"""

from argparse import ArgumentParser
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys


PPMP_ROOT = Path(__file__).resolve().parents[1]
if str(PPMP_ROOT) not in sys.path:
    sys.path.insert(0, str(PPMP_ROOT))

from app import app  # noqa: E402
from models import (  # noqa: E402
    APPItem, APPSection, AnnualProcurementPlan, WorkflowAuditLog, db,
)


REFERENCE_DIR = PPMP_ROOT / 'reference_data' / 'app_2026'
SOURCE_IMAGES = tuple(f'app_2026_page_{page}.jfif' for page in range(1, 5))
GAA_PDF = 'APP-2026-ISU-CAUAYAN-CAMPUS-GAA-FUND.pdf'
OFFICE = 'ISU Cauayan Campus'
FISCAL_YEAR = 2026
SOURCE_OF_FUND = 'GAA 2026 - Current Appropriation'
START = date(2026, 1, 1)
END = date(2026, 12, 1)

REPORTED_TOTALS = {
    'mooe': 61_459_200,
    'capital_outlay': 32_000_000,
    'epa_projects': 92_959_200,
    'cse': 500_000,
    'overall': 93_459_200,
}
EXPECTED_ROW_TOTAL = 93_459_200
EXPECTED_MOOE_ROW_TOTAL = 61_459_200


def item(project_title, estimated_budget, mode='Small Value Procurement',
         early=False, general_description='Goods'):
    return {
        'project_title': project_title,
        'implementing_unit': OFFICE,
        'general_description': general_description,
        'mode_of_procurement': mode,
        'early_procurement_activity': early,
        'bid_evaluation_criteria': 'LCRB',
        'procurement_start': START,
        'procurement_end': END,
        'source_of_fund': SOURCE_OF_FUND,
        'estimated_budget': Decimal(str(estimated_budget)).quantize(Decimal('0.00')),
        # Columns 11 and 12 are blank in all four source images.
        'procurement_strategy_tools': None,
        'remarks': None,
    }


SECTIONS = (
    ('General Requirements', (
        item('Supply and Delivery of Accountable Forms', 85_000),
        item('Supply and Delivery of Medical, Dental and Laboratory Supplies', 64_000),
        item('Supply and Delivery of Semi-Expendable Machinery and Equipment Expenses- Office Equipment', 431_000),
        item('Supply and Delivery of Semi-Expendable Machinery and Equipment Expenses- Information and Communications Technology Equipment', 50_000),
        item('Supply and Delivery of Semi-Expendable Furniture, Fixtures and Books Expenses- Furniture and Fixtures', 313_000),
        item('Supply and Delivery of Semi-Expendable Furniture, Fixtures and Books Expenses- Books', 110_000),
        item('Supply and Delivery of Other Supplies and Materials', 330_000),
        item('Procurement of Internet Subscription', 297_000),
        item('Procurement of Janitorial Services', 1_358_000, mode='Public Bidding', early=True),
        item('Procurement of Security Services', 1_620_000, mode='Public Bidding', early=True),
        item('Procurement for the Repair & Maintenance- Buildings and Other Structures - Buildings', 173_000),
        item('Procurement for the Repair & Maintenance- Buildings and Other Structures - School Buildings', 380_000),
        item('Procurement for the Repair & Maintenance- Machinery', 20_000),
        item('Procurement for the Repair & Maintenance- Motor Vehicles', 141_000),
        item('Procurement for Printing and Publication', 83_000),
        item('Procurement for Representation Expenses', 196_000),
        item('Membership Dues and Contributions to Organizations', 7_000),
        item('Supply and Delivery of Agricultural and Marine Supplies Expenses', 43_000),
        item('Supply and Delivery of Textbooks and Instructional Materials', 54_000),
        item('Procurement of Subscription Expenses- ICT Software Subscription', 41_000,
             mode='Negotiated Procurement'),
        item('Procurement of Other Subscriptions', 68_000),
        item('Subsidies-Others', 49_768_200, mode='Negotiated Procurement'),
        item('Taxes, Duties and Licenses', 25_000, mode='Negotiated Procurement'),
        item('Labor and Wages', 379_000, mode='Negotiated Procurement'),
    )),
    ('Miscellaneous Items (for Direct Acquisition only) Sec 32.2 of RA No. 12009', (
        item('Travel Expenses-Local', 426_000, mode='Direct Acquisition'),
        item('Travel Expenses-Foreign', 69_000, mode='Direct Acquisition'),
        item('Training Expenses', 609_000, mode='Direct Acquisition'),
        item('Procurement of Fuel, Oil and Lubricants', 427_000,
             mode='Direct Retail Purchase of Petroleum Fuel, Oil and Lubricant Products'),
        item('Water Expenses', 277_000, mode='Direct Acquisition'),
        item('Electricity Expenses', 1_910_000, mode='Direct Acquisition'),
        item('Telephone Expenses-mobile', 54_000, mode='Direct Acquisition'),
        item('Telephone Expenses-landline', 237_000, mode='Direct Acquisition'),
        item('Fidelity Bond Premiums', 29_000, mode='Direct Acquisition'),
        item('Insurance Expenses', 346_000, mode='Direct Acquisition'),
        item('Procurement of Other Professional Services', 480_000, mode='Direct Acquisition'),
        item('Procurement of Other General Services', 59_000, mode='Direct Acquisition'),
    )),
    ('Common Use Supplies and Equipment (CSE)', (
        item('Supply and Delivery of Common-use Office Supplies Expenses', 500_000,
             mode='Agency to Agency'),
    )),
    ('Capital Outlay', (
        item('Construction of School Buildings', 30_000_000, mode='Public Bidding',
             general_description='Infrastructure'),
        item('Procurement of Information and Communication Technology Equipment', 750_000,
             general_description='Infrastructure'),
        item('Procurement of Technical and Scientific Equipment', 1_250_000,
             general_description='Infrastructure'),
    )),
)


def transcription_summary():
    rows = [row for _, section_rows in SECTIONS for row in section_rows]
    section_totals = {
        section: int(sum(row['estimated_budget'] for row in section_rows))
        for section, section_rows in SECTIONS
    }
    row_total = int(sum(row['estimated_budget'] for row in rows))
    mooe_row_total = row_total - section_totals['Capital Outlay']
    return {
        'row_count': len(rows),
        'section_count': len(SECTIONS),
        'row_total': row_total,
        'mooe_row_total': mooe_row_total,
        'section_totals': section_totals,
        'reported_variance': REPORTED_TOTALS['overall'] - row_total,
    }


def validate_transcription(require_images=True):
    summary = transcription_summary()
    if require_images:
        missing = [
            name for name in (*SOURCE_IMAGES, GAA_PDF)
            if not (REFERENCE_DIR / name).is_file()
        ]
        if missing:
            raise RuntimeError('Missing reference image(s): ' + ', '.join(missing))
    if summary['row_count'] != 40 or summary['section_count'] != 4:
        raise RuntimeError('The APP transcription must contain exactly 40 rows in four sections.')
    if summary['row_total'] != EXPECTED_ROW_TOTAL:
        raise RuntimeError('The transcribed row total changed unexpectedly.')
    if summary['mooe_row_total'] != EXPECTED_MOOE_ROW_TOTAL:
        raise RuntimeError('The transcribed MOOE row total changed unexpectedly.')
    if summary['section_totals']['Capital Outlay'] != REPORTED_TOTALS['capital_outlay']:
        raise RuntimeError('The Capital Outlay rows no longer match the printed subtotal.')
    if summary['section_totals']['Common Use Supplies and Equipment (CSE)'] != REPORTED_TOTALS['cse']:
        raise RuntimeError('The CSE rows no longer match the printed subtotal.')
    if summary['reported_variance'] != 0:
        raise RuntimeError('The documented source-image variance changed unexpectedly.')
    return summary


def source_details(summary):
    return {
        'description': 'FY 2026 final GAA APP verified from the clear PDF and four user-provided images',
        'source_label': 'Final GAA PDF verified against 4 source images',
        'image_count': len(SOURCE_IMAGES),
        'image_files': list(SOURCE_IMAGES),
        'verification_file': GAA_PDF,
        'reported_totals': REPORTED_TOTALS,
        'transcribed_row_total': summary['row_total'],
        'transcribed_mooe_row_total': summary['mooe_row_total'],
        'reported_variance': summary['reported_variance'],
        'blank_source_columns': ['procurement_strategy_tools', 'remarks'],
        'workflow_note': 'Printed FINAL status preserved; no system approval history was fabricated.',
        'source_discrepancies': [
            'The PDF reports an EPA total of PHP 92,959,200.00, while the two rows marked Yes total PHP 2,978,000.00.'
        ],
    }


def existing_import_is_identical(plan, summary):
    return (
        plan.source_type == 'REFERENCE_DOCUMENTS'
        and plan.status == 'Finalized'
        and len(plan.sections) == summary['section_count']
        and len(plan.items) == summary['row_count']
        and int(sum(row.estimated_budget for row in plan.items)) == summary['row_total']
        and [row.project_title for row in plan.items]
        == [row['project_title'] for _, rows in SECTIONS for row in rows]
    )


def import_reference_app():
    summary = validate_transcription()
    existing = AnnualProcurementPlan.query.filter_by(
        office=OFFICE, fiscal_year=FISCAL_YEAR, plan_type='APP',
    ).one_or_none()
    if existing is not None:
        if existing_import_is_identical(existing, summary):
            return existing, False, summary
        current_rows = list(existing.items)
        expected_rows = [row for _, rows in SECTIONS for row in rows]
        legacy_titles = {
            'Supply and Delivery of Semi-Expendable Furniture, Fixtures and Books Expenses- Furniture and Fixtures':
                'Supply and Delivery of Semi-Expendable Furniture, Fixtures and Books Expense- Furniture and Fixtures',
            'Supply and Delivery of Semi-Expendable Furniture, Fixtures and Books Expenses- Books':
                'Supply and Delivery of Semi-Expendable Furniture, Fixtures and Books Expense- Books',
        }
        legacy_budgets = {
            'Procurement of Internet Subscription': Decimal('287000.00'),
            'Procurement for the Repair & Maintenance- Buildings and Other Structures - School Buildings': Decimal('360000.00'),
        }
        reconcilable = (
            existing.source_type in {'REFERENCE_IMAGES', 'REFERENCE_DOCUMENTS'}
            and existing.status == 'Finalized'
            and len(current_rows) == len(expected_rows) == 40
        )
        if reconcilable:
            for current, expected in zip(current_rows, expected_rows):
                allowed_title = {expected['project_title'], legacy_titles.get(expected['project_title'])}
                allowed_budget = {
                    expected['estimated_budget'], legacy_budgets.get(expected['project_title'])
                }
                if (current.project_title not in allowed_title
                        or current.estimated_budget not in allowed_budget):
                    reconcilable = False
                    break
        if not reconcilable:
            raise RuntimeError(
                'A conflicting FY 2026 ISU Cauayan Campus APP already exists; no data was changed.'
            )
        for current, expected in zip(current_rows, expected_rows):
            current.project_title = expected['project_title']
            current.estimated_budget = expected['estimated_budget']
        existing.source_type = 'REFERENCE_DOCUMENTS'
        existing.source_details = source_details(summary)
        existing.remarks = (
            'Verified against the final FY 2026 GAA APP PDF and four source images. '
            'All 40 rows total PHP 93,459,200.00. Columns 11 and 12 are blank in the source.'
        )
        db.session.add(WorkflowAuditLog(
            entity_type='app', entity_id=existing.id,
            action='CLEAR_SOURCE_RECONCILED', performed_by=None,
            details={
                'corrected_rows': {
                    'Procurement of Internet Subscription': {'from': 287000, 'to': 297000},
                    'School Buildings repair': {'from': 360000, 'to': 380000},
                },
                'verified_total': EXPECTED_ROW_TOTAL,
                'verification_file': GAA_PDF,
            },
        ))
        db.session.commit()
        return existing, True, summary

    plan = AnnualProcurementPlan(
        office=OFFICE,
        fiscal_year=FISCAL_YEAR,
        plan_type='APP',
        consolidation_batch_id=None,
        source_type='REFERENCE_DOCUMENTS',
        source_details=source_details(summary),
        status='Finalized',
        created_by=None,
        remarks=(
            'Verified against the final FY 2026 GAA APP PDF and four source images. '
            'All 40 rows total PHP 93,459,200.00. Columns 11 and 12 are blank in the source.'
        ),
    )
    db.session.add(plan)
    db.session.flush()

    for sort_order, (section_name, section_rows) in enumerate(SECTIONS, 1):
        section = APPSection(
            app_id=plan.id, name=section_name, sort_order=sort_order * 10, created_by=None,
        )
        db.session.add(section)
        db.session.flush()
        for values in section_rows:
            db.session.add(APPItem(
                app_id=plan.id,
                section_id=section.id,
                source_ppmp_item_id=None,
                created_by=None,
                **values,
            ))

    db.session.add(WorkflowAuditLog(
        entity_type='app',
        entity_id=plan.id,
        action='REFERENCE_IMAGES_IMPORTED',
        performed_by=None,
        details={
            'fiscal_year': FISCAL_YEAR,
            'office': OFFICE,
            'row_count': summary['row_count'],
            'row_total': summary['row_total'],
            'printed_total': REPORTED_TOTALS['overall'],
            'variance': summary['reported_variance'],
            'source_images': list(SOURCE_IMAGES),
        },
    ))
    db.session.commit()
    return plan, True, summary


def main():
    parser = ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check-only', action='store_true', help='Validate the transcription without database writes.')
    action.add_argument('--apply', action='store_true', help='Import the validated transcription into MariaDB.')
    args = parser.parse_args()

    if args.check_only:
        print(validate_transcription())
        return

    with app.app_context():
        try:
            plan, created, summary = import_reference_app()
            print({
                'app_id': plan.id,
                'created': created,
                'status': plan.status,
                'rows': summary['row_count'],
                'row_total': summary['row_total'],
                'printed_total': REPORTED_TOTALS['overall'],
                'variance': summary['reported_variance'],
            })
        except Exception:
            db.session.rollback()
            raise


if __name__ == '__main__':
    main()
