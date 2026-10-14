"""Validate and import the FY 2026 Supply Office PPMP image rows.

The importer is narrow, provenance-preserving, and idempotent. It adds only
clearly quantified procurement rows to the master PPMP Wishlist. It never
changes users, existing Wishlist items, PPMP records, orders, or approvals.
"""

from argparse import ArgumentParser
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
import sys


PPMP_ROOT = Path(__file__).resolve().parents[1]
if str(PPMP_ROOT) not in sys.path:
    sys.path.insert(0, str(PPMP_ROOT))

from app import app  # noqa: E402
from models import WishlistItem, WorkflowAuditLog, db  # noqa: E402


REFERENCE_DIR = PPMP_ROOT / 'reference_data' / 'ppmp_2026'
SOURCE_FILES = {
    'ppmp_2026_page_1.jfif': '8cda89561c82210e7e16962ca4d54cf4b9971f345e3ad2cf9e9579751c8f3270',
    'ppmp_2026_page_2.jfif': 'c8836a0e2dabe7f715ff0444b0fc64aaa63ec3688259ebda21bb3a35331bec01',
}
IMPORT_MARKER = 'PPMP_IMAGE_IMPORT_2026_SUPPLY_OFFICE'
OFFICE = 'SUPPLY OFFICE'
PRINTED_TOTAL = Decimal('249878.00')
UNQUANTIFIED_ROW_TOTAL = Decimal('23000.00')


def row(page, number, description, quantity, unit, total, start='Jan-26', end='Jan-26', delivery='Jan-26', documents='CSE to be procured at PS-DBM'):
    return {
        'page': page,
        'number': number,
        'description': description,
        'quantity': Decimal(str(quantity)),
        'unit': unit,
        'total': Decimal(str(total)).quantize(Decimal('0.00')),
        'start': start,
        'end': end,
        'delivery': delivery,
        'documents': documents,
    }


ROWS = (
    row(1, 1, 'Laptop Processor: 13th Generation Core i7-1355U (12 MB cache, 10 cores, 12 threads, up to 5.00 GHz Turbo); Windows 11 Pro; Intel Iris Xe Graphics; UHD Graphics; 16GB memory; 512GB, M.2, PCIe NVMe SSD; Intel Wi-Fi 6 AX201, 2x2, 802.11ax, Bluetooth wireless card; 3-cell, 54 Wh battery; 1-year warranty; 1.63 kg; 400 nits storage 512 GB; model RZ09-4537NAW3-R3U1', 1, 'unit', 49000, end='Feb-26', delivery='Feb-26', documents='Market scoping checklist; technical specifications'),
    row(1, 2, 'Document Scanner', 1, 'unit', 80000, documents='Market scoping checklist; technical specifications'),
    row(1, 3, 'UPS', 3, 'units', 12000, end='Feb-26', delivery='Feb-26', documents='Market scoping checklist; technical specifications'),
    row(1, 4, 'Executive Chair', 3, 'units', 30000, start='Feb-26', end='Mar-26', delivery='Mar-26', documents='Market scoping checklist; technical specifications'),
    row(1, 5, 'Keyboard and Mouse', 3, 'sets', 1500, start='Feb-26', end='Feb-26', delivery='Feb-26', documents='Market scoping checklist'),
    row(1, 6, 'Paper, Multipurpose A4', 50, 'reams', 10750),
    row(1, 7, 'Paper, Multipurpose Legal', 30, 'reams', 5900),
    row(1, 8, 'Folder Expanded Legal', 100, 'pcs', 2000, start='Feb-26', end='Feb-26', delivery='Feb-26'),
    row(1, 9, 'Folder with Tab Legal', 100, 'pcs', 700, start='Feb-26', end='Feb-26', delivery='Feb-26'),
    row(1, 10, 'Toner Cartridge HP Laserjet CF256A', 2, 'cart', 6000),
    row(1, 11, 'Epson 001 Ink', 4, 'sets', 4000, start='Feb-26', end='Feb-26', delivery='Feb-26'),
    row(1, 12, 'Epson 003 Ink', 6, 'sets', 4800, start='Feb-26', end='Feb-26', delivery='Feb-26'),
    row(1, 13, 'Sticker Paper (Glossy) A4', 5, 'reams', 2500),
    row(2, 1, 'Property Card', 300, 'pcs', 900, documents='CSE to be procured at PS-DBM; Property form Number 08-13-0001; 55gsm'),
    row(2, 2, 'Stock Card', 500, 'pcs', 1500, documents='CSE to be procured at PS-DBM; Government form number 08-13-0002; 55gsm'),
    row(2, 3, 'Tape Transparent 48mm', 6, 'rolls', 180),
    row(2, 4, 'Tape Transparent 24mm', 10, 'rolls', 200),
    row(2, 5, 'Ball pen .05 (Black)', 24, 'pcs', 168),
    row(2, 6, 'Sign Pen, Fine Tip, Black', 24, 'pcs', 720),
    row(2, 7, 'Stapler, standard', 3, 'pcs', 500, start='Mar-26', end='Mar-26', delivery='Mar-26'),
    row(2, 8, 'Fastener', 5, 'boxes', 480),
    row(2, 9, 'Staple Wire', 3, 'boxes', 90),
    row(2, 10, 'Paper Tray Heavy Duty, Metal, 4 Layers', 4, 'pcs', 1500),
    row(2, 11, 'Stamp pad felt', 2, 'pcs', 90),
    row(2, 12, 'Stamp pad Ink', 2, 'bottle', 100),
    row(2, 13, 'Record Book 500 pages', 10, 'books', 1000),
    row(2, 14, 'Correction Tape', 10, 'pcs', 200),
    row(2, 15, 'Plastic Storage Box', 10, 'pcs', 1500),
    row(2, 16, 'Window Blinds', 3, 'pcs', 7500, documents='Market scoping checklist'),
)


