"""
PPMP System — SQLAlchemy ORM Models
Use with Flask-SQLAlchemy and SQLite or MariaDB.

The application defaults to SQLite; set DATABASE_URL to a MariaDB SQLAlchemy
URL when a MariaDB deployment or recovery is required.
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import Enum, Text, DECIMAL, JSON, UniqueConstraint, CheckConstraint

db = SQLAlchemy()

# ──────────────────────────────────────────────
# Connection helper
# ──────────────────────────────────────────────
def get_db_uri(host='localhost', port=3306, user='ppmp_user',
               password='ppmp_password', database='ppmp_db') -> str:
    """Build MariaDB URI for Flask-SQLAlchemy."""
    return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def init_app(app, db_uri: str = None):
    """Initialize SQLAlchemy with Flask app."""
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri or get_db_uri()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }
    db.init_app(app)
    with app.app_context():
        db.create_all()


# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────

class College(db.Model):
    __tablename__ = 'colleges'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code       = db.Column(db.String(20), unique=True, nullable=False)
    name       = db.Column(db.String(200), nullable=False)
    dean       = db.Column(db.String(120), nullable=True)
    address    = db.Column(db.String(300), nullable=True)
    is_active  = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ppmp_items = db.relationship('PPMPItem', back_populates='college', lazy='dynamic')
    users      = db.relationship('User', back_populates='college', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id, 'code': self.code, 'name': self.name,
            'dean': self.dean, 'address': self.address, 'is_active': self.is_active,
        }

    def __repr__(self):
        return f'<College {self.code}: {self.name}>'


class User(db.Model):
    __tablename__ = 'users'

    # Operational roles, not module accounts. A role can carry permissions for
    # both PPMP and APP (for example PROCUREMENT, EO and BUDGET).
    ROLES = (
        'ADMIN', 'ACCOUNTING', 'BIRD-C', 'BUDGET', 'CAS', 'CBM', 'CASHIER', 'CBAO', 'CCSICT', 'CCJE', 'CED', 'COA',
        'EXTENSION', 'FABLAB', 'FIC', 'GSO', 'GUIDANCE', 'EO', 'QA', 'AA',
        'EAPRIL', 'HRMO/AFS', 'IAT', 'INFIRMARY', 'INFRA', 'LIBRARY', 'MIS',
        'NSTP/ROTC', 'OSAS', "PLANNING AND DEV'T WITH GAD", 'PROCUREMENT',
        'PS', 'RECORDS', 'REGISTRAR', 'RESEARCH', 'SOCIO', 'SPORTS', 'SSC',
        'SUPPLY', 'SWINE PROJECT', 'TKC', 'BAC CHAIRMAN',
    )

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    college_id    = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='SET NULL'), nullable=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    full_name     = db.Column(db.String(150), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # A VARCHAR role is intentionally used so future role changes do not require
    # destructive MariaDB ENUM rewrites.
    role          = db.Column(db.String(64), nullable=True, unique=True)
    released_role = db.Column(db.String(64), nullable=True)
    office        = db.Column(db.String(120), nullable=True)
    account_status = db.Column(db.String(16), default='PENDING', nullable=False)
    is_active     = db.Column(db.Boolean, default=False, nullable=False)
    auth_version  = db.Column(db.Integer, default=0, nullable=False)
    last_login    = db.Column(db.DateTime, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    college = db.relationship('College', back_populates='users')

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username, 'full_name': self.full_name,
            'email': self.email, 'role': self.role, 'released_role': self.released_role,
            'office': self.office, 'college_id': self.college_id,
            'is_active': self.is_active, 'account_status': self.account_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    __table_args__ = (
        CheckConstraint("account_status IN ('PENDING','ACTIVE','SUSPENDED','ARCHIVED','REJECTED')", name='ck_user_account_status'),
    )


class UserActivityLog(db.Model):
    __tablename__ = 'user_activity_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    time_in = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    time_out = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User')

    @staticmethod
    def _philippine_time(value):
        return value + timedelta(hours=8) if value else None

    def to_dict(self):
        time_in = self._philippine_time(self.time_in)
        time_out = self._philippine_time(self.time_out)
        return {
            'date': time_in.strftime('%Y-%m-%d'),
            'time_in': time_in.strftime('%I:%M:%S %p'),
            'time_out': time_out.strftime('%I:%M:%S %p') if time_out else '',
        }


class PasswordResetRequest(db.Model):
    """Administrator-assisted reset request; SMTP delivery can be added later."""
    __tablename__ = 'password_reset_requests'

    STATUSES = ('PENDING', 'CODE_ISSUED', 'USED', 'EXPIRED')

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token_hash   = db.Column(db.String(64), nullable=True)
    status       = db.Column(db.String(20), default='PENDING', nullable=False)
    requested_ip = db.Column(db.String(45), nullable=True)
    attempt_count = db.Column(db.Integer, default=0, nullable=False)
    expires_at   = db.Column(db.DateTime, nullable=True)
    approved_by  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at  = db.Column(db.DateTime, nullable=True)
    used_at      = db.Column(db.DateTime, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])
    approver = db.relationship('User', foreign_keys=[approved_by])

    def to_admin_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'full_name': self.user.full_name if self.user else 'Removed account',
            'username': self.user.username if self.user else '',
            'email': self.user.email if self.user else '',
            'office': self.user.office if self.user else None,
            'status': self.status,
            'attempt_count': self.attempt_count,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    __table_args__ = (
        db.Index('ix_password_reset_user_status', 'user_id', 'status'),
    )


class PPMPItem(db.Model):
    __tablename__ = 'ppmp_items'

    FUND_SOURCES = ('GAA', 'STF', 'IGP', 'LGSF', 'Trust Fund', '164', 'SB 164')
    MODES = (
        'Public Bidding',
        'Shopping (Sec. 52.1a)',
        'Shopping (Sec. 52.1b)',
        'Negotiated Procurement',
        'Direct Contracting',
        'Repeat Order',
        'Small Value Procurement',
    )
    TYPES    = ('Goods', 'Services', 'Infrastructure', 'Consulting Services')
    QUARTERS = ('Q1 (Jan-Mar)', 'Q2 (Apr-Jun)', 'Q3 (Jul-Sep)', 'Q4 (Oct-Dec)')
    STATUSES = ('Draft', 'Submitted', 'EO Review', 'Procurement Review', 'Returned', 'Approved', 'Rejected')

    id                  = db.Column(db.Integer, primary_key=True, autoincrement=True)
    college_id          = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    fiscal_year         = db.Column(db.SmallInteger, nullable=False, default=lambda: datetime.utcnow().year)
    item_code           = db.Column(db.String(50), nullable=True)
    item_description    = db.Column(Text, nullable=False)
    unit                = db.Column(db.String(60), nullable=False)
    quantity            = db.Column(DECIMAL(12, 2), nullable=False, default=0)
    unit_cost           = db.Column(DECIMAL(15, 2), nullable=False, default=0)
    authorized_budget   = db.Column(DECIMAL(18, 2), nullable=True)
    fund_source         = db.Column(db.String(80), nullable=False)
    mode_of_procurement = db.Column(db.String(255), nullable=False)
    procurement_type    = db.Column(db.String(80), nullable=False, default='Goods')
    quarter             = db.Column(Enum(*QUARTERS,            name='quarter_enum'),      nullable=True)
    remarks             = db.Column(Text, nullable=True)
    status              = db.Column(db.String(32), nullable=False, default='Draft')
    created_by          = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_by         = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at         = db.Column(db.DateTime, nullable=True)
    cancelled_by        = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    cancelled_at        = db.Column(db.DateTime, nullable=True)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    college      = db.relationship('College', back_populates='ppmp_items')
    creator      = db.relationship('User', foreign_keys=[created_by])
    approver     = db.relationship('User', foreign_keys=[approved_by])

    @property
    def total_cost(self):
        """Python-side computed total (MariaDB uses GENERATED ALWAYS AS)."""
        if self.authorized_budget is not None:
            return float(self.authorized_budget)
        return float(self.quantity or 0) * float(self.unit_cost or 0)

    def to_dict(self):
        college = self.college
        return {
            'id':                   self.id,
            'college_id':           self.college_id,
            'college_code':         college.code if college else '',
            'college_name':         college.name if college else '',
            'fiscal_year':          self.fiscal_year,
            'item_code':            self.item_code,
            'item_description':     self.item_description,
            'unit':                 self.unit,
            'quantity':             float(self.quantity or 0),
            'unit_cost':            float(self.unit_cost or 0),
            'authorized_budget':    float(self.authorized_budget) if self.authorized_budget is not None else None,
            'total_cost':           self.total_cost,
            'fund_source':          self.fund_source,
            'mode_of_procurement':  self.mode_of_procurement,
            'procurement_type':     self.procurement_type,
            'quarter':              self.quarter,
            'remarks':              self.remarks,
            'status':               self.status,
            'created_by':           self.created_by,
            'approved_at':          self.approved_at.isoformat() if self.approved_at else None,
            'created_at':           self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<PPMPItem {self.id}: {self.item_description[:40]}>'


class PPMPAuditLog(db.Model):
    __tablename__ = 'ppmp_audit_log'

    ACTIONS = ('CREATE', 'UPDATE', 'STATUS_CHANGE', 'DELETE', 'EXPORT')

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ppmp_item_id  = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='CASCADE'), nullable=False)
    action        = db.Column(Enum(*ACTIONS, name='audit_action_enum'), nullable=False)
    old_values    = db.Column(JSON, nullable=True)
    new_values    = db.Column(JSON, nullable=True)
    performed_by  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_address    = db.Column(db.String(45), nullable=True)
    notes         = db.Column(Text, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    ppmp_item = db.relationship('PPMPItem')
    performer = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id, 'ppmp_item_id': self.ppmp_item_id,
            'action': self.action, 'old_values': self.old_values,
            'new_values': self.new_values, 'created_at': self.created_at.isoformat(),
        }


class PPMPConsolidationLog(db.Model):
    __tablename__ = 'ppmp_consolidation_log'

    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fiscal_year    = db.Column(db.SmallInteger, nullable=False)
    generated_by   = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    college_ids    = db.Column(JSON, nullable=True)
    total_amount   = db.Column(DECIMAL(18, 2), nullable=False, default=0)
    item_count     = db.Column(db.Integer, nullable=False, default=0)
    export_format  = db.Column(Enum('Excel', 'PDF', 'Both', name='export_fmt'), default='Excel')
    notes          = db.Column(Text, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    generator = db.relationship('User')


class PPMPNotification(db.Model):
    __tablename__ = 'ppmp_notifications'

    TYPES = ('info', 'success', 'warning', 'error')

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    recipient_id  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    ppmp_item_id  = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='SET NULL'), nullable=True)
    type          = db.Column(Enum(*TYPES, name='notif_type_enum'), default='info', nullable=False)
    title         = db.Column(db.String(200), nullable=False)
    message       = db.Column(Text, nullable=False)
    is_read       = db.Column(db.Boolean, default=False, nullable=False)
    read_at       = db.Column(db.DateTime, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    recipient = db.relationship('User')
    ppmp_item = db.relationship('PPMPItem')

    def to_dict(self):
        return {
            'id': self.id, 'type': self.type, 'title': self.title,
            'message': self.message, 'is_read': self.is_read,
            'created_at': self.created_at.isoformat(),
        }


class PPMPSubmissionRequest(db.Model):
    """EO request to a college to prepare one PPMP record for a fiscal year."""
    __tablename__ = 'ppmp_submission_requests'

    STATUSES = ('Requested', 'In Progress', 'Draft', 'Submitted', 'Returned', 'Approved', 'Closed')

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    college_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Requested')
    notes = db.Column(Text, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)

    college = db.relationship('College')
    requester = db.relationship('User')

    __table_args__ = (
        UniqueConstraint('college_id', 'fiscal_year', name='uq_ppmp_request_office_year'),
    )

    def to_dict(self):
        return {'id': self.id, 'college_id': self.college_id, 'college_code': self.college.code if self.college else '',
                'college_name': self.college.name if self.college else '', 'fiscal_year': self.fiscal_year,
                'status': self.status, 'notes': self.notes, 'due_date': self.due_date.isoformat() if self.due_date else None,
                'requested_by': self.requested_by,
                'requester_name': self.requester.full_name if self.requester else '',
                'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class PPMPRecord(db.Model):
    """Office-level planning document retained for historical records."""
    __tablename__ = 'ppmp_records'

    STATUSES = (
        'Draft', 'Submitted', 'Under Review', 'Pending Admin Approval',
        'Returned', 'Rejected', 'Approved', 'Consolidated',
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    reference_number = db.Column(db.String(40), unique=True, nullable=False)
    submission_request_id = db.Column(
        db.Integer, db.ForeignKey('ppmp_submission_requests.id', ondelete='SET NULL'),
        unique=True, nullable=True,
    )
    office_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    source_order_id = db.Column(
        db.Integer, db.ForeignKey('ppmp_orders.id', ondelete='RESTRICT'), nullable=True, unique=True,
    )
    ppmp_document_number = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    status = db.Column(db.String(32), nullable=False, default='Draft')
    prepared_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    decision_note = db.Column(Text, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    office = db.relationship('College')
    source_order = db.relationship('PPMPOrder', foreign_keys=[source_order_id])
    submission_request = db.relationship('PPMPSubmissionRequest')
    preparer = db.relationship('User', foreign_keys=[prepared_by])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    approver = db.relationship('User', foreign_keys=[approved_by])
    items = db.relationship('PPMPRecordItem', back_populates='record', cascade='all, delete-orphan', lazy='select')

    __table_args__ = (
        UniqueConstraint('office_id', 'fiscal_year', name='uq_ppmp_record_office_year'),
    )

    @property
    def included_items(self):
        return [item for item in self.items if item.item_status != 'Removed']

    @property
    def total_budget(self):
        return sum(float(item.estimated_budget or 0) for item in self.included_items)

    def to_dict(self, include_items=True):
        result = {
            'id': self.id,
            'reference_number': self.reference_number,
            'submission_request_id': self.submission_request_id,
            'office_id': self.office_id,
            'office_code': self.office.code if self.office else '',
            'office_name': self.office.name if self.office else '',
            'fiscal_year': self.fiscal_year,
            'source_order_id': self.source_order_id,
            'ppmp_document_number': self.ppmp_document_number,
            'is_indicative_copy': self.source_order_id is not None,
            'status': self.status,
            'prepared_by': self.prepared_by,
            'prepared_by_name': self.preparer.full_name if self.preparer else '',
            'decision_note': self.decision_note,
            'item_count': len(self.included_items),
            'total_budget': self.total_budget,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_items:
            result['items'] = [item.to_dict() for item in self.items]
        return result


class PPMPRecordItem(db.Model):
    """One row of the required 12-column PPMP Wishlist table."""
    __tablename__ = 'ppmp_record_items'

    PROJECT_TYPES = ('Goods', 'Infrastructure', 'Consulting Services')
    ITEM_STATUSES = ('Draft', 'Included', 'Removed')
    FUND_SOURCES = ('GAA', 'STF', 'IGP', 'LGSF', 'Trust Fund', '164', 'SB 164')

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ppmp_record_id = db.Column(db.Integer, db.ForeignKey('ppmp_records.id', ondelete='CASCADE'), nullable=False)
    general_description = db.Column(Text, nullable=False)
    project_type = db.Column(db.String(40), nullable=False)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    unit_size = db.Column(db.String(80), nullable=False)
    procurement_method = db.Column(db.String(255), nullable=False)
    pre_procurement_conference = db.Column(db.Boolean, nullable=True)
    procurement_start = db.Column(db.Date, nullable=True)
    procurement_end = db.Column(db.Date, nullable=True)
    delivery_period = db.Column(db.Date, nullable=True)
    schedule_as_needed = db.Column(db.Boolean, nullable=True, default=False)
    source_of_funds = db.Column(db.String(80), nullable=False)
    estimated_budget = db.Column(DECIMAL(18, 2), nullable=False)
    supporting_documents = db.Column(Text, nullable=True)
    remarks = db.Column(Text, nullable=True)
    item_status = db.Column(db.String(16), nullable=False, default='Included')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ppmp_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='SET NULL'), unique=True, nullable=True)
    legacy_ppmp_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='SET NULL'), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    record = db.relationship('PPMPRecord', back_populates='items')
    creator = db.relationship('User')
    materialized_item = db.relationship('PPMPItem', foreign_keys=[ppmp_item_id])
    legacy_item = db.relationship('PPMPItem', foreign_keys=[legacy_ppmp_item_id])

    __table_args__ = (
        CheckConstraint('quantity > 0', name='ck_ppmp_record_item_quantity'),
        CheckConstraint('estimated_budget >= 0', name='ck_ppmp_record_item_budget'),
        CheckConstraint(
            "item_status IN ('Draft','Included','Removed')",
            name='ck_ppmp_record_item_status',
        ),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'ppmp_record_id': self.ppmp_record_id,
            'general_description': self.general_description,
            'project_type': self.project_type,
            'quantity': float(self.quantity or 0),
            'unit_size': self.unit_size,
            'quantity_size': f'{float(self.quantity or 0):g} {self.unit_size}',
            'procurement_method': self.procurement_method,
            'pre_procurement_conference': self.pre_procurement_conference,
            'procurement_start': self.procurement_start.isoformat() if self.procurement_start else None,
            'procurement_end': self.procurement_end.isoformat() if self.procurement_end else None,
            'delivery_period': self.delivery_period.isoformat() if self.delivery_period else None,
            'schedule_as_needed': self.schedule_as_needed,
            'source_of_funds': self.source_of_funds,
            'estimated_budget': float(self.estimated_budget or 0),
            'supporting_documents': self.supporting_documents,
            'remarks': self.remarks,
            'item_status': self.item_status,
            'created_by': self.created_by,
            'ppmp_item_id': self.ppmp_item_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WishlistItem(db.Model):
    __tablename__ = 'wishlist_items'

    STATUSES = ('Available', 'Requested', 'Pending Admin Approval', 'Approved', 'Rejected', 'Returned', 'Processing', 'Completed')

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    office = db.Column(db.String(120), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    item_description = db.Column(Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    unit = db.Column(db.String(60), nullable=False)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    estimated_cost = db.Column(DECIMAL(15, 2), nullable=False)
    remarks = db.Column(Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default='Available')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])

    @property
    def total_cost(self):
        return float(self.quantity or 0) * float(self.estimated_cost or 0)

    def to_dict(self):
        return {'id': self.id, 'office': self.office, 'item_description': self.item_description, 'category': self.category,
                'unit': self.unit, 'quantity': float(self.quantity or 0), 'estimated_cost': float(self.estimated_cost or 0),
                'total_cost': self.total_cost, 'remarks': self.remarks, 'status': self.status,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class DepartmentPPMPSubmission(db.Model):
    """Historical department submission retained after workflow removal."""
    __tablename__ = 'department_ppmp_submissions'

    STATUSES = ('Submitted', 'No PPMP')

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    department_code = db.Column(db.String(16), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    notes = db.Column(Text, nullable=True)
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submitter = db.relationship('User', foreign_keys=[submitted_by])
    items = db.relationship(
        'DepartmentPPMPSubmissionItem', back_populates='submission',
        cascade='all, delete-orphan', lazy='select', order_by='DepartmentPPMPSubmissionItem.id',
    )
    review_copy = db.relationship(
        'DepartmentPPMPReviewCopy', back_populates='submission', uselist=False,
        cascade='all, delete-orphan', lazy='select',
    )

    __table_args__ = (
        UniqueConstraint('department_code', 'fiscal_year', name='uq_department_ppmp_year'),
        CheckConstraint("status IN ('Submitted','No PPMP')", name='ck_department_ppmp_submission_status'),
    )



class DepartmentPPMPSubmissionItem(db.Model):
    """Historical item snapshot; no active Department Wishlist API uses it."""
    __tablename__ = 'department_ppmp_submission_items'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    submission_id = db.Column(
        db.Integer, db.ForeignKey('department_ppmp_submissions.id', ondelete='CASCADE'), nullable=False,
    )
    master_item_id = db.Column(
        db.Integer, db.ForeignKey('wishlist_items.id', ondelete='SET NULL'), nullable=True,
    )
    item_name = db.Column(Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    unit = db.Column(db.String(60), nullable=False)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    estimated_unit_cost = db.Column(DECIMAL(15, 2), nullable=False)
    remarks = db.Column(Text, nullable=True)

    submission = db.relationship('DepartmentPPMPSubmission', back_populates='items')

    __table_args__ = (
        UniqueConstraint('submission_id', 'master_item_id', name='uq_department_submission_master_item'),
        CheckConstraint('quantity > 0', name='ck_department_submission_quantity'),
        CheckConstraint('estimated_unit_cost >= 0', name='ck_department_submission_unit_cost'),
    )



class DepartmentPPMPReviewCopy(db.Model):
    """Historical AA review copy retained without an active review workflow."""
    __tablename__ = 'department_ppmp_review_copies'

    STATUSES = ('Draft', 'Reviewed')

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    submission_id = db.Column(
        db.Integer, db.ForeignKey('department_ppmp_submissions.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )
    status = db.Column(db.String(16), nullable=False, default='Draft')
    notes = db.Column(Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    submission = db.relationship('DepartmentPPMPSubmission', back_populates='review_copy')
    creator = db.relationship('User', foreign_keys=[created_by])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    items = db.relationship(
        'DepartmentPPMPReviewItem', back_populates='review_copy',
        cascade='all, delete-orphan', lazy='select', order_by='DepartmentPPMPReviewItem.id',
    )

    __table_args__ = (
        CheckConstraint("status IN ('Draft','Reviewed')", name='ck_department_ppmp_review_status'),
    )



class DepartmentPPMPReviewItem(db.Model):
    """Historical AA copy item retained for data preservation."""
    __tablename__ = 'department_ppmp_review_items'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    review_copy_id = db.Column(
        db.Integer, db.ForeignKey('department_ppmp_review_copies.id', ondelete='CASCADE'), nullable=False,
    )
    master_item_id = db.Column(
        db.Integer, db.ForeignKey('wishlist_items.id', ondelete='SET NULL'), nullable=True,
    )
    item_name = db.Column(Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    unit = db.Column(db.String(60), nullable=False)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    estimated_unit_cost = db.Column(DECIMAL(15, 2), nullable=False)
    remarks = db.Column(Text, nullable=True)
    is_custom_item = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    review_copy = db.relationship('DepartmentPPMPReviewCopy', back_populates='items')

    __table_args__ = (
        CheckConstraint('quantity > 0', name='ck_department_review_quantity'),
        CheckConstraint('estimated_unit_cost >= 0', name='ck_department_review_unit_cost'),
    )




class WishlistRequest(db.Model):
    __tablename__ = 'wishlist_requests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    wishlist_item_id = db.Column(db.Integer, db.ForeignKey('wishlist_items.id', ondelete='RESTRICT'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    remarks = db.Column(Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default='Pending Admin Approval')
    admin_note = db.Column(Text, nullable=True)
    decided_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship('WishlistItem')
    requester = db.relationship('User', foreign_keys=[requested_by])
    decider = db.relationship('User', foreign_keys=[decided_by])

    def to_dict(self):
        return {'id': self.id, 'wishlist_item_id': self.wishlist_item_id, 'item': self.item.to_dict() if self.item else None,
                'quantity': float(self.quantity or 0), 'remarks': self.remarks, 'status': self.status,
                'admin_note': self.admin_note, 'created_at': self.created_at.isoformat() if self.created_at else None}


class PPMPOrder(db.Model):
    """Official PPMP submission; pre-workflow orders remain historical records."""
    __tablename__ = 'ppmp_orders'

    STATUSES = (
        'Draft', 'Requested', 'Pending Admin Approval',
        'Submitted', 'EO Review', 'Procurement Review',
        'Returned', 'Approved', 'Rejected', 'Processing', 'Completed',
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    reference_number = db.Column(db.String(40), unique=True, nullable=False)
    office_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=True)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    fiscal_year = db.Column(db.SmallInteger, nullable=False, default=lambda: datetime.utcnow().year)
    ppmp_document_number = db.Column(db.Integer, nullable=False, default=1)
    workflow_official = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    return_stage = db.Column(db.String(32), nullable=True)
    fund_source = db.Column(db.String(80), nullable=True)
    mode_of_procurement = db.Column(db.String(120), nullable=True)
    procurement_type = db.Column(db.String(80), nullable=True)
    quarter = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(32), nullable=False, default='Pending Admin Approval')
    remarks = db.Column(Text, nullable=True)
    admin_note = db.Column(Text, nullable=True)
    decided_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    legacy_wishlist_request_id = db.Column(
        db.Integer, db.ForeignKey('wishlist_requests.id', ondelete='RESTRICT'), unique=True, nullable=True)

    office = db.relationship('College')
    requester = db.relationship('User', foreign_keys=[requested_by])
    decider = db.relationship('User', foreign_keys=[decided_by])
    legacy_wishlist_request = db.relationship('WishlistRequest')
    items = db.relationship('PPMPOrderItem', back_populates='order', cascade='all, delete-orphan', lazy='select')

    @property
    def total_amount(self):
        return sum(item.total_cost for item in self.items)

    @property
    def approval_stage(self):
        if self.workflow_official:
            return {
                'Draft': 'Office Preparation',
                'Submitted': 'Procurement Review',
                'Procurement Review': 'Procurement Review',
                'Pending Admin Approval': 'Administrator Approval',
                'Returned': 'Creator Revision',
                'Approved': 'Final Approved PPMP',
                'Rejected': 'Closed',
            }.get(self.status, self.status)
        return {
            'Requested': 'Pending Administrator Review',
            'Pending Admin Approval': 'Administrator Review',
            'Submitted': 'APP / Procurement Consolidation',
            'EO Review': 'Procurement Review',
            'Procurement Review': 'Administrator Review',
            'Returned': 'Requester Revision',
            'Approved': 'Approved for Processing',
            'Processing': 'Processing',
            'Completed': 'Completed',
            'Rejected': 'Closed',
        }.get(self.status, self.status)

    def to_dict(self, include_items=True):
        result = {
            'id': self.id,
            'reference_number': self.reference_number,
            'office_id': self.office_id,
            'office_code': self.office.code if self.office else '',
            'office_name': self.office.name if self.office else '',
            'requested_by': self.requested_by,
            'requester_name': self.requester.full_name if self.requester else '',
            'fiscal_year': self.fiscal_year,
            'ppmp_document_number': self.ppmp_document_number,
            'workflow_official': bool(self.workflow_official),
            'return_stage': self.return_stage,
            'fund_source': self.fund_source,
            'mode_of_procurement': self.mode_of_procurement,
            'procurement_type': self.procurement_type,
            'quarter': self.quarter,
            'status': self.status,
            'current_stage': self.approval_stage,
            'remarks': self.remarks,
            'admin_note': self.admin_note,
            'item_count': len(self.items),
            'total_quantity': sum(float(item.quantity or 0) for item in self.items),
            'total_amount': self.total_amount,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_items:
            result['items'] = [item.to_dict() for item in self.items]
        return result


class OfficialPPMP(db.Model):
    """Reserve one official office/year without altering historical orders."""
    __tablename__ = 'official_ppmps'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    office_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    source_order_id = db.Column(
        db.Integer, db.ForeignKey('ppmp_orders.id', ondelete='RESTRICT'), nullable=False, unique=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    office = db.relationship('College')
    source_order = db.relationship('PPMPOrder', foreign_keys=[source_order_id])

    __table_args__ = (
        UniqueConstraint('office_id', 'fiscal_year', name='uq_official_ppmp_office_year'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'office_id': self.office_id, 'fiscal_year': self.fiscal_year,
            'source_order_id': self.source_order_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class IndicativePPMPCopy(db.Model):
    """An editable report snapshot that never changes its approved source PPMP."""
    __tablename__ = 'indicative_ppmp_copies'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    reference_number = db.Column(db.String(40), nullable=False, unique=True)
    source_order_id = db.Column(
        db.Integer, db.ForeignKey('ppmp_orders.id', ondelete='RESTRICT'), nullable=False, unique=True,
    )
    office_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    prepared_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ppmp_document_number = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    items = db.Column(JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_order = db.relationship('PPMPOrder', foreign_keys=[source_order_id])
    office = db.relationship('College')
    preparer = db.relationship('User', foreign_keys=[prepared_by])

    __table_args__ = (
        UniqueConstraint('office_id', 'fiscal_year', name='uq_indicative_copy_office_year'),
        CheckConstraint('ppmp_document_number > 0', name='ck_indicative_copy_number'),
    )

    @property
    def total_budget(self):
        return float(sum(
            (Decimal(str(item.get('estimated_budget') or 0)) for item in (self.items or [])),
            Decimal('0.00'),
        ))

    def to_dict(self, include_items=True):
        result = {
            'id': self.id, 'reference_number': self.reference_number,
            'source_order_id': self.source_order_id,
            'source_reference_number': self.source_order.reference_number if self.source_order else '',
            'office_id': self.office_id,
            'office_code': self.office.code if self.office else '',
            'office_name': self.office.name if self.office else '',
            'fiscal_year': self.fiscal_year, 'prepared_by': self.prepared_by,
            'prepared_by_name': self.preparer.full_name if self.preparer else '',
            'ppmp_document_number': self.ppmp_document_number,
            'status': 'Indicative', 'is_indicative_copy': True,
            'item_count': len(self.items or []), 'total_budget': self.total_budget,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_items:
            result['items'] = self.items or []
        return result


class PPMPOrderItem(db.Model):
    """A request snapshot referencing a master item or holding custom item data."""
    __tablename__ = 'ppmp_order_items'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer, db.ForeignKey('ppmp_orders.id', ondelete='CASCADE'), nullable=False)
    master_item_id = db.Column(db.Integer, db.ForeignKey('wishlist_items.id', ondelete='RESTRICT'), nullable=True)
    wishlist_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_record_items.id', ondelete='RESTRICT'), nullable=True)
    legacy_wishlist_item_id = db.Column(db.Integer, db.ForeignKey('wishlist_items.id', ondelete='RESTRICT'), nullable=True)
    ppmp_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='SET NULL'), unique=True, nullable=True)
    item_name = db.Column(db.String(300), nullable=False)
    description = db.Column(Text, nullable=True)
    category = db.Column(db.String(80), nullable=True)
    project_type = db.Column(db.String(40), nullable=True)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    unit = db.Column(db.String(60), nullable=False)
    procurement_method = db.Column(db.String(255), nullable=True)
    pre_procurement_conference = db.Column(db.Boolean, nullable=True)
    procurement_start = db.Column(db.Date, nullable=True)
    procurement_end = db.Column(db.Date, nullable=True)
    delivery_period = db.Column(db.Date, nullable=True)
    schedule_as_needed = db.Column(db.Boolean, nullable=True, default=False)
    source_of_funds = db.Column(db.String(80), nullable=True)
    estimated_unit_cost = db.Column(DECIMAL(15, 2), nullable=True)
    estimated_budget = db.Column(DECIMAL(18, 2), nullable=False)
    supporting_documents = db.Column(Text, nullable=True)
    remarks = db.Column(Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    is_custom_item = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    order = db.relationship('PPMPOrder', back_populates='items')
    master_item = db.relationship('WishlistItem', foreign_keys=[master_item_id])
    wishlist_item = db.relationship('PPMPRecordItem')
    legacy_wishlist_item = db.relationship('WishlistItem', foreign_keys=[legacy_wishlist_item_id])
    ppmp_item = db.relationship('PPMPItem')
    creator = db.relationship('User')

    __table_args__ = (
        CheckConstraint(
            '(is_custom_item IS TRUE AND master_item_id IS NULL AND wishlist_item_id IS NULL) OR '
            '(is_custom_item IS FALSE AND '
            '((master_item_id IS NOT NULL AND wishlist_item_id IS NULL AND legacy_wishlist_item_id IS NULL) OR '
            '(master_item_id IS NULL AND wishlist_item_id IS NOT NULL AND legacy_wishlist_item_id IS NULL) OR '
            '(master_item_id IS NULL AND wishlist_item_id IS NULL AND legacy_wishlist_item_id IS NOT NULL)))',
            name='ck_ppmp_order_item_source',
        ),
        CheckConstraint('quantity > 0', name='ck_ppmp_order_item_quantity'),
        CheckConstraint('estimated_budget >= 0', name='ck_ppmp_order_item_budget'),
    )

    @property
    def total_cost(self):
        return float(self.estimated_budget or 0)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'master_item_id': self.master_item_id,
            'wishlist_item_id': self.wishlist_item_id,
            'legacy_wishlist_item_id': self.legacy_wishlist_item_id,
            'ppmp_item_id': self.ppmp_item_id,
            'item_name': self.item_name,
            'description': self.description,
            'category': self.category,
            'project_type': self.project_type,
            'quantity': float(self.quantity or 0),
            'unit': self.unit,
            'procurement_method': self.procurement_method,
            'pre_procurement_conference': self.pre_procurement_conference,
            'procurement_start': self.procurement_start.isoformat() if self.procurement_start else None,
            'procurement_end': self.procurement_end.isoformat() if self.procurement_end else None,
            'delivery_period': self.delivery_period.isoformat() if self.delivery_period else None,
            'schedule_as_needed': bool(self.schedule_as_needed),
            'source_of_funds': self.source_of_funds,
            'estimated_unit_cost': float(
                self.estimated_unit_cost
                if self.estimated_unit_cost is not None
                else (Decimal(self.estimated_budget or 0) / Decimal(self.quantity or 1))
            ),
            'estimated_budget': float(self.estimated_budget or 0),
            'total_cost': self.total_cost,
            'supporting_documents': self.supporting_documents,
            'remarks': self.remarks,
            'is_custom_item': bool(self.is_custom_item),
            'is_legacy_item': self.legacy_wishlist_item_id is not None,
            'source_type': (
                'Custom / Unlisted' if self.is_custom_item
                else 'PPMP Wishlist Item' if self.wishlist_item_id is not None
                else 'CSE Master List'
            ),
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class PPMPReport(db.Model):
    """Administrator-published PPMP report definition; report rows remain live and scoped."""
    __tablename__ = 'ppmp_reports'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(180), nullable=False)
    office_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    office = db.relationship('College')
    updater = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'office_id': self.office_id,
            'office_code': self.office.code if self.office else '',
            'office_name': self.office.name if self.office else '',
            'fiscal_year': self.fiscal_year,
            'updated_by_name': self.updater.full_name if self.updater else 'Administrator',
            'is_available': bool(self.is_available),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PPMPComment(db.Model):
    __tablename__ = 'ppmp_comments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ppmp_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='CASCADE'), nullable=True)
    wishlist_request_id = db.Column(db.Integer, db.ForeignKey('wishlist_requests.id', ondelete='CASCADE'), nullable=True)
    ppmp_record_id = db.Column(db.Integer, db.ForeignKey('ppmp_records.id', ondelete='CASCADE'), nullable=True)
    ppmp_record_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_record_items.id', ondelete='CASCADE'), nullable=True)
    wishlist_order_id = db.Column(db.Integer, db.ForeignKey('ppmp_orders.id', ondelete='CASCADE'), nullable=True)
    comment_type = db.Column(db.String(32), nullable=False, default='PPMP Review')
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    message = db.Column(Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User')
    ppmp_record = db.relationship('PPMPRecord')
    ppmp_record_item = db.relationship('PPMPRecordItem')
    wishlist_order = db.relationship('PPMPOrder')

    def to_dict(self):
        return {'id': self.id, 'ppmp_item_id': self.ppmp_item_id, 'wishlist_request_id': self.wishlist_request_id,
                'ppmp_record_id': self.ppmp_record_id, 'ppmp_record_item_id': self.ppmp_record_item_id,
                'wishlist_order_id': self.wishlist_order_id, 'comment_type': self.comment_type,
                'author': self.author.full_name if self.author else 'System', 'office': self.author.office if self.author else None,
                'role': self.author.role if self.author else None, 'message': self.message,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class ConsolidationBatch(db.Model):
    __tablename__ = 'consolidation_batches'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    app_cycle = db.Column(db.String(40), nullable=False, default='ANNUAL')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User')
    __table_args__ = (UniqueConstraint('fiscal_year', 'app_cycle', name='uq_consolidation_year_cycle'),)


class ConsolidationSource(db.Model):
    __tablename__ = 'consolidation_sources'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('consolidation_batches.id', ondelete='CASCADE'), nullable=False)
    ppmp_item_id = db.Column(db.Integer, db.ForeignKey('ppmp_items.id', ondelete='RESTRICT'), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    batch = db.relationship('ConsolidationBatch')
    ppmp_item = db.relationship('PPMPItem')


class AnnualProcurementPlan(db.Model):
    __tablename__ = 'annual_procurement_plans'

    TYPES = ('APP', 'APP_CSE', 'APP_NON_CSE')
    STATUSES = ('Draft', 'Submitted', 'Under Review', 'For Admin Approval', 'Returned', 'Rejected', 'Approved', 'Finalized', 'Imported')

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    office = db.Column(db.String(120), nullable=False)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    plan_type = db.Column(db.String(16), nullable=False, default='APP')
    # Consolidation remains mandatory for normal APP creation.  NULL is reserved
    # for explicitly imported source documents that have no system PPMP history.
    consolidation_batch_id = db.Column(db.Integer, db.ForeignKey('consolidation_batches.id', ondelete='RESTRICT'), nullable=True)
    source_type = db.Column(db.String(32), nullable=False, default='CONSOLIDATION')
    source_details = db.Column(JSON, nullable=True)
    # Version 1 preserves existing APP permissions and historical review order.
    workflow_version = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    current_review_role = db.Column(db.String(64), nullable=True)
    return_review_role = db.Column(db.String(64), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    supplemental_parent_id = db.Column(
        db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='RESTRICT'), nullable=True,
    )
    status = db.Column(db.String(32), nullable=False, default='Draft')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    remarks = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User')
    supplemental_parent = db.relationship(
        'AnnualProcurementPlan', remote_side=[id], foreign_keys=[supplemental_parent_id],
    )
    consolidation_batch = db.relationship('ConsolidationBatch')
    sections = db.relationship(
        'APPSection', back_populates='app', cascade='all, delete-orphan',
        order_by='APPSection.sort_order, APPSection.id', lazy='select',
    )
    items = db.relationship(
        'APPItem', back_populates='app', cascade='all, delete-orphan',
        order_by='APPItem.id', lazy='select',
    )
    approvals = db.relationship(
        'APPApproval', back_populates='app', cascade='all, delete-orphan',
        order_by='APPApproval.id', lazy='select',
    )
    comments = db.relationship(
        'APPComment', back_populates='app', cascade='all, delete-orphan',
        order_by='APPComment.id', lazy='select',
    )
    batch_links = db.relationship(
        'APPBatchLink', back_populates='app', cascade='all, delete-orphan',
        order_by='APPBatchLink.id', lazy='select',
    )
    workflow_registration = db.relationship(
        'APPWorkflowRegistry', back_populates='app', cascade='all, delete-orphan', uselist=False,
    )
    __table_args__ = (UniqueConstraint('office', 'fiscal_year', 'plan_type', name='uq_app_office_year_type'),)

    def totals(self):
        included = list(self.items)
        cse_budget = Decimal('0.00')
        for item in included:
            if (self.workflow_version or 1) >= 2 and item.contributions:
                # A merged row can include both catalog and custom sources.
                # Count only the catalog allocations, using their revised APP
                # budgets while preserving the approved PPMP snapshots.
                cse_budget += sum((
                    allocation.estimated_budget or Decimal('0.00')
                    for allocation in item.contributions
                    if (allocation.source_snapshot or {}).get('is_cse') is True
                ), Decimal('0.00'))
            elif self.plan_type == 'APP_CSE' or (item.section and 'CSE' in item.section.name.upper()):
                cse_budget += item.estimated_budget or Decimal('0.00')
        by_section = {
            section.name: float(sum(
                (item.estimated_budget or Decimal('0.00'))
                for item in included if item.section_id == section.id
            )) for section in self.sections
        }
        by_mode = {}
        for item in included:
            mode = item.mode_of_procurement or 'Unspecified'
            by_mode[mode] = by_mode.get(mode, 0.0) + float(item.estimated_budget or 0)
        return {
            'overall': float(sum((item.estimated_budget or Decimal('0.00')) for item in included)),
            'early_procurement': float(sum(
                (item.estimated_budget or Decimal('0.00'))
                for item in included if item.early_procurement_activity is True
            )),
            'cse': float(cse_budget),
            'capital_outlay': float(sum(
                (item.estimated_budget or Decimal('0.00')) for item in included
                if item.section and 'CAPITAL OUTLAY' in item.section.name.upper()
            )),
            'by_section': by_section,
            'by_mode': by_mode,
        }

    def to_dict(self, include_details=False):
        result = {
            'id': self.id, 'office': self.office, 'fiscal_year': self.fiscal_year,
            'plan_type': self.plan_type, 'consolidation_batch_id': self.consolidation_batch_id,
            'source_type': self.source_type, 'source_details': self.source_details or {},
            'workflow_version': self.workflow_version,
            'current_review_role': self.current_review_role,
            'return_review_role': self.return_review_role,
            'revision': self.revision,
            'supplemental_parent_id': self.supplemental_parent_id,
            'is_supplemental': self.supplemental_parent_id is not None,
            'supplemental_number': (
                self.workflow_registration.sequence if self.workflow_registration else None
            ),
            'batch_ids': [link.batch_id for link in self.batch_links],
            'status': self.status, 'remarks': self.remarks, 'created_by': self.created_by,
            'prepared_by_name': self.creator.full_name if self.creator else '',
            'item_count': len(self.items), 'section_count': len(self.sections),
            'totals': self.totals(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_details:
            result['sections'] = [section.to_dict(include_items=True) for section in self.sections]
            result['approval_history'] = [approval.to_dict() for approval in self.approvals]
            result['comments'] = [comment.to_dict() for comment in self.comments]
        return result


class APPWorkflowRegistry(db.Model):
    """Allocate annual/supplemental APP identities without changing legacy keys."""
    __tablename__ = 'app_workflow_registry'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_id = db.Column(
        db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='CASCADE'), nullable=False, unique=True,
    )
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    # Zero is the annual APP; subsequent numbers identify supplements.
    sequence = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    app = db.relationship('AnnualProcurementPlan', back_populates='workflow_registration')

    __table_args__ = (
        UniqueConstraint('fiscal_year', 'sequence', name='uq_app_workflow_year_sequence'),
        CheckConstraint('sequence >= 0', name='ck_app_workflow_sequence'),
    )


class APPBatchLink(db.Model):
    """Each consolidation batch contributes to exactly one APP."""
    __tablename__ = 'app_batch_links'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_id = db.Column(
        db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='CASCADE'), nullable=False,
    )
    batch_id = db.Column(
        db.Integer, db.ForeignKey('consolidation_batches.id', ondelete='RESTRICT'), nullable=False, unique=True,
    )
    added_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    added_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    app = db.relationship('AnnualProcurementPlan', back_populates='batch_links')
    batch = db.relationship('ConsolidationBatch')
    actor = db.relationship('User', foreign_keys=[added_by])

    __table_args__ = (
        UniqueConstraint('app_id', 'batch_id', name='uq_app_batch_link'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'app_id': self.app_id, 'batch_id': self.batch_id,
            'added_by': self.added_by, 'added_at': self.added_at.isoformat() if self.added_at else None,
        }


class APPSection(db.Model):
    """A printed APP group header, kept separate from procurement project rows."""
    __tablename__ = 'app_sections'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_id = db.Column(
        db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='CASCADE'), nullable=False,
    )
    name = db.Column(db.String(180), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    app = db.relationship('AnnualProcurementPlan', back_populates='sections')
    creator = db.relationship('User')
    items = db.relationship('APPItem', back_populates='section', order_by='APPItem.id', lazy='select')

    __table_args__ = (
        UniqueConstraint('app_id', 'name', name='uq_app_section_name'),
        CheckConstraint('sort_order >= 0', name='ck_app_section_sort_order'),
    )

    @property
    def total_budget(self):
        return float(sum((item.estimated_budget or Decimal('0.00')) for item in self.items))

    def to_dict(self, include_items=False):
        result = {
            'id': self.id, 'app_id': self.app_id, 'name': self.name,
            'sort_order': self.sort_order, 'item_count': len(self.items),
            'total_budget': self.total_budget,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_items:
            result['items'] = [item.to_dict() for item in self.items]
        return result


class APPItem(db.Model):
    """One procurement project row in the official 12-column APP table."""
    __tablename__ = 'app_items'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_id = db.Column(
        db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='CASCADE'), nullable=False,
    )
    section_id = db.Column(db.Integer, db.ForeignKey('app_sections.id', ondelete='RESTRICT'), nullable=False)
    source_ppmp_item_id = db.Column(
        db.Integer, db.ForeignKey('ppmp_items.id', ondelete='RESTRICT'), nullable=True,
    )
    project_title = db.Column(Text, nullable=False)
    implementing_unit = db.Column(db.String(200), nullable=False)
    # Some official reference formats do not contain the 12-column APP's
    # general-description field. Normal interactive APP entry still requires it.
    general_description = db.Column(db.String(120), nullable=True)
    mode_of_procurement = db.Column(db.String(255), nullable=False)
    early_procurement_activity = db.Column(db.Boolean, nullable=True)
    bid_evaluation_criteria = db.Column(Text, nullable=True)
    procurement_start = db.Column(db.Date, nullable=True)
    procurement_end = db.Column(db.Date, nullable=True)
    source_of_fund = db.Column(db.String(120), nullable=False)
    estimated_budget = db.Column(DECIMAL(18, 2), nullable=False, default=0)
    quantity = db.Column(DECIMAL(12, 2), nullable=False, default=0, server_default='0')
    unit_size = db.Column(db.String(80), nullable=True)
    merge_key = db.Column(db.String(64), nullable=True, index=True)
    procurement_strategy_tools = db.Column(Text, nullable=True)
    remarks = db.Column(Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    app = db.relationship('AnnualProcurementPlan', back_populates='items')
    section = db.relationship('APPSection', back_populates='items')
    source_ppmp_item = db.relationship('PPMPItem')
    creator = db.relationship('User')
    contributions = db.relationship(
        'APPItemContribution', back_populates='app_item', cascade='all, delete-orphan',
        order_by='APPItemContribution.office_id, APPItemContribution.id', lazy='select',
    )

    __table_args__ = (
        UniqueConstraint('app_id', 'source_ppmp_item_id', name='uq_app_item_source'),
        CheckConstraint('estimated_budget >= 0', name='ck_app_item_budget'),
    )

    @staticmethod
    def month_label(value):
        return value.strftime('%m/%Y') if value else None

    def to_dict(self):
        return {
            'id': self.id, 'app_id': self.app_id, 'section_id': self.section_id,
            'source_ppmp_item_id': self.source_ppmp_item_id,
            'project_title': self.project_title, 'implementing_unit': self.implementing_unit,
            'general_description': self.general_description,
            'mode_of_procurement': self.mode_of_procurement,
            'early_procurement_activity': self.early_procurement_activity,
            'bid_evaluation_criteria': self.bid_evaluation_criteria,
            'procurement_start': self.month_label(self.procurement_start),
            'procurement_end': self.month_label(self.procurement_end),
            'source_of_fund': self.source_of_fund,
            'estimated_budget': float(self.estimated_budget or 0),
            'quantity': float(self.quantity or 0),
            'unit_size': self.unit_size,
            'merge_key': self.merge_key,
            'contributions': [contribution.to_dict() for contribution in self.contributions],
            'procurement_strategy_tools': self.procurement_strategy_tools,
            'remarks': self.remarks, 'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class APPItemContribution(db.Model):
    """Keep each office's source allocation when APP rows are merged or revised."""
    __tablename__ = 'app_item_contributions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_item_id = db.Column(db.Integer, db.ForeignKey('app_items.id', ondelete='CASCADE'), nullable=False)
    source_ppmp_item_id = db.Column(
        db.Integer, db.ForeignKey('ppmp_items.id', ondelete='RESTRICT'), nullable=False, unique=True,
    )
    office_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    original_quantity = db.Column(DECIMAL(12, 2), nullable=False)
    original_budget = db.Column(DECIMAL(18, 2), nullable=False)
    quantity = db.Column(DECIMAL(12, 2), nullable=False)
    estimated_budget = db.Column(DECIMAL(18, 2), nullable=False)
    source_snapshot = db.Column(JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    app_item = db.relationship('APPItem', back_populates='contributions')
    source_ppmp_item = db.relationship('PPMPItem', foreign_keys=[source_ppmp_item_id])
    office = db.relationship('College')

    __table_args__ = (
        CheckConstraint('original_quantity >= 0 AND quantity >= 0', name='ck_app_contribution_quantities'),
        CheckConstraint('original_budget >= 0 AND estimated_budget >= 0', name='ck_app_contribution_budgets'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'app_item_id': self.app_item_id,
            'source_ppmp_item_id': self.source_ppmp_item_id, 'office_id': self.office_id,
            'office_code': self.office.code if self.office else '',
            'office_name': self.office.name if self.office else '',
            'original_quantity': float(self.original_quantity or 0),
            'original_budget': float(self.original_budget or 0),
            'quantity': float(self.quantity or 0),
            'estimated_budget': float(self.estimated_budget or 0),
            'source_snapshot': self.source_snapshot or {},
        }


class APPApproval(db.Model):
    __tablename__ = 'app_approvals'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_id = db.Column(db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='CASCADE'), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    note = db.Column(Text, nullable=True)
    reviewer_role = db.Column(db.String(64), nullable=True)
    snapshot = db.Column(JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    app = db.relationship('AnnualProcurementPlan', back_populates='approvals')
    performer = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id, 'action': self.action, 'note': self.note,
            'performed_by': self.performed_by,
            'performed_by_name': self.performer.full_name if self.performer else 'System',
            'performed_by_role': self.reviewer_role or (self.performer.role if self.performer else None),
            'reviewer_role': self.reviewer_role,
            'snapshot': self.snapshot or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class APPComment(db.Model):
    """Append-only APP review note; optionally points to one APP item."""
    __tablename__ = 'app_comments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    app_id = db.Column(
        db.Integer, db.ForeignKey('annual_procurement_plans.id', ondelete='CASCADE'), nullable=False,
    )
    app_item_id = db.Column(db.Integer, db.ForeignKey('app_items.id', ondelete='SET NULL'), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    message = db.Column(Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    app = db.relationship('AnnualProcurementPlan', back_populates='comments')
    app_item = db.relationship('APPItem')
    author = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id, 'app_id': self.app_id, 'app_item_id': self.app_item_id,
            'author': self.author.full_name if self.author else 'System',
            'role': self.author.role if self.author else None,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class WorkflowAuditLog(db.Model):
    __tablename__ = 'workflow_audit_log'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(40), nullable=False)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    details = db.Column(JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    performer = db.relationship('User')


# ──────────────────────────────────────────────
# Helper: Query helpers for Flask routes
# ──────────────────────────────────────────────

class Survey(db.Model):
    __tablename__ = 'surveys'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(Text, nullable=True)
    fiscal_year = db.Column(db.SmallInteger, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User')

    def to_dict(self):
        return {'id': self.id, 'title': self.title, 'description': self.description,
                'fiscal_year': self.fiscal_year, 'is_enabled': self.is_enabled,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class SurveyRecipient(db.Model):
    __tablename__ = 'survey_recipients'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False)
    college_id = db.Column(db.Integer, db.ForeignKey('colleges.id', ondelete='RESTRICT'), nullable=False)
    response = db.Column(Text, nullable=True)
    responded_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)
    survey = db.relationship('Survey')
    college = db.relationship('College')
    __table_args__ = (UniqueConstraint('survey_id', 'college_id', name='uq_survey_college'),)

    def to_dict(self):
        return {'id': self.id, 'survey_id': self.survey_id, 'college_id': self.college_id,
                'college_name': self.college.name if self.college else None, 'response': self.response,
                'responded_at': self.responded_at.isoformat() if self.responded_at else None}


def get_ppmp_items(college_id=None, status=None, fund_source=None,
                   procurement_type=None, quarter=None, search=None,
                   fiscal_year=None):
    """Filterable PPMP query — mirrors the Flask in-memory filter logic."""
    q = PPMPItem.query.join(College)
    if college_id:
        q = q.filter(PPMPItem.college_id == college_id)
    if status:
        q = q.filter(PPMPItem.status == status)
    if fund_source:
        q = q.filter(PPMPItem.fund_source == fund_source)
    if procurement_type:
        q = q.filter(PPMPItem.procurement_type == procurement_type)
    if quarter:
        q = q.filter(PPMPItem.quarter == quarter)
    if fiscal_year:
        q = q.filter(PPMPItem.fiscal_year == fiscal_year)
    if search:
        q = q.filter(
            db.or_(
                PPMPItem.item_description.ilike(f'%{search}%'),
                College.name.ilike(f'%{search}%'),
            )
        )
    return q.order_by(PPMPItem.id.desc()).all()


def get_summary(fiscal_year=None, items=None):
    """Aggregate summary stats — replaces in-memory summary computation."""
    from sqlalchemy import func
    q = db.session.query(PPMPItem)
    if fiscal_year:
        q = q.filter(PPMPItem.fiscal_year == fiscal_year)
    items = q.all() if items is None else items
    total = sum(i.total_cost for i in items)

    by_college = {}
    by_fund    = {}
    by_quarter = {}
    by_status = {status: 0 for status in PPMPItem.STATUSES}

    for item in items:
        cname = item.college.name if item.college else 'Unknown'
        by_college[cname]    = by_college.get(cname, 0)    + item.total_cost
        by_fund[item.fund_source]          = by_fund.get(item.fund_source, 0) + item.total_cost
        if item.quarter:
            by_quarter[item.quarter]       = by_quarter.get(item.quarter, 0) + item.total_cost
        if item.status in by_status:
            by_status[item.status]        += 1

    return {
        'total_items':  len(items),
        'total_amount': total,
        'by_college':   by_college,
        'by_fund':      by_fund,
        'by_quarter':   by_quarter,
        'by_status':    by_status,
    }