def validate_transcription():
    missing = [name for name in SOURCE_FILES if not (REFERENCE_DIR / name).is_file()]
    if missing:
        raise RuntimeError('Missing controlled PPMP source image(s): ' + ', '.join(missing))
    for name, expected_hash in SOURCE_FILES.items():
        actual_hash = sha256((REFERENCE_DIR / name).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError(f'Source image hash mismatch: {name}')
    if len(ROWS) != 29:
        raise RuntimeError('The quantified PPMP transcription must contain exactly 29 rows.')
    row_total = sum((item['total'] for item in ROWS), Decimal('0.00'))
    expected_quantified_total = PRINTED_TOTAL - UNQUANTIFIED_ROW_TOTAL - Decimal('1100.00')
    if row_total != expected_quantified_total:
        raise RuntimeError('The quantified PPMP row total changed unexpectedly.')
    return {
        'importable_rows': len(ROWS),
        'quantified_row_total': str(row_total),
        'printed_total': str(PRINTED_TOTAL),
        'unquantified_row_total': str(UNQUANTIFIED_ROW_TOTAL),
        'printed_vs_transcribed_variance': '1100.00',
    }


def source_remarks(values):
    return (
        f'{IMPORT_MARKER}; source=FY 2026 PPMP, End-User/Implementing Unit: SUPPLY OFFICE; '
        f'page={values["page"]}; source_row={values["number"]}; project_type=Goods; '
        f'mode=Small Value Procurement; pre_procurement_conference=No; '
        f'schedule={values["start"]} to {values["end"]}; delivery={values["delivery"]}; '
        f'source_of_funds=164; printed_total_budget=PHP {values["total"]}; '
        f'supporting_documents={values["documents"]}. Estimated unit cost is derived from '
        'the printed total divided by the source quantity.'
    )


def existing_import_is_identical(existing):
    expected = [(item['description'], item['quantity'], item['unit']) for item in ROWS]
    actual = [(item.item_description, Decimal(item.quantity), item.unit) for item in existing]
    return actual == expected


def import_rows():
    summary = validate_transcription()
    existing = WishlistItem.query.filter(WishlistItem.remarks.like(f'{IMPORT_MARKER}%')).order_by(WishlistItem.id).all()
    if existing:
        if existing_import_is_identical(existing):
            return existing, False, summary
        raise RuntimeError('A partial or conflicting PPMP image import exists; no data was changed.')

    created = []
    for values in ROWS:
        unit_cost = (values['total'] / values['quantity']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        item = WishlistItem(
            office=OFFICE,
            created_by=None,
            item_description=values['description'],
            category='Goods',
            unit=values['unit'],
            quantity=values['quantity'],
            estimated_cost=unit_cost,
            remarks=source_remarks(values),
            status='Available',
        )
        db.session.add(item)
        created.append(item)
    db.session.flush()
    db.session.add(WorkflowAuditLog(
        entity_type='wishlist_import', entity_id=created[0].id,
        action='PPMP_REFERENCE_IMAGES_IMPORTED', performed_by=None,
        details={
            **summary,
            'office': OFFICE,
            'source_files': list(SOURCE_FILES),
            'excluded_source_row': {
                'description': 'Repair and Maintenance / Emergency',
                'reason': 'The source quantity and unit are blank; they were not fabricated.',
                'printed_total_budget': '23000.00',
                'schedule': 'As needed',
            },
            'source_discrepancy': 'The sum of readable row budgets is PHP 1,100.00 below the printed total budget.',
        },
    ))
    db.session.commit()
    return created, True, summary


def main():
    parser = ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check-only', action='store_true')
    action.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.check_only:
        print(validate_transcription())
        return
    with app.app_context():
        try:
            rows, changed, summary = import_rows()
            print({'changed': changed, 'first_id': rows[0].id, **summary})
        except Exception:
            db.session.rollback()
            raise


if __name__ == '__main__':
    main()
