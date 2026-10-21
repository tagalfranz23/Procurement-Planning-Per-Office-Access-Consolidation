if __name__ == '__main__':
    print('Starting PPMP: loading Python dependencies (this can take a few seconds). Keep this window open; Ctrl+C cancels startup.', flush=True)

import io
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
import re
from xml.sax.saxutils import escape as xml_escape
from dotenv import load_dotenv

# Load project-local settings while allowing process environment variables to win.
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

import mysql.connector
from mysql.connector import Error as MySQLConnectorError
from flask import Flask, jsonify, render_template, request, send_file, session
from flask_cors import CORS
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A3, A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as ReportImage, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import inspect, or_, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from models import (
    APPApproval, APPComment, APPItem, APPSection, AnnualProcurementPlan,
    College, ConsolidationBatch, ConsolidationSource,
    DepartmentPPMPReviewCopy, DepartmentPPMPReviewItem, DepartmentPPMPSubmission,
    DepartmentPPMPSubmissionItem,
    PasswordResetRequest, PPMPAuditLog, PPMPComment, PPMPConsolidationLog, PPMPItem, PPMPNotification,
    PPMPOrder, PPMPOrderItem, PPMPRecord, PPMPRecordItem, PPMPReport, PPMPSubmissionRequest,
    Survey, SurveyRecipient, User, UserActivityLog, WishlistItem,
    WishlistRequest, WorkflowAuditLog,
    db, format_username, get_ppmp_items, get_summary,
)
from models import OfficialPPMP
from workflow_migrations import apply_workflow_migrations, workflow_required_columns
from notification_actions import (
    backfill_notification_links, notification_context, notification_payload,
    resolve_notification_tasks,
)
from ppmp_workflow import (
    can_edit_official_ppmp, create_indicative_copy, indicative_report_payload,
    register_ppmp_workflow_routes, create_copy_response, extended_report_changes,
    validate_report_timeline, workflow_history, positive_decimal,
)

FUND_SOURCES = list(PPMPItem.FUND_SOURCES)
MODES_OF_PROCUREMENT = list(PPMPItem.MODES)
APP_MODES_OF_PROCUREMENT = tuple(dict.fromkeys((*PPMPItem.MODES,
    'Direct Acquisition', 'Agency to Agency',
    'Direct Retail Purchase of Petroleum Fuel, Oil and Lubricant Products',
)))
PROCUREMENT_TYPES = list(PPMPItem.TYPES)
QUARTERS = list(PPMPItem.QUARTERS)
STATUSES = list(PPMPItem.STATUSES)
PPMP_ORDER_CATEGORIES = ('Goods', 'Infrastructure', 'Consulting Services')
PPMP_ORDER_FUND_SOURCES = ('GAA/101', 'SB 164', '161', '601')
PPMP_ORDER_TYPES = ('Goods/Services', 'Infrastructure', 'Consulting Services')
PPMP_REPORT_PROCUREMENT_METHODS = (
    'Competitive Bidding',
    'Competitive Dialogue',
    'Direct Acquisition',
    'Direct Contracting',
    'Direct Procurement for Science, Technology and Innovation',
    'Direct Sales',
    'Limited Source Bidding',
    'Negotiated Procurement - Adjacent or Contiguous',
    'Negotiated Procurement - Agency-to-Agency',
    'Negotiated Procurement - Community Participation',
    'Negotiated Procurement - Defense Cooperation',
    'Agreements and Inventory-Based Items',
    'Negotiated Procurement - Direct Retail Purchase of Petroleum Fuel, Oil and Lubricant Products, Electronic Charging Devices, and Online Subscriptions',
    'Negotiated Procurement - Emergency Cases',
    'Negotiated Procurement - Highly Technical Consultants',
    'Negotiated Procurement - International Events, Conferences, Summits or Activities Hosted by the Philippine Government',
    'Negotiated Procurement - Lease of Real Property and Venue',
    'Negotiated Procurement - Non-Government Organization (NGO) Participation',
    'Negotiated Procurement - Sagip Saka',
    'Negotiated Procurement - Scientific, Scholarly or Artistic Work, Exclusive Technology and Media Services',
    'Negotiated Procurement - Take-over of Contracts',
    'Negotiated Procurement - Two Failed Biddings',
    'Negotiated Procurement - United Nations (UN) Agencies, International Organizations or International Financing Institutions',
    'Repeat Order',
    'Small Value Procurement',
    'Unsolicited Offer with Bid Matching',
)
PPMP_REPORT_PENDING_STATUSES = {
    'Draft', 'Returned',
}
PPMP_REPORT_COLUMNS = (
    'General Description and Objective of the Project to be Procured',
    'Types of the Project to be procured (Whether Goods, Infrastructure, and Consulting Services)',
    'Quantity and Size of the Project to be Procured',
    'Recommended Mode of Procurement',
    'Pre-Procured conference, if applicable (Yes/No)',
    'Start of Procurement Activity',
    'End of Procurement Activity',
    'Expected Delivery Implementation Period',
    'Source of Funds',
    'Estimated Budget / Authorized Budgetary Allocation (Php)',
    'ATTACHED SUPPORTING DOCUMENTS',
    'REMARKS',
)
OFFICES = (
    "ACCOUNTING", "BAC CHAIRMAN", "BIRD-C", "BUDGET", "CASHIER", "CBAO", "COA", "EXTENSION", "FABLAB", "FIC", "GSO",
    "GUIDANCE", "EO", "QA", "AA", "EAPRIL", "HRMO/AFS", "INFIRMARY", "INFRA", "LIBRARY", "MIS",
    "NSTP/ROTC", "OSAS", "PLANNING AND DEV'T WITH GAD", "PROCUREMENT", "RECORDS", "REGISTRAR", "RESEARCH",
    "SOCIO", "SPORTS", "SSC", "SUPPLY", "SWINE PROJECT", "TKC",
)
DEPARTMENT_UNITS = {
    'CED': 'College of Education (CED)',
    'CBM': 'College of Business and Management (CBM)',
    'CAS': 'College of Arts and Sciences (CAS)',
    'CCSICT': 'College of Computing Studies, Information and Communication Technology (CCSICT)',
    'CCJE': 'College of Criminal Justice Education (CCJE)',
    'IAT': 'Institute of Agricultural Technology (IAT)',
    'PS': 'Polytechnic School (PS)',
}
DEPARTMENT_CODES = frozenset(DEPARTMENT_UNITS)
# Retain organizational identities for registration and normal office PPMP access.
RETIRED_DEPARTMENT_MODELS = (
    DepartmentPPMPReviewItem, DepartmentPPMPReviewCopy,
    DepartmentPPMPSubmissionItem, DepartmentPPMPSubmission,
)
WORKFLOW_ROLES = tuple(User.ROLES)

PPMP_OFFICE_ROLES = (set(OFFICES) | set(DEPARTMENT_CODES)) - {'EO', 'PROCUREMENT', 'BUDGET', 'BAC CHAIRMAN'}
ROLE_PERMISSIONS = {
    'ADMIN': {'*'},
    'EO': {'ppmp.view', 'ppmp.request.create', 'ppmp.request.monitor', 'ppmp.order.view',
           'ppmp.record.view', 'ppmp.record.review', 'ppmp.review', 'ppmp.return',
           'ppmp.reject', 'ppmp.comment', 'ppmp.report', 'ppmp.export', 'survey.manage',
           'app.view', 'app.review', 'app.return', 'app.report', 'app.export'},
    'PROCUREMENT': {'ppmp.view', 'ppmp.order.view', 'ppmp.record.view', 'ppmp.record.review', 'ppmp.review',
                    'ppmp.return', 'ppmp.reject', 'ppmp.approve',
                    'ppmp.comment', 'ppmp.report', 'ppmp.export',
                    'app.view', 'app.review',
                    'app.return', 'app.reject', 'app.report', 'app.export', 'app.cse.view'},
    'BUDGET': {'ppmp.view', 'ppmp.order.view', 'ppmp.record.view', 'ppmp.review', 'ppmp.return', 'ppmp.comment', 'ppmp.report',
               'app.view', 'app.review', 'app.return', 'app.reject', 'app.report', 'app.export',
               'app.cse.view', 'app.cse.review'},
    'BAC CHAIRMAN': {'ppmp.view','app.view', 'app.review', 'app.return', 'app.reject', 'app.report',
                     'app.export', 'app.cse.view', 'app.cse.review', 'app.cse.approve'},
}
OFFICE_PERMISSIONS = {
    'ppmp.view', 'ppmp.wishlist.view', 'ppmp.record.view', 'ppmp.record.create',
    'ppmp.record.edit', 'ppmp.record.submit', 'ppmp.order.create', 'ppmp.order.view',
    'ppmp.report', 'ppmp.export',
}

PASSWORD_RESET_REQUEST_MESSAGE = (
    'Password recovery email delivery is not configured yet. No administrator approval request was created. '
    'Contact authorized system support for the current recovery procedure.'
)
_RESET_RATE_BUCKETS = {}
_RESET_RATE_LOCK = threading.Lock()
REGISTRATION_TOKEN_MAX_AGE = 60 * 60 * 24 * 30


def reset_rate_limited(bucket, key, limit, window_seconds):
    """Small single-process throttle; token attempts are also persisted in MariaDB."""
    now = time.monotonic()
    rate_key = f'{bucket}:{key}'
    with _RESET_RATE_LOCK:
        recent = [timestamp for timestamp in _RESET_RATE_BUCKETS.get(rate_key, ())
                  if now - timestamp < window_seconds]
        if len(recent) >= limit:
            _RESET_RATE_BUCKETS[rate_key] = recent
            return True
        recent.append(now)
        _RESET_RATE_BUCKETS[rate_key] = recent
        return False


def registration_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='registration-status-v1')


def create_registration_token(user):
    return registration_serializer().dumps({
        'registration': user.id,
        'fingerprint': hashlib.sha256(user.email.encode('utf-8')).hexdigest()[:16],
    })


def configured_offices():
    """Configured operational offices plus active persisted office identities."""
    persisted = {office.code for office in College.query.filter_by(is_active=True).all()}
    return tuple(sorted(set(OFFICES) | set(DEPARTMENT_CODES) | persisted))


def configured_roles():
    return tuple(sorted(set(User.ROLES) | set(configured_offices())))


def is_ppmp_office_role(role):
    if role in ROLE_PERMISSIONS:
        return False
    return role in PPMP_OFFICE_ROLES or role in {office.code for office in College.query.filter_by(is_active=True).all()}


def permissions_for(user):
    if not user:
        return set()
    return ROLE_PERMISSIONS.get(user.role, OFFICE_PERMISSIONS if is_ppmp_office_role(user.role) else set())


def has_permission(user, permission):
    permissions = permissions_for(user)
    return '*' in permissions or permission in permissions


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_session_user()
            if user is None or not user.is_active or user.account_status != 'ACTIVE':
                return jsonify({'error': 'Authentication required.'}), 401
            if not has_permission(user, permission):
                return jsonify({'error': 'You are not authorized to perform this action.'}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def database_uri():
    if os.getenv('DATABASE_URL'):
        configured_url = make_url(os.environ['DATABASE_URL'])
        if configured_url.drivername in {'postgres', 'postgresql', 'postgresql+psycopg2'}:
            configured_url = configured_url.set(drivername='postgresql+psycopg')
        return configured_url.render_as_string(hide_password=False)
    backend = os.getenv('DB_BACKEND', 'sqlite').strip().lower()
    if backend == 'mariadb':
        return URL.create(
            'mysql+mysqlconnector',
            username=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', '3306')),
            database=os.getenv('DB_NAME', 'ppmp_db'),
            query={'charset': 'utf8mb4'},
        ).render_as_string(hide_password=False)
    if backend in {'postgres', 'postgresql'}:
        return URL.create(
            'postgresql+psycopg',
            username=os.getenv('DB_USER', 'ppmp_user'),
            password=os.getenv('DB_PASSWORD', ''),
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', '5432')),
            database=os.getenv('DB_NAME', 'ppmp_db'),
        ).render_as_string(hide_password=False)
    if backend != 'sqlite':
        raise ValueError("DB_BACKEND must be 'sqlite', 'mariadb', or 'postgresql'.")
    # SQLite is the default; MariaDB and PostgreSQL are explicit deployment choices.
    sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ppmp.sqlite')
    return URL.create('sqlite', database=sqlite_path).render_as_string(hide_password=False)


def get_db():
    """Open the configured database for the startup connectivity check."""
    return db.engine.raw_connection()


DATABASE_URI = database_uri()
DATABASE_BACKEND = make_url(DATABASE_URI).get_backend_name()
if DATABASE_BACKEND == 'sqlite':
    ENGINE_OPTIONS = {}
elif DATABASE_BACKEND == 'postgresql':
    ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'connect_args': {'connect_timeout': 5},
    }
else:
    ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'connect_args': {'connection_timeout': 5},
    }
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
if (os.getenv('FLASK_ENV', '').strip().lower() == 'production'
        and FLASK_SECRET_KEY in {None, '', 'change-this-development-secret', 'change-this-to-a-random-secret-key'}):
    raise RuntimeError('Set a unique FLASK_SECRET_KEY before starting in production.')
app = Flask(__name__)
app.config.update(
    SECRET_KEY=FLASK_SECRET_KEY or 'change-this-development-secret',
    SQLALCHEMY_DATABASE_URI=DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS=ENGINE_OPTIONS,
    TEMPLATES_AUTO_RELOAD=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('FLASK_ENV') == 'production',
)
CORS(app, supports_credentials=True, origins=[])
db.init_app(app)
app.jinja_env.auto_reload = True


@app.after_request
def prevent_sensitive_html_caching(response):
    """Keep Login/Dashboard HTML revisions and authenticated pages out of browser caches."""
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_session_user()
        if user is None or not user.is_active or user.account_status != 'ACTIVE':
            return jsonify({'error': 'Authentication required.'}), 401
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Allow account-approval actions only to an active administrator."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = db.session.get(User, session.get("user_id")) if session.get("user_id") else None
        if user is None or not user.is_active or user.account_status != 'ACTIVE' or user.role != "ADMIN":
            return jsonify({"error": "Administrator access required."}), 403
        return view(*args, **kwargs)
    return wrapped


def current_session_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


def roles_required(*roles):
    """Enforce workflow roles server-side for every sensitive action."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_session_user()
            if user is None or not user.is_active:
                return jsonify({"error": "Authentication required."}), 401
            if user.role not in roles:
                return jsonify({"error": "You do not have permission for this action."}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def add_notification(recipients, title, message, notification_type="info", ppmp_item_id=None,
                     *, target_type=None, target_id=None, action_stage=None):
    seen = set()
    for recipient in recipients:
        if recipient is None or recipient.id in seen:
            continue
        seen.add(recipient.id)
        db.session.add(PPMPNotification(recipient_id=recipient.id, ppmp_item_id=ppmp_item_id,
                                        type=notification_type, title=title, message=message,
                                        target_type=target_type or ('ppmp_item' if ppmp_item_id else None),
                                        target_id=target_id if target_type else ppmp_item_id,
                                        action_stage=action_stage))


def notify_roles(roles, title, message, notification_type="info", ppmp_item_id=None, **target):
    add_notification(User.query.filter(User.role.in_(roles), User.is_active.is_(True),
                                       User.account_status == 'ACTIVE').all(),
                     title, message, notification_type, ppmp_item_id, **target)


def notify_offices(office_ids, title, message, notification_type='info', extra_recipients=(), **target):
    """Notify every active account in the affected offices, never unrelated offices."""
    office_ids = {office_id for office_id in office_ids if office_id is not None}
    office_codes = [office.code for office in College.query.filter(College.id.in_(office_ids)).all()]
    recipients = User.query.filter(
        User.is_active.is_(True), User.account_status == 'ACTIVE',
        or_(User.college_id.in_(office_ids), User.office.in_(office_codes)),
    ).all() if office_ids else []
    recipients.extend(user for user in extra_recipients
                      if user and user.is_active and user.account_status == 'ACTIVE')
    add_notification(recipients, title, message, notification_type, **target)


def notify_ppmp_order_update(order, action, reviewer_role, note=None):
    label = (f'{order.reference_number} '
             f'({order.office.code if order.office else "Office"}, FY {order.fiscal_year})')
    if order.status in {'Pending Admin Approval', 'Procurement Review'}:
        detail = ('was resubmitted and requires Administrator review.' if action == 'submit'
                  else 'was approved by Procurement and requires Administrator review.')
        title = 'PPMP awaiting Administrator review'
        notify_roles(('ADMIN',), title, f'{label} {detail} Open PPMP Request Records to review it.',
                     target_type='ppmp_order', target_id=order.id, action_stage='ADMIN')
    elif order.status in {'Submitted', 'EO Review'}:
        detail = 'was resubmitted for Procurement review.' if order.return_stage else 'was submitted for Procurement review.'
        title = 'PPMP awaiting Procurement review'
        notify_roles(('PROCUREMENT',), title, f'{label} {detail} Open PPMP Request Records to review it.',
                     target_type='ppmp_order', target_id=order.id, action_stage='PROCUREMENT')
    else:
        title = f'PPMP {order.status.lower()}'
        detail = {
            'Returned': f'was returned by {reviewer_role}. The creator must correct and resubmit it.',
            'Rejected': f'was rejected by {reviewer_role}.',
            'Approved': 'received final Administrator approval. The official PPMP is now locked.',
            'Processing': 'is now being processed.',
            'Completed': 'has been completed.',
        }.get(order.status, f'is now {order.status}.')
    message = f'{label} {detail}' + (f' Review note: {note}' if note else '')
    notification_type = ('success' if order.status in {'Approved', 'Completed'} else
                         'warning' if order.status in {'Returned', 'Rejected'} else 'info')
    if order.status not in {'Pending Admin Approval', 'Procurement Review'} and reviewer_role != 'ADMIN':
        notify_roles(('ADMIN',), f'PPMP {order.status.lower()}', message, notification_type,
                     target_type='ppmp_order', target_id=order.id)
    notify_offices({order.office_id}, title, message, notification_type,
                   extra_recipients=[order.requester], target_type='ppmp_order', target_id=order.id,
                   action_stage='CREATOR' if order.status == 'Returned' else None)


def app_notification_label(plan):
    supplemental = 'Supplemental APP' if plan.supplemental_parent_id else 'APP'
    return f'{supplemental} #{plan.id}, FY {plan.fiscal_year}, revision {plan.revision or 1}'


def notify_app_offices(plan, title, message, notification_type='info', app_items=None, action_stage=None):
    # Contributions cover merged sources; source items also cover historical APPs.
    items = plan.items if app_items is None else app_items
    office_ids = {row.office_id for item in items for row in item.contributions}
    sources = [item.source_ppmp_item for item in items if item.source_ppmp_item is not None]
    office_ids.update(item.college_id for item in sources)
    if not office_ids:
        office = College.query.filter_by(code=plan.office).first()
        if office:
            office_ids.add(office.id)
    notify_offices(office_ids, title, message, notification_type,
                   target_type='app', target_id=plan.id, action_stage=action_stage)


def audit(entity_type, entity_id, action, details=None):
    user = current_session_user()
    db.session.add(WorkflowAuditLog(entity_type=entity_type, entity_id=entity_id, action=action,
                                    performed_by=user.id if user else None,
                                    ip_address=request.headers.get('X-Forwarded-For', request.remote_addr),
                                    details=details or {}))


@app.before_request
def require_authenticated_api_user():
    if request.method == "OPTIONS":
        return None
    public_api = {
        '/api/auth/login', '/api/auth/logout', '/api/auth/me', '/api/auth/register',
        '/api/auth/available-roles', '/api/auth/registration-status',
        '/api/auth/forgot-password', '/api/auth/reset-password',
    }
    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        auth_version = int(user.auth_version or 0) if user else -1
        if (user is None or not user.is_active or user.account_status != 'ACTIVE'
                or session.get('auth_version', 0) != auth_version):
            session.clear()
        else:
            session['role'] = user.role
            session['username'] = format_username(user.username)
            session['auth_version'] = auth_version
    if request.path.startswith("/api/") and request.path not in public_api:
        if "user_id" not in session:
            return jsonify({"error": "Authentication required."}), 401
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.path.startswith('/api/'):
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return jsonify({'error': 'Cross-site request rejected.'}), 403


def ensure_admin_account():
    """Create only the requested initial admin account; never seed business data."""
    if User.query.filter_by(role="ADMIN").first() is None:
        initial_password = os.getenv('INITIAL_ADMIN_PASSWORD')
        if os.getenv('FLASK_ENV', '').strip().lower() == 'production' and not initial_password:
            raise RuntimeError(
                'Set INITIAL_ADMIN_PASSWORD before initializing a production database.'
            )
        db.session.add(User(
            username="admin", full_name="System Administrator", email="admin@localhost",
            password_hash=generate_password_hash(initial_password or 'admin1234'),
            role="ADMIN", office='ADMINISTRATION', account_status='ACTIVE', is_active=True,
        ))
        db.session.commit()


def reset_database():
    """Delete all operational data, then leave only admin/admin1234."""
    existing_tables = set(inspect(db.engine).get_table_names())
    db.session.query(PasswordResetRequest).delete()
    db.session.query(SurveyRecipient).delete()
    db.session.query(Survey).delete()
    db.session.query(APPComment).delete()
    db.session.query(APPApproval).delete()
    db.session.query(APPItem).delete()
    db.session.query(APPSection).delete()
    db.session.query(AnnualProcurementPlan).delete()
    db.session.query(PPMPReport).delete()
    db.session.query(ConsolidationSource).delete()
    db.session.query(ConsolidationBatch).delete()
    db.session.query(PPMPComment).delete()
    db.session.query(PPMPOrderItem).delete()
    db.session.query(PPMPOrder).delete()
    db.session.query(PPMPRecordItem).delete()
    db.session.query(PPMPRecord).delete()
    # Retired tables are optional on installations that never used the feature.
    for model in RETIRED_DEPARTMENT_MODELS:
        if model.__tablename__ in existing_tables:
            db.session.query(model).delete()
    db.session.query(WishlistRequest).delete()
    db.session.query(WishlistItem).delete()
    db.session.query(PPMPSubmissionRequest).delete()
    db.session.query(WorkflowAuditLog).delete()
    db.session.query(PPMPNotification).delete()
    db.session.query(PPMPAuditLog).delete()
    db.session.query(PPMPConsolidationLog).delete()
    db.session.query(PPMPItem).delete()
    db.session.query(User).delete()
    db.session.query(College).delete()
    db.session.commit()
    ensure_admin_account()


def verify_database_schema():
    """Read-only startup check. Schema changes belong to --migrate-only."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    retired_tables = {model.__tablename__ for model in RETIRED_DEPARTMENT_MODELS}
    required_tables = set(db.metadata.tables) - retired_tables
    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        raise RuntimeError(
            'Database schema is not initialized. Missing tables: '
            + ', '.join(missing_tables)
            + '. Back up the database, then run: python app.py --migrate-only'
        )
    required_columns = {
        'users': {'office', 'role', 'released_role', 'account_status', 'auth_version'},
        'user_activity_logs': {'user_id', 'time_in', 'time_out'},
        'ppmp_items': {'authorized_budget'},
        'annual_procurement_plans': {'consolidation_batch_id', 'source_type', 'source_details'},
        'app_sections': {'app_id', 'name', 'sort_order', 'created_by'},
        'app_items': {
            'app_id', 'section_id', 'source_ppmp_item_id', 'project_title',
            'implementing_unit', 'general_description', 'mode_of_procurement',
            'early_procurement_activity', 'bid_evaluation_criteria',
            'procurement_start', 'procurement_end', 'source_of_fund',
            'estimated_budget', 'procurement_strategy_tools', 'remarks', 'created_by',
        },
        'app_comments': {'app_id', 'app_item_id', 'author_id', 'message'},
        'consolidation_batches': {'app_cycle'},
        'ppmp_records': {
            'reference_number', 'submission_request_id', 'office_id', 'fiscal_year',
            'status', 'prepared_by', 'decision_note', 'submitted_at', 'approved_by',
        },
        'ppmp_record_items': {
            'ppmp_record_id', 'general_description', 'project_type', 'quantity',
            'unit_size', 'procurement_method', 'pre_procurement_conference',
            'procurement_start', 'procurement_end', 'delivery_period',
            'schedule_as_needed', 'source_of_funds', 'estimated_budget',
            'supporting_documents', 'remarks', 'item_status', 'ppmp_item_id',
        },
        'ppmp_orders': {
            'reference_number', 'office_id', 'requested_by', 'fiscal_year',
            'fund_source', 'mode_of_procurement', 'procurement_type', 'quarter',
            'ppmp_document_number', 'status', 'legacy_wishlist_request_id',
        },
        'ppmp_order_items': {
            'order_id', 'master_item_id', 'wishlist_item_id', 'legacy_wishlist_item_id',
            'ppmp_item_id', 'item_name', 'category', 'quantity', 'unit',
            'estimated_unit_cost', 'estimated_budget', 'is_custom_item',
        },
        'ppmp_comments': {'ppmp_record_id', 'ppmp_record_item_id', 'wishlist_order_id', 'comment_type'},
        'workflow_audit_log': {'ip_address'},
    }
    for table_name, expected in workflow_required_columns.items():
        required_columns.setdefault(table_name, set()).update(expected)
    missing_columns = []
    for table_name, expected in required_columns.items():
        actual = {column['name'] for column in inspector.get_columns(table_name)}
        missing_columns.extend(f'{table_name}.{name}' for name in sorted(expected - actual))
    if missing_columns:
        raise RuntimeError(
            'Database migration is required. Missing columns: '
            + ', '.join(missing_columns)
            + '. Back up the database, then run: python app.py --migrate-only'
        )
    if User.query.filter_by(role='ADMIN', account_status='ACTIVE', is_active=True).first() is None:
        raise RuntimeError('No active ADMIN account exists. Run: python app.py --migrate-only')




def initialize_database(apply_migrations=False):
    with app.app_context():
        try:
            connection = get_db()
            connection.close()
            if apply_migrations:
                retired_tables = {model.__tablename__ for model in RETIRED_DEPARTMENT_MODELS}
                db.metadata.create_all(bind=db.engine, tables=[
                    table for name, table in db.metadata.tables.items() if name not in retired_tables
                ])
                apply_workflow_migrations(db)
                migrate_revision_schema()
                ensure_admin_account()
                backfill_notification_links(sys.modules[__name__])
                verify_database_schema()
            else:
                verify_database_schema()
        except (OperationalError, MySQLConnectorError) as error:
            db.session.rollback()
            message = str(getattr(error, "orig", error))
            if "auth_gssapi_client" in message:
                raise RuntimeError(
                    "MariaDB authentication fell back to the unsupported auth_gssapi_client "
                    "plugin. On Windows, this can happen when the configured password is "
                    "incorrect. Verify DATABASE_URL or DB_USER/DB_PASSWORD in ppmp/.env; "
                    "if needed, configure a dedicated application account with "
                    "mysql_native_password. See DATABASE_CONNECTION.md."
                ) from error
            target = db.engine.url
            if target.get_backend_name() == 'sqlite':
                detail = f"Unable to open the SQLite database at {target.database}. Check that its parent directory is writable."
            else:
                is_postgresql = target.get_backend_name() == 'postgresql'
                backend_label = 'PostgreSQL' if is_postgresql else 'MariaDB'
                detail = (
                    f"Unable to connect to the {backend_label} database at {target.host}:{target.port or (5432 if is_postgresql else 3306)}"
                    f"/{target.database} as {target.username}. Verify "
                    "DATABASE_URL or DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD."
                )
            raise RuntimeError(f"{detail} Driver error: {message}") from error
        except SQLAlchemyError as error:
            db.session.rollback()
            raise RuntimeError(f"{db.engine.dialect.name} initialization failed. See the server log for details.") from error


def migrate_revision_schema():
    """Apply additive revision changes without deleting procurement data."""
    inspector = inspect(db.engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "office" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN office VARCHAR(120) NULL"))
    if "account_status" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN account_status VARCHAR(16) NOT NULL DEFAULT 'PENDING'"))
        db.session.execute(text("UPDATE users SET account_status = CASE WHEN is_active IS TRUE THEN 'ACTIVE' ELSE 'PENDING' END"))
    if "released_role" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN released_role VARCHAR(64) NULL"))
    if 'auth_version' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0'))
    app_columns = {column['name'] for column in inspector.get_columns('annual_procurement_plans')}
    if 'consolidation_batch_id' not in app_columns:
        # Existing APP rows need explicit administrator reconciliation before
        # this column can safely become NOT NULL in a later migration.
        db.session.execute(text('ALTER TABLE annual_procurement_plans ADD COLUMN consolidation_batch_id INTEGER NULL'))
    if 'source_type' not in app_columns:
        db.session.execute(text(
            "ALTER TABLE annual_procurement_plans ADD COLUMN source_type "
            "VARCHAR(32) NOT NULL DEFAULT 'CONSOLIDATION'"
        ))
    if 'source_details' not in app_columns:
        db.session.execute(text('ALTER TABLE annual_procurement_plans ADD COLUMN source_details JSON NULL'))
    app_item_columns = {
        column['name']: column for column in inspector.get_columns('app_items')
    }
    if (db.engine.dialect.name == 'mysql'
            and not app_item_columns['general_description']['nullable']):
        db.session.execute(text(
            'ALTER TABLE app_items MODIFY COLUMN general_description VARCHAR(120) NULL'
        ))
    batch_columns = {column['name'] for column in inspector.get_columns('consolidation_batches')}
    if 'app_cycle' not in batch_columns:
        db.session.execute(text("ALTER TABLE consolidation_batches ADD COLUMN app_cycle VARCHAR(40) NOT NULL DEFAULT 'ANNUAL'"))
    audit_columns = {column['name'] for column in inspector.get_columns('workflow_audit_log')}
    if 'ip_address' not in audit_columns:
        db.session.execute(text('ALTER TABLE workflow_audit_log ADD COLUMN ip_address VARCHAR(45) NULL'))
    ppmp_item_columns = {column['name'] for column in inspector.get_columns('ppmp_items')}
    if 'authorized_budget' not in ppmp_item_columns:
        db.session.execute(text('ALTER TABLE ppmp_items ADD COLUMN authorized_budget DECIMAL(18,2) NULL'))
    comment_columns = {column['name'] for column in inspector.get_columns('ppmp_comments')}
    comment_additions = {
        'ppmp_record_id': 'INTEGER NULL',
        'ppmp_record_item_id': 'INTEGER NULL',
        'wishlist_order_id': 'INTEGER NULL',
        'comment_type': "VARCHAR(32) NOT NULL DEFAULT 'PPMP Review'",
    }
    for column_name, definition in comment_additions.items():
        if column_name not in comment_columns:
            db.session.execute(text(f'ALTER TABLE ppmp_comments ADD COLUMN {column_name} {definition}'))
    order_columns = {column['name'] for column in inspector.get_columns('ppmp_orders')}
    order_additions = {
        'fiscal_year': 'SMALLINT NULL',
        'ppmp_document_number': 'INTEGER NOT NULL DEFAULT 1',
        'fund_source': 'VARCHAR(80) NULL',
        'mode_of_procurement': 'VARCHAR(120) NULL',
        'procurement_type': 'VARCHAR(80) NULL',
        'quarter': 'VARCHAR(32) NULL',
    }
    for column_name, definition in order_additions.items():
        if column_name not in order_columns:
            db.session.execute(text(f'ALTER TABLE ppmp_orders ADD COLUMN {column_name} {definition}'))
    order_item_column_map = {
        column['name']: column for column in inspector.get_columns('ppmp_order_items')
    }
    order_item_columns = set(order_item_column_map)
    order_item_additions = {
        'master_item_id': 'INTEGER NULL',
        'category': 'VARCHAR(80) NULL',
        'estimated_unit_cost': 'DECIMAL(15,2) NULL',
        'is_custom_item': 'BOOLEAN NOT NULL DEFAULT FALSE',
    }
    for column_name, definition in order_item_additions.items():
        if column_name not in order_item_columns:
            db.session.execute(text(f'ALTER TABLE ppmp_order_items ADD COLUMN {column_name} {definition}'))
    if db.engine.dialect.name == 'mysql':
        method_column = order_item_column_map.get('procurement_method')
        method_length = getattr(method_column.get('type'), 'length', None) if method_column else None
        if method_length is not None and method_length < 255:
            db.session.execute(text(
                'ALTER TABLE ppmp_order_items MODIFY COLUMN procurement_method VARCHAR(255) NULL'
            ))
    if db.engine.dialect.name == 'mysql':
        year_expression = 'YEAR(COALESCE(submitted_at, created_at, CURRENT_TIMESTAMP))'
    elif db.engine.dialect.name == 'postgresql':
        year_expression = 'CAST(EXTRACT(YEAR FROM COALESCE(submitted_at, created_at, CURRENT_TIMESTAMP)) AS INTEGER)'
    else:
        year_expression = "CAST(strftime('%Y', COALESCE(submitted_at, created_at, CURRENT_TIMESTAMP)) AS INTEGER)"
    db.session.execute(text(
        f'UPDATE ppmp_orders SET fiscal_year = {year_expression} WHERE fiscal_year IS NULL'
    ))
    db.session.execute(text(
        'UPDATE ppmp_order_items SET estimated_unit_cost = '
        'CASE WHEN quantity > 0 THEN estimated_budget / quantity ELSE 0 END '
        'WHERE estimated_unit_cost IS NULL'
    ))
    db.session.execute(text(
        "UPDATE ppmp_orders SET status = 'Pending Admin Approval' WHERE status = 'Requested'"
    ))
    if db.engine.dialect.name == "mysql":
        # Convert legacy ENUM values only after accepting them temporarily, then remove them.
        db.session.execute(text("ALTER TABLE users MODIFY COLUMN role VARCHAR(64) NULL"))
        db.session.execute(text("UPDATE users SET role = UPPER(role) WHERE role IS NOT NULL"))
        db.session.execute(text("ALTER TABLE ppmp_items MODIFY COLUMN status VARCHAR(32) NOT NULL DEFAULT 'Draft'"))
        db.session.execute(text("ALTER TABLE ppmp_items MODIFY COLUMN fund_source VARCHAR(80) NOT NULL"))
        db.session.execute(text("ALTER TABLE ppmp_items MODIFY COLUMN mode_of_procurement VARCHAR(255) NOT NULL"))
        db.session.execute(text("ALTER TABLE ppmp_items MODIFY COLUMN procurement_type VARCHAR(80) NOT NULL DEFAULT 'Goods'"))
        db.session.execute(text("UPDATE ppmp_items SET status = 'Submitted' WHERE status = 'Pending'"))
        db.session.execute(text("UPDATE ppmp_items SET status = 'Rejected' WHERE status = 'Cancelled'"))
        db.session.execute(text('ALTER TABLE ppmp_orders MODIFY COLUMN fiscal_year SMALLINT NOT NULL'))
    elif db.engine.dialect.name == 'postgresql':
        db.session.execute(text("UPDATE users SET role = UPPER(role) WHERE role IS NOT NULL"))
        db.session.execute(text("UPDATE ppmp_items SET status = 'Submitted' WHERE status = 'Pending'"))
        db.session.execute(text("UPDATE ppmp_items SET status = 'Rejected' WHERE status = 'Cancelled'"))
    db.session.commit()
    duplicates = db.session.execute(text("SELECT role, COUNT(*) AS n FROM users WHERE role IS NOT NULL GROUP BY role HAVING COUNT(*) > 1")).all()
    if duplicates:
        conflicts = ', '.join(f'{row.role} ({row.n})' for row in duplicates)
        raise RuntimeError('Role uniqueness migration blocked; resolve duplicate assignments first: ' + conflicts)
    if db.engine.dialect.name in {'mysql', 'postgresql'}:
        user_indexes = inspect(db.engine).get_indexes('users')
        role_has_unique_index = any(
            index.get('unique') and tuple(index.get('column_names') or ()) == ('role',)
            for index in user_indexes
        )
        role_has_unique_constraint = any(
            tuple(constraint.get('column_names') or ()) == ('role',)
            for constraint in inspect(db.engine).get_unique_constraints('users')
        )
        if not role_has_unique_index and not role_has_unique_constraint:
            db.session.execute(text('CREATE UNIQUE INDEX uq_users_role ON users (role)'))
            db.session.commit()
        duplicate_cycles = db.session.execute(text(
            'SELECT fiscal_year, app_cycle, COUNT(*) AS n FROM consolidation_batches '
            'GROUP BY fiscal_year, app_cycle HAVING COUNT(*) > 1'
        )).all()
        if duplicate_cycles:
            conflicts = ', '.join(f'{row.fiscal_year}/{row.app_cycle} ({row.n})' for row in duplicate_cycles)
            raise RuntimeError('Consolidation-cycle uniqueness migration blocked; resolve duplicate batches first: ' + conflicts)
        batch_constraints = {item['name'] for item in inspect(db.engine).get_unique_constraints('consolidation_batches')}
        if 'uq_consolidation_year_cycle' not in batch_constraints:
            db.session.execute(text(
                'ALTER TABLE consolidation_batches ADD CONSTRAINT uq_consolidation_year_cycle '
                'UNIQUE (fiscal_year, app_cycle)'
            ))
            db.session.commit()
        duplicate_requests = db.session.execute(text(
            'SELECT college_id, fiscal_year, COUNT(*) AS n FROM ppmp_submission_requests '
            'GROUP BY college_id, fiscal_year HAVING COUNT(*) > 1'
        )).all()
        if duplicate_requests:
            conflicts = ', '.join(f'{row.college_id}/{row.fiscal_year} ({row.n})' for row in duplicate_requests)
            raise RuntimeError('EO request uniqueness migration blocked; resolve duplicate requests first: ' + conflicts)
        request_constraints = {
            item['name'] for item in inspect(db.engine).get_unique_constraints('ppmp_submission_requests')
        }
        if 'uq_ppmp_request_office_year' not in request_constraints:
            db.session.execute(text(
                'ALTER TABLE ppmp_submission_requests ADD CONSTRAINT uq_ppmp_request_office_year '
                'UNIQUE (college_id, fiscal_year)'
            ))
            db.session.commit()
        comment_foreign_keys = {
            tuple(item.get('constrained_columns') or ())
            for item in inspect(db.engine).get_foreign_keys('ppmp_comments')
        }
        for column_name, target, constraint_name in (
            ('ppmp_record_id', 'ppmp_records(id)', 'fk_comment_ppmp_record'),
            ('ppmp_record_item_id', 'ppmp_record_items(id)', 'fk_comment_ppmp_record_item'),
            ('wishlist_order_id', 'ppmp_orders(id)', 'fk_comment_wishlist_order'),
        ):
            if (column_name,) not in comment_foreign_keys:
                db.session.execute(text(
                    f'ALTER TABLE ppmp_comments ADD CONSTRAINT {constraint_name} '
                    f'FOREIGN KEY ({column_name}) REFERENCES {target} ON DELETE CASCADE'
                ))
        order_item_foreign_keys = {
            tuple(item.get('constrained_columns') or ())
            for item in inspect(db.engine).get_foreign_keys('ppmp_order_items')
        }
        if ('master_item_id',) not in order_item_foreign_keys:
            db.session.execute(text(
                'ALTER TABLE ppmp_order_items ADD CONSTRAINT fk_order_item_master '
                'FOREIGN KEY (master_item_id) REFERENCES wishlist_items(id) ON DELETE RESTRICT'
            ))
        source_check = next((
            item for item in inspect(db.engine).get_check_constraints('ppmp_order_items')
            if item.get('name') == 'ck_ppmp_order_item_source'
        ), None)
        if source_check and 'master_item_id' not in str(source_check.get('sqltext') or ''):
            db.session.execute(text(
                'ALTER TABLE ppmp_order_items DROP CONSTRAINT ck_ppmp_order_item_source'
            ))
            source_check = None
        if source_check is None:
            db.session.execute(text(
                'ALTER TABLE ppmp_order_items ADD CONSTRAINT ck_ppmp_order_item_source CHECK ('
                '(is_custom_item IS TRUE AND master_item_id IS NULL AND wishlist_item_id IS NULL) OR '
                '(is_custom_item IS FALSE AND ('
                '(master_item_id IS NOT NULL AND wishlist_item_id IS NULL AND legacy_wishlist_item_id IS NULL) OR '
                '(master_item_id IS NULL AND wishlist_item_id IS NOT NULL AND legacy_wishlist_item_id IS NULL) OR '
                '(master_item_id IS NULL AND wishlist_item_id IS NULL AND legacy_wishlist_item_id IS NOT NULL))))'
            ))
        db.session.commit()
    archive_legacy_franz_account()
    migrate_legacy_ppmp_records()
    migrate_legacy_wishlist_orders()
    if db.engine.dialect.name in {'mysql', 'postgresql'}:
        duplicate_records = db.session.execute(text(
            'SELECT office_id, fiscal_year, COUNT(*) AS n FROM ppmp_records '
            'GROUP BY office_id, fiscal_year HAVING COUNT(*) > 1'
        )).all()
        if duplicate_records:
            conflicts = ', '.join(
                f'{row.office_id}/{row.fiscal_year} ({row.n})' for row in duplicate_records
            )
            raise RuntimeError(
                'PPMP record uniqueness migration blocked; resolve duplicate office/year records first: '
                + conflicts
            )
        record_constraints = {
            item['name'] for item in inspect(db.engine).get_unique_constraints('ppmp_records')
        }
        if 'uq_ppmp_record_office_year' not in record_constraints:
            db.session.execute(text(
                'ALTER TABLE ppmp_records ADD CONSTRAINT uq_ppmp_record_office_year '
                'UNIQUE (office_id, fiscal_year)'
            ))
            db.session.commit()


def archive_legacy_franz_account():
    """Revoke the explicitly retired legacy account while preserving every linked row."""
    legacy = User.query.filter_by(username='franz', role='COLLEGE_ENCODER').one_or_none()
    if legacy is None:
        return False
    legacy.released_role = legacy.role
    legacy.role = None
    legacy.account_status = 'ARCHIVED'
    legacy.is_active = False
    legacy.auth_version = int(legacy.auth_version or 0) + 1
    db.session.add(WorkflowAuditLog(
        entity_type='account', entity_id=legacy.id, action='LEGACY_ACCOUNT_ARCHIVED',
        performed_by=None,
        details={
            'username': 'franz',
            'released_role': 'COLLEGE_ENCODER',
            'reason': 'System Quality & Access Revision',
        },
    ))
    return True


def migrate_legacy_ppmp_records():
    """Represent each legacy PPMP item without inventing missing 12-column values."""
    status_mapping = {
        'Draft': 'Draft',
        'Submitted': 'Submitted',
        'EO Review': 'Under Review',
        'Procurement Review': 'Pending Admin Approval',
        'Returned': 'Returned',
        'Approved': 'Approved',
        'Rejected': 'Rejected',
    }
    status_priority = {
        'Draft': 0, 'Returned': 0, 'Rejected': 0, 'Submitted': 1,
        'Under Review': 2, 'Pending Admin Approval': 3, 'Approved': 4,
    }
    for legacy in PPMPItem.query.order_by(PPMPItem.id).all():
        if PPMPRecordItem.query.filter_by(legacy_ppmp_item_id=legacy.id).first():
            continue
        mapped_status = status_mapping.get(legacy.status, 'Returned')
        record = PPMPRecord.query.filter_by(
            office_id=legacy.college_id, fiscal_year=legacy.fiscal_year,
        ).first()
        if record is None:
            record = PPMPRecord(
                reference_number=f'LEGACY-PPMP-{legacy.college_id}-{legacy.fiscal_year}',
                office_id=legacy.college_id,
                fiscal_year=legacy.fiscal_year,
                status=mapped_status,
                prepared_by=legacy.created_by,
                approved_by=legacy.approved_by if mapped_status == 'Approved' else None,
                approved_at=legacy.approved_at if mapped_status == 'Approved' else None,
                submitted_at=legacy.created_at if legacy.status != 'Draft' else None,
                created_at=legacy.created_at or datetime.utcnow(),
            )
            db.session.add(record)
            db.session.flush()
        elif record.reference_number.startswith('LEGACY-PPMP-'):
            if status_priority.get(mapped_status, 0) < status_priority.get(record.status, 0):
                record.status = mapped_status
                if mapped_status != 'Approved':
                    record.approved_by = None
                    record.approved_at = None
        db.session.add(PPMPRecordItem(
            ppmp_record_id=record.id,
            general_description=legacy.item_description,
            project_type=legacy.procurement_type,
            quantity=legacy.quantity,
            unit_size=legacy.unit,
            procurement_method=legacy.mode_of_procurement,
            pre_procurement_conference=None,
            procurement_start=None,
            procurement_end=None,
            delivery_period=None,
            schedule_as_needed=None,
            source_of_funds=legacy.fund_source,
            estimated_budget=legacy.total_cost,
            supporting_documents=None,
            remarks=legacy.remarks,
            item_status='Included',
            created_by=legacy.created_by,
            ppmp_item_id=legacy.id if legacy.status == 'Approved' else None,
            legacy_ppmp_item_id=legacy.id,
            created_at=legacy.created_at or datetime.utcnow(),
        ))


def migrate_legacy_wishlist_orders():
    """Preserve each legacy single-item Wishlist request as a new PPMP order exactly once."""
    status_mapping = {
        'Requested': 'Pending Admin Approval',
        'Pending Admin Approval': 'Pending Admin Approval',
        'Approved': 'Approved',
        'Rejected': 'Rejected',
        'Returned': 'Returned',
        'Processing': 'Processing',
        'Completed': 'Completed',
    }
    for legacy in WishlistRequest.query.order_by(WishlistRequest.id).all():
        if PPMPOrder.query.filter_by(legacy_wishlist_request_id=legacy.id).first():
            continue
        item = legacy.item
        if item is None:
            continue
        requester = legacy.requester
        order = PPMPOrder(
            reference_number=f'LEGACY-WR-{legacy.id:08d}',
            office_id=requester.college_id if requester else None,
            requested_by=legacy.requested_by,
            fiscal_year=(legacy.created_at or datetime.utcnow()).year,
            status=status_mapping.get(legacy.status, 'Returned'),
            remarks=legacy.remarks,
            admin_note=legacy.admin_note,
            decided_by=legacy.decided_by,
            decided_at=legacy.decided_at,
            submitted_at=legacy.created_at or datetime.utcnow(),
            created_at=legacy.created_at or datetime.utcnow(),
            legacy_wishlist_request_id=legacy.id,
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(PPMPOrderItem(
            order_id=order.id,
            legacy_wishlist_item_id=item.id,
            item_name=item.item_description,
            description=item.remarks,
            category=item.category,
            project_type=None,
            quantity=legacy.quantity,
            unit=item.unit,
            procurement_method=None,
            pre_procurement_conference=None,
            procurement_start=None,
            procurement_end=None,
            delivery_period=None,
            schedule_as_needed=None,
            source_of_funds=None,
            estimated_unit_cost=item.estimated_cost,
            estimated_budget=float(legacy.quantity or 0) * float(item.estimated_cost or 0),
            supporting_documents=None,
            remarks=legacy.remarks,
            created_by=legacy.requested_by,
            is_custom_item=True,
            created_at=legacy.created_at or datetime.utcnow(),
        ))
    db.session.commit()


def parse_item_data(data, college):
    return {
        "college_id": college.id,
        "item_description": data.get("item_description", "").strip(),
        "unit": data.get("unit", "").strip(),
        "quantity": float(data.get("quantity", 0)),
        "unit_cost": float(data.get("unit_cost", 0)),
        "fund_source": data.get("fund_source", ""),
        "mode_of_procurement": data.get("mode_of_procurement", ""),
        "procurement_type": data.get("procurement_type", "Goods"),
        "quarter": data.get("quarter") or None,
        "remarks": data.get("remarks", "").strip() or None,
        "status": "Draft",
    }


def can_access_ppmp(user, item):
    if user.role in {'ADMIN', 'EO', 'PROCUREMENT', 'BUDGET'}:
        return True
    return item.created_by == user.id or (user.college_id and item.college_id == user.college_id)


@app.route("/")
def index():
    if "user_id" not in session:
        return render_template("login.html")
    return render_template(
        "index.html", is_admin=session.get("role") == "ADMIN", current_role=session.get("role"),
        websocket_url=os.getenv('WEBSOCKET_URL', '').strip(),
    )


def username_account_ids(username):
    """Compare legacy usernames consistently across supported database collations."""
    lookup = format_username(username).casefold()
    return [user_id for user_id, stored_username in db.session.query(User.id, User.username).all()
            if format_username(stored_username).casefold() == lookup]


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    submitted_username = data.get("username") or ""
    if not isinstance(submitted_username, str):
        return jsonify({"error": "Username and password are required."}), 400
    username = submitted_username.strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400
    candidate_ids = username_account_ids(username)
    candidates = User.query.filter(User.id.in_(candidate_ids)).all() if candidate_ids else []
    matches = [candidate for candidate in candidates if check_password_hash(candidate.password_hash, password)]
    # Submitted casing is formatted by the UI and cannot identify a legacy
    # case-only collision. Never select arbitrarily between matching credentials.
    if len(matches) != 1:
        return jsonify({"error": "Invalid username or password."}), 401
    user = matches[0]
    if user.account_status == 'PENDING':
        audit('account', user.id, 'LOGIN_BLOCKED_PENDING_APPROVAL', {'result': 'blocked'})
        db.session.commit()
        return jsonify({
            'error': 'Your account is waiting for Administrator approval.',
            'code': 'ACCOUNT_PENDING', 'account_status': 'PENDING',
        }), 403
    if user.account_status == 'REJECTED':
        audit('account', user.id, 'LOGIN_BLOCKED_REJECTED', {'result': 'blocked'})
        db.session.commit()
        return jsonify({
            'error': 'Your registration has not been approved. Please contact the System Administrator.',
            'code': 'ACCOUNT_REJECTED', 'account_status': 'REJECTED',
        }), 403
    if not user.is_active or user.account_status != 'ACTIVE':
        audit('account', user.id, 'LOGIN_BLOCKED_ACCOUNT_STATUS', {'status': user.account_status})
        db.session.commit()
        return jsonify({
            'error': 'This account is not active. Please contact the System Administrator.',
            'code': 'ACCOUNT_INACTIVE', 'account_status': user.account_status,
        }), 403
    session.clear()
    session["user_id"] = user.id
    session["username"] = format_username(user.username)
    session["role"] = user.role
    session['auth_version'] = int(user.auth_version or 0)
    session.permanent = bool(data.get("remember_me"))
    login_time = datetime.utcnow()
    user.last_login = login_time
    activity = UserActivityLog(user_id=user.id, time_in=login_time)
    db.session.add(activity)
    db.session.flush()
    session['activity_log_id'] = activity.id
    audit('account', user.id, 'LOGIN', {'result': 'success'})
    db.session.commit()
    return jsonify({"user": user.to_dict(), "permissions": sorted(permissions_for(user))})


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    submitted_username = data.get("username") or ""
    if not isinstance(submitted_username, str):
        return jsonify({'error': 'Enter a valid username.'}), 400
    username = format_username(submitted_username.strip())
    password = data.get("password") or ""
    password_confirmation = data.get('password_confirmation') or ''
    role = (data.get('role') or '').strip().upper()
    office = (data.get('office') or '').strip().upper()
    if not all((first_name, last_name, email, username, password, password_confirmation, role, office)):
        return jsonify({"error": "Complete all required registration fields."}), 400
    if len(username) > User.__table__.c.username.type.length:
        return jsonify({'error': 'Username must contain no more than 80 characters.'}), 400
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must contain at least 8 characters."}), 400
    if password != password_confirmation:
        return jsonify({'error': 'The password confirmation does not match.'}), 400
    if role == 'ADMIN' or role not in configured_roles():
        return jsonify({"error": "Administrator accounts must be created by an administrator."}), 403
    if office not in set(configured_offices()) | set(DEPARTMENT_CODES):
        return jsonify({'error': 'Select a valid office.'}), 400
    if role not in {'EO', 'PROCUREMENT', 'BUDGET', 'BAC CHAIRMAN'} and role != office:
        return jsonify({'error': 'The selected office role must match its office.'}), 400
    managed_office = College.query.filter_by(code=office, is_active=True).first()
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email address already exists.'}), 409
    if username_account_ids(username):
        return jsonify({'error': 'This username is already in use.'}), 409
    if User.query.filter_by(role=role).first():
        audit('account', 0, 'REGISTRATION_ROLE_UNAVAILABLE', {'role': role})
        db.session.commit()
        return jsonify({
            'error': 'The selected role already has an assigned or pending account. '
                     'Please contact the System Administrator.'
        }), 409
    full_name = " ".join(part for part in (first_name, middle_name, last_name) if part)
    user = User(username=username, full_name=full_name, email=email,
                password_hash=generate_password_hash(password), role=role, office=office,
                college_id=managed_office.id if managed_office else None,
                account_status='PENDING', is_active=False)
    db.session.add(user)
    try:
        db.session.flush()  # the unique role/email indexes arbitrate concurrent requests
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'This email or role was reserved by another registration. Only one account is permitted per role.'}), 409
    for admin in User.query.filter_by(role="ADMIN", is_active=True).all():
        db.session.add(PPMPNotification(
            recipient_id=admin.id, type="info", title="New account awaiting approval",
            message=f"{full_name} registered and needs an office and workflow role assignment.",
            target_type='account', target_id=user.id, action_stage='PENDING',
        ))
    audit('account', user.id, 'ACCOUNT_REGISTERED', {'role': role, 'office': office, 'result': 'pending'})
    audit('account', user.id, 'ROLE_RESERVED', {'role': role})
    db.session.commit()
    return jsonify({
        'message': 'Your account has been submitted for Administrator approval.',
        'account_status': 'PENDING',
        'registration_token': create_registration_token(user),
    }), 201


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    user_id = session.get('user_id')
    if user_id:
        activity_id = session.get('activity_log_id')
        if activity_id:
            activity = UserActivityLog.query.filter_by(
                id=activity_id, user_id=user_id, time_out=None,
            ).one_or_none()
            if activity:
                activity.time_out = datetime.utcnow()
        audit('account', user_id, 'LOGOUT', {'result': 'success'})
        db.session.commit()
    session.clear()
    return jsonify({"success": True})


@app.route("/api/auth/me")
def current_user():
    user_id = session.get("user_id")
    user = db.session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        session.clear()
        return jsonify({"error": "Authentication required."}), 401
    return jsonify({"user": user.to_dict(), "permissions": sorted(permissions_for(user))})


@app.route('/api/activity-log')
@login_required
def activity_log():
    records = UserActivityLog.query.filter_by(
        user_id=current_session_user().id,
    ).order_by(UserActivityLog.time_in.desc()).all()
    return jsonify([record.to_dict() for record in records])


@app.route('/api/admin/activity-log')
@admin_required
def admin_activity_log_tracker():
    offices = list(configured_offices())
    office = (request.args.get('office') or '').strip()
    if not office:
        return jsonify({'offices': offices, 'records': [], 'other_activities': []})
    if office not in offices:
        return jsonify({'error': 'Select a valid office.'}), 400

    records = (UserActivityLog.query
               .join(User, User.id == UserActivityLog.user_id)
               .filter(User.office == office)
               .order_by(UserActivityLog.time_in.desc()).all())
    result = []
    for record in records:
        login_time = record._philippine_time(record.time_in)
        logout_time = record._philippine_time(record.time_out)
        result.append({
            'user': record.user.full_name or format_username(record.user.username),
            'login_month': login_time.strftime('%B'),
            'login_day': login_time.strftime('%d'),
            'login_year': login_time.strftime('%Y'),
            'login_time': login_time.strftime('%I:%M:%S %p'),
            'logout_month': logout_time.strftime('%B') if logout_time else '',
            'logout_day': logout_time.strftime('%d') if logout_time else '',
            'logout_year': logout_time.strftime('%Y') if logout_time else '',
            'logout_time': logout_time.strftime('%I:%M:%S %p') if logout_time else '',
        })
    activities = (WorkflowAuditLog.query
                  .join(User, User.id == WorkflowAuditLog.performed_by)
                  .filter(User.office == office,
                          ~WorkflowAuditLog.action.in_(('LOGIN', 'LOGOUT')))
                  .order_by(WorkflowAuditLog.created_at.desc()).all())
    other_activities = []
    for activity in activities:
        activity_time = UserActivityLog._philippine_time(activity.created_at)
        other_activities.append({
            'date': activity_time.strftime('%B %d, %Y') if activity_time else '',
            'activity': activity.action.replace('_', ' ').title(),
        })
    return jsonify({'offices': offices, 'records': result, 'other_activities': other_activities})


@app.route('/api/auth/available-roles')
def available_roles():
    occupied = {role for (role,) in db.session.query(User.role).filter(User.role.isnot(None)).all()}
    roles = [role for role in configured_roles() if role != 'ADMIN' and role not in occupied]
    role_options = [
        {'name': role, 'available': role not in occupied}
        for role in configured_roles() if role != 'ADMIN'
    ]
    offices = sorted(set(configured_offices()) | set(DEPARTMENT_CODES))
    return jsonify({'roles': roles, 'role_options': role_options, 'offices': offices})


@app.route('/api/auth/registration-status', methods=['POST'])
def registration_status():
    data = request.get_json(silent=True) or {}
    token = (data.get('registration_token') or '').strip()
    remote_address = request.remote_addr or 'unknown'
    rate_key = hashlib.sha256(f'{remote_address}:{token[:24]}'.encode('utf-8')).hexdigest()
    if reset_rate_limited('registration_status', rate_key, 20, 900):
        return jsonify({'error': 'Too many status checks. Try again later.'}), 429
    if not token:
        return jsonify({'error': 'A valid registration reference is required.'}), 400
    try:
        payload = registration_serializer().loads(token, max_age=REGISTRATION_TOKEN_MAX_AGE)
    except SignatureExpired:
        return jsonify({'error': 'This registration reference has expired. Please contact the Administrator.'}), 400
    except BadSignature:
        return jsonify({'error': 'This registration reference is invalid.'}), 400
    user = db.session.get(User, payload.get('registration'))
    fingerprint = hashlib.sha256(user.email.encode('utf-8')).hexdigest()[:16] if user else ''
    if user is None or not hmac.compare_digest(payload.get('fingerprint') or '', fingerprint):
        return jsonify({'error': 'This registration reference is invalid.'}), 400
    messages = {
        'PENDING': 'Your account is still waiting for Administrator approval.',
        'ACTIVE': 'Your account has been approved. You may now log in.',
        'REJECTED': 'Your registration was not approved. Please contact the Administrator.',
        'SUSPENDED': 'This account is suspended. Please contact the Administrator.',
        'ARCHIVED': 'This registration is no longer active. Please contact the Administrator.',
    }
    audit('account', user.id, 'ACCOUNT_STATUS_CHECKED', {'status': user.account_status})
    db.session.commit()
    return jsonify({
        'account_status': user.account_status,
        'message': messages.get(user.account_status, 'This account is not available for login.'),
    })


def password_reset_digest(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({'error': 'Enter a valid email address.'}), 400
    remote_address = request.remote_addr or 'unknown'
    rate_key = hashlib.sha256(f'{remote_address}:{email}'.encode('utf-8')).hexdigest()
    if reset_rate_limited('request', rate_key, 3, 3600):
        return jsonify({'message': PASSWORD_RESET_REQUEST_MESSAGE})
    return jsonify({'message': PASSWORD_RESET_REQUEST_MESSAGE})


@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    code = (data.get('code') or '').strip()
    password = data.get('password') or ''
    confirmation = data.get('password_confirmation') or ''
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not code:
        return jsonify({'error': 'Enter your email address and one-time reset code.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'The new password must contain at least 8 characters.'}), 400
    if password != confirmation:
        return jsonify({'error': 'The password confirmation does not match.'}), 400
    remote_address = request.remote_addr or 'unknown'
    if reset_rate_limited('verify', remote_address, 20, 900):
        return jsonify({'error': 'Too many reset attempts. Try again later.'}), 429

    user = User.query.filter_by(email=email, account_status='ACTIVE', is_active=True).first()
    reset_request = None
    if user:
        reset_request = PasswordResetRequest.query.filter_by(
            user_id=user.id, status='CODE_ISSUED').order_by(PasswordResetRequest.created_at.desc()).first()
    invalid_message = 'The reset code is invalid or expired. Request a new code if needed.'
    now = datetime.utcnow()
    if reset_request is None:
        return jsonify({'error': invalid_message}), 400
    if reset_request.expires_at is None or reset_request.expires_at <= now:
        reset_request.status = 'EXPIRED'
        db.session.commit()
        return jsonify({'error': invalid_message}), 400
    if not hmac.compare_digest(reset_request.token_hash or '', password_reset_digest(code)):
        reset_request.attempt_count += 1
        if reset_request.attempt_count >= 5:
            reset_request.status = 'EXPIRED'
        audit('password_reset', reset_request.id, 'CODE_REJECTED', {'attempts': reset_request.attempt_count})
        db.session.commit()
        return jsonify({'error': invalid_message}), 400
    if check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Choose a password different from the current password.'}), 400

    user.password_hash = generate_password_hash(password)
    user.auth_version = int(user.auth_version or 0) + 1
    reset_request.status = 'USED'
    reset_request.used_at = now
    reset_request.token_hash = None
    PasswordResetRequest.query.filter(
        PasswordResetRequest.user_id == user.id,
        PasswordResetRequest.id != reset_request.id,
        PasswordResetRequest.status.in_({'PENDING', 'CODE_ISSUED'}),
    ).update({'status': 'EXPIRED'}, synchronize_session=False)
    add_notification([user], 'Password changed', 'Your password was changed through the recovery process.', 'success')
    audit('password_reset', reset_request.id, 'COMPLETED', {'user_id': user.id})
    db.session.commit()
    session.clear()
    return jsonify({'message': 'Password updated. You can now sign in using your new password.'})


@app.route("/api/admin/pending-users")
@admin_required
def pending_users():
    users = User.query.filter_by(account_status='PENDING').order_by(User.created_at.asc()).all()
    return jsonify({"users": [user.to_dict() for user in users], "count": len(users)})


@app.route("/api/admin/pending-users/<int:user_id>/approve", methods=["POST"])
@admin_required
def approve_pending_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "Account not found."}), 404
    if user.is_active:
        return jsonify({"error": "This account has already been approved."}), 409
    data = request.get_json(silent=True) or {}
    if user.account_status != 'PENDING':
        return jsonify({'error': 'Only a pending account can be approved.'}), 409
    if user.role not in {'ADMIN', 'EO', 'AA', 'PROCUREMENT', 'BUDGET', 'BAC CHAIRMAN'}:
        office = db.session.get(College, user.college_id) if user.college_id else None
        if office is None:
            office = College.query.filter_by(code=user.office).first()
        if office is None and user.office in PPMP_OFFICE_ROLES and user.role == user.office:
            office = College(code=user.office, name=DEPARTMENT_UNITS.get(user.office, user.office), is_active=True)
            db.session.add(office)
            try:
                db.session.flush()
            except IntegrityError:
                db.session.rollback()
                office = College.query.filter_by(code=user.office, is_active=True).first()
        if office is None:
            return jsonify({'error': 'This account is not linked to a recognized operational office.'}), 409
        if not office.is_active:
            return jsonify({'error': 'This account is linked to an inactive operational office.'}), 409
        user.college_id = office.id
    user.account_status, user.is_active = 'ACTIVE', True
    resolve_notification_tasks('account', user.id)
    db.session.add(PPMPNotification(
        recipient_id=user.id, type="success", title="Account approved",
        message="Your account was approved by the System Administrator. Welcome to the ISU Procurement Management System.",
        target_type='profile', target_id=user.id,
    ))
    audit('account', user.id, 'ACCOUNT_APPROVED', {'role': user.role, 'office': user.office})
    db.session.commit()
    return jsonify({"user": user.to_dict(), "message": "Account approved."})


@app.route('/api/admin/users/<int:user_id>/status', methods=['POST'])
@admin_required
def change_user_status(user_id):
    user = db.session.get(User, user_id)
    if user is None or user.role == 'ADMIN':
        return jsonify({'error': 'Account not found or protected.'}), 404
    data = request.get_json(silent=True) or {}
    status = (data.get('status') or '').upper()
    if status not in {'SUSPENDED', 'ARCHIVED', 'REJECTED'}:
        return jsonify({'error': 'Select a valid account status.'}), 400
    old_role = user.role
    user.account_status, user.is_active = status, False
    resolve_notification_tasks('account', user.id)
    if status in {'ARCHIVED', 'REJECTED'}:
        user.released_role, user.role = old_role, None
    audit('account', user.id, 'ROLE_RELEASE' if user.role is None else 'STATUS_CHANGE',
          {'status': status, 'released_role': old_role})
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route("/api/colleges")
def get_colleges():
    colleges = College.query.filter_by(is_active=True).order_by(College.code).all()
    return jsonify([college.to_dict() for college in colleges])


@app.route("/api/metadata")
def get_metadata():
    return jsonify({"fund_sources": FUND_SOURCES, "modes_of_procurement": MODES_OF_PROCUREMENT,
                    "procurement_types": PROCUREMENT_TYPES, "quarters": QUARTERS, "statuses": STATUSES,
                    "ppmp_order_categories": PPMP_ORDER_CATEGORIES,
                    "ppmp_order_fund_sources": PPMP_ORDER_FUND_SOURCES,
                    "ppmp_order_types": PPMP_ORDER_TYPES,
                    "project_types": PPMPRecordItem.PROJECT_TYPES,
                    "pre_procurement_options": ('Yes', 'No'),
                    "offices": configured_offices(), "roles": configured_roles()})


@app.route("/api/ppmp", methods=["GET"])
def list_ppmp():
    items = get_ppmp_items(
        college_id=request.args.get("college_id", type=int), status=request.args.get("status") or None,
        fund_source=request.args.get("fund_source") or None, procurement_type=request.args.get("procurement_type") or None,
        quarter=request.args.get("quarter") or None, search=request.args.get("search") or None,
    )
    user = current_session_user()
    return jsonify([item.to_dict() for item in items if can_access_ppmp(user, item)])


@app.route("/api/ppmp", methods=["POST"])
@permission_required('ppmp.create')
def add_ppmp():
    data = request.get_json(silent=True) or {}
    college = db.session.get(College, data.get("college_id"))
    if college is None or not college.is_active:
        return jsonify({"error": "A valid active college is required."}), 400
    user = current_session_user()
    if user.role != 'ADMIN' and user.college_id != college.id:
        return jsonify({'error': 'You are not authorized to create PPMP for this college.'}), 403
    try:
        item = PPMPItem(**parse_item_data(data, college), created_by=user.id)
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity and unit cost must be valid numbers."}), 400
    if not item.item_description or not item.unit:
        return jsonify({"error": "Item description and unit are required."}), 400
    db.session.add(item)
    db.session.flush()
    audit("ppmp_item", item.id, "CREATE")
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route("/api/ppmp/<int:item_id>", methods=["PUT"])
@permission_required('ppmp.edit')
def update_ppmp(item_id):
    item = db.session.get(PPMPItem, item_id)
    if item is None:
        return jsonify({"error": "Not found"}), 404
    user = current_session_user()
    if not can_access_ppmp(user, item):
        return jsonify({'error': 'You are not authorized to access this PPMP.'}), 403
    if user.role != "ADMIN" and (item.created_by != user.id or item.status not in {"Draft", "Returned"}):
        return jsonify({"error": "Only the creating office user can edit a draft or returned PPMP item."}), 403
    data = request.get_json(silent=True) or {}
    if "college_id" in data:
        college = db.session.get(College, data["college_id"])
        if college is None or not college.is_active:
            return jsonify({"error": "A valid active college is required."}), 400
        item.college_id = college.id
    for field in ("item_description", "unit", "fund_source", "mode_of_procurement", "procurement_type", "quarter", "remarks"):
        if field in data:
            setattr(item, field, (data[field] or None) if field in {"quarter", "remarks"} else data[field])
    try:
        for field in ("quantity", "unit_cost"):
            if field in data:
                setattr(item, field, float(data[field]))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity and unit cost must be valid numbers."}), 400
    audit("ppmp_item", item.id, "UPDATE")
    db.session.commit()
    return jsonify(item.to_dict())


@app.route("/api/ppmp/<int:item_id>", methods=["DELETE"])
@permission_required('ppmp.edit')
def delete_ppmp(item_id):
    item = db.session.get(PPMPItem, item_id)
    if item is None:
        return jsonify({"error": "Not found"}), 404
    user = current_session_user()
    if not can_access_ppmp(user, item):
        return jsonify({'error': 'You are not authorized to access this PPMP.'}), 403
    if user.role != "ADMIN" and (item.created_by != user.id or item.status not in {"Draft", "Returned"}):
        return jsonify({"error": "Only the creating office user can delete a draft or returned PPMP item."}), 403
    audit("ppmp_item", item.id, "DELETE")
    db.session.delete(item)
    db.session.commit()
    return jsonify({"deleted": item_id})


@app.route("/api/ppmp/<int:item_id>/transition", methods=["POST"])
@login_required
def transition_ppmp(item_id):
    item = db.session.get(PPMPItem, item_id)
    if item is None:
        return jsonify({"error": "PPMP item not found."}), 404
    user, data = current_session_user(), request.get_json(silent=True) or {}
    if not can_access_ppmp(user, item):
        return jsonify({'error': 'You are not authorized to access this PPMP.'}), 403
    action, note = data.get("action"), (data.get("note") or "").strip()
    if action in {'return', 'reject'} and not note:
        return jsonify({'error': 'A reason is required when returning or rejecting a PPMP item.'}), 400
    transitions = {
        ('office', 'Draft', 'submit'): 'Submitted',
        ('office', 'Returned', 'submit'): 'Submitted',
        ('EO', 'Submitted', 'approve'): 'EO Review',
        ('EO', 'Submitted', 'return'): 'Returned',
        ('EO', 'Submitted', 'reject'): 'Rejected',
        ('PROCUREMENT', 'EO Review', 'approve'): 'Procurement Review',
        ('PROCUREMENT', 'EO Review', 'return'): 'Returned',
        ('PROCUREMENT', 'EO Review', 'reject'): 'Rejected',
        ('ADMIN', 'Procurement Review', 'approve'): 'Approved',
        ('ADMIN', 'Procurement Review', 'return'): 'Returned',
        ('ADMIN', 'Procurement Review', 'reject'): 'Rejected',
    }
    actor = 'office' if is_ppmp_office_role(user.role) else user.role
    target = transitions.get((actor, item.status, action))
    if target is None or (actor == 'office' and item.created_by != user.id):
        return jsonify({"error": "This PPMP transition is not allowed."}), 409
    previous = item.status
    resolve_notification_tasks('ppmp_item', item.id)
    item.status = target
    if target == "Approved":
        item.approved_by, item.approved_at = user.id, datetime.utcnow()
    if note:
        db.session.add(PPMPComment(ppmp_item_id=item.id, author_id=user.id, message=note))
    audit("ppmp_item", item.id, action.upper(), {"from": previous, "to": target})
    if target == "Submitted":
        request_record = PPMPSubmissionRequest.query.filter_by(college_id=item.college_id, fiscal_year=item.fiscal_year, status="Requested").first()
        if request_record:
            request_record.status, request_record.submitted_at = "Submitted", datetime.utcnow()
        notify_roles(("EO",), "PPMP submitted", f"A PPMP item from {item.college.code} is ready for EO review.", "info", item.id, action_stage='EO')
    elif target == 'EO Review':
        notify_roles(('PROCUREMENT',), 'PPMP ready for Procurement review', f'PPMP item {item.id} requires review.', 'info', item.id, action_stage='PROCUREMENT')
    elif target == 'Procurement Review':
        notify_roles(('ADMIN',), 'PPMP pending final approval', f'PPMP item {item.id} requires final approval.', 'info', item.id, action_stage='ADMIN')
    notify_offices({item.college_id}, f'PPMP item {target.lower()}',
                   f'{item.item_description} (FY {item.fiscal_year}) is now {target}.' + (f' Review note: {note}' if note else ''),
                   'success' if target == 'Approved' else 'warning' if target in {'Returned', 'Rejected'} else 'info',
                   extra_recipients=[item.creator])
    db.session.commit()
    return jsonify(item.to_dict())


@app.route("/api/ppmp/<int:item_id>/comments", methods=["GET", "POST"])
def ppmp_comments(item_id):
    item = db.session.get(PPMPItem, item_id)
    if item is None:
        return jsonify({"error": "PPMP item not found."}), 404
    user = current_session_user()
    if not can_access_ppmp(user, item):
        return jsonify({'error': 'You are not authorized to access this PPMP.'}), 403
    if request.method == "GET":
        return jsonify([comment.to_dict() for comment in PPMPComment.query.filter_by(ppmp_item_id=item_id).order_by(PPMPComment.created_at.asc())])
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not has_permission(user, 'ppmp.comment') or not message:
        return jsonify({"error": "A comment message is required."}), 400
    comment = PPMPComment(ppmp_item_id=item_id, author_id=user.id, message=message)
    db.session.add(comment)
    audit("ppmp_item", item_id, "COMMENT")
    db.session.commit()
    return jsonify(comment.to_dict()), 201


def is_legacy_ppmp_document(record):
    return bool(record and record.reference_number.startswith('LEGACY-PPMP-') and record.source_order_id is None)


def is_deleted_legacy_ppmp_record(record):
    return bool(is_legacy_ppmp_document(record) and WorkflowAuditLog.query.filter_by(
        entity_type='ppmp_record', entity_id=record.id, action='PPMP_LEGACY_DOCUMENT_DELETED',
    ).first())


def visible_ppmp_records():
    deleted_ids = db.session.query(WorkflowAuditLog.entity_id).filter(
        WorkflowAuditLog.entity_type == 'ppmp_record',
        WorkflowAuditLog.action == 'PPMP_LEGACY_DOCUMENT_DELETED',
    )
    return PPMPRecord.query.filter(~PPMPRecord.id.in_(deleted_ids))


def can_delete_legacy_ppmp_record(user, record):
    return bool(
        user and user.is_active and user.account_status == 'ACTIVE'
        and has_permission(user, 'ppmp.record.edit') and is_legacy_ppmp_document(record)
        and (user.role == 'ADMIN' or (
            is_ppmp_office_role(user.role) and user.college_id == record.office_id
            and record.prepared_by == user.id and has_permission(user, 'ppmp.record.create')
        ))
    )


def can_access_ppmp_record(user, record):
    if user is None or is_deleted_legacy_ppmp_record(record):
        return False
    if user.role in {'ADMIN', 'EO', 'AA', 'PROCUREMENT', 'BUDGET'}:
        return True
    return bool(user.college_id and user.college_id == record.office_id)


def can_edit_ppmp_record(user, record):
    if is_deleted_legacy_ppmp_record(record):
        return False
    if record.source_order_id:
        return bool(user and (user.role == 'ADMIN' or (
            user.college_id == record.office_id and record.prepared_by == user.id
        )))
    return (
        is_ppmp_office_role(user.role)
        and user.college_id == record.office_id
        and record.prepared_by == user.id
        and record.status in {'Draft', 'Returned'}
    )


def can_delete_ppmp_record(user, record):
    """Remove legacy display documents, or the preparer's independent unused draft."""
    if is_legacy_ppmp_document(record):
        return can_delete_legacy_ppmp_record(user, record) and not is_deleted_legacy_ppmp_record(record)
    if (user is None or not user.is_active or user.account_status != 'ACTIVE'
            or not has_permission(user, 'ppmp.record.create')
            or not has_permission(user, 'ppmp.record.edit')
            or not can_edit_ppmp_record(user, record)
            or record.status != 'Draft' or record.submitted_at is not None
            or record.submission_request_id is not None
            or record.reviewed_by is not None or record.reviewed_at is not None
            or record.approved_by is not None or record.approved_at is not None
            or record.decision_note):
        return False
    if PPMPRecordItem.query.filter(
        PPMPRecordItem.ppmp_record_id == record.id,
        or_(PPMPRecordItem.ppmp_item_id.isnot(None), PPMPRecordItem.legacy_ppmp_item_id.isnot(None)),
    ).first():
        return False
    if PPMPOrderItem.query.join(
        PPMPRecordItem, PPMPOrderItem.wishlist_item_id == PPMPRecordItem.id,
    ).filter(PPMPRecordItem.ppmp_record_id == record.id).first():
        return False
    if PPMPComment.query.outerjoin(
        PPMPRecordItem, PPMPComment.ppmp_record_item_id == PPMPRecordItem.id,
    ).filter(or_(
        PPMPComment.ppmp_record_id == record.id,
        PPMPRecordItem.ppmp_record_id == record.id,
    )).first():
        return False
    if WorkflowAuditLog.query.filter(
        WorkflowAuditLog.entity_type == 'ppmp_record',
        WorkflowAuditLog.entity_id == record.id,
        WorkflowAuditLog.created_at >= record.created_at,
        WorkflowAuditLog.action.notin_(('PPMP_DRAFT_CREATED', 'PPMP_DRAFT_SAVED')),
    ).first():
        return False
    return True


def parse_month_value(value, field_label):
    value = str(value or '').strip()
    for pattern in ('%Y-%m', '%Y-%m-%d'):
        try:
            parsed = datetime.strptime(value, pattern).date()
            return parsed.replace(day=1)
        except ValueError:
            continue
    raise ValueError(f'{field_label} must be a valid month.')


def parse_controlled_boolean(value, field_label):
    if value in {True, 1, '1', 'Yes', 'yes', 'YES'}:
        return True
    if value in {False, 0, '0', 'No', 'no', 'NO'}:
        return False
    raise ValueError(f'{field_label} must be Yes or No.')


def parse_ppmp_record_item(data):
    description = str(data.get('general_description') or '').strip()
    project_type = str(data.get('project_type') or '').strip()
    unit_size = str(data.get('unit_size') or '').strip()
    method = str(data.get('procurement_method') or '').strip()
    source = str(data.get('source_of_funds') or '').strip()
    supporting_documents = str(data.get('supporting_documents') or '').strip() or None
    remarks = str(data.get('remarks') or '').strip() or None
    if not description or len(description) > 3000:
        raise ValueError('General description is required and must not exceed 3,000 characters.')
    if project_type not in PPMPRecordItem.PROJECT_TYPES:
        raise ValueError('Select a valid project type.')
    if not unit_size or len(unit_size) > 80:
        raise ValueError('Quantity unit/size is required and must not exceed 80 characters.')
    if method not in MODES_OF_PROCUREMENT:
        raise ValueError('Select a valid recommended mode of procurement.')
    if source not in PPMPRecordItem.FUND_SOURCES:
        raise ValueError('Select a valid source of funds.')
    if supporting_documents and len(supporting_documents) > 5000:
        raise ValueError('Supporting-document information must not exceed 5,000 characters.')
    if remarks and len(remarks) > 5000:
        raise ValueError('Remarks must not exceed 5,000 characters.')
    try:
        quantity = Decimal(str(data.get('quantity')))
        budget = Decimal(str(data.get('estimated_budget'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Quantity and estimated budget must be valid numbers.')
    if quantity <= 0:
        raise ValueError('Quantity must be greater than zero.')
    if budget < 0:
        raise ValueError('Estimated budget cannot be negative.')
    pre_procurement = parse_controlled_boolean(
        data.get('pre_procurement_conference'), 'Pre-procurement conference',
    )
    schedule_as_needed = parse_controlled_boolean(
        data.get('schedule_as_needed', False), 'Schedule as needed',
    )
    if schedule_as_needed:
        procurement_start = procurement_end = delivery_period = None
    else:
        procurement_start = parse_month_value(data.get('procurement_start'), 'Procurement start')
        procurement_end = parse_month_value(data.get('procurement_end'), 'Procurement end')
        delivery_period = parse_month_value(data.get('delivery_period'), 'Delivery/implementation period')
        if procurement_end < procurement_start:
            raise ValueError('Procurement end cannot be earlier than procurement start.')
        if delivery_period < procurement_end:
            raise ValueError('Expected delivery cannot be earlier than procurement end.')
    return {
        'general_description': description,
        'project_type': project_type,
        'quantity': quantity,
        'unit_size': unit_size,
        'procurement_method': method,
        'pre_procurement_conference': pre_procurement,
        'procurement_start': procurement_start,
        'procurement_end': procurement_end,
        'delivery_period': delivery_period,
        'schedule_as_needed': schedule_as_needed,
        'source_of_funds': source,
        'estimated_budget': budget,
        'supporting_documents': supporting_documents,
        'remarks': remarks,
        'item_status': 'Included',
    }


def validate_ppmp_record_for_submission(record):
    items = record.included_items
    if not items:
        return 'Add at least one PPMP Wishlist item before submitting.'
    for index, item in enumerate(items, 1):
        if (not item.general_description or item.project_type not in PPMPRecordItem.PROJECT_TYPES
                or not item.unit_size or item.procurement_method not in MODES_OF_PROCUREMENT
                or item.pre_procurement_conference is None
                or item.source_of_funds not in PPMPRecordItem.FUND_SOURCES
                or Decimal(item.quantity or 0) <= 0 or Decimal(item.estimated_budget or 0) < 0):
            return f'Wishlist row {index} is incomplete or contains an invalid controlled value.'
        if not item.schedule_as_needed:
            if not item.procurement_start or not item.procurement_end or not item.delivery_period:
                return f'Wishlist row {index} requires start, end, and delivery months.'
            if item.procurement_end < item.procurement_start or item.delivery_period < item.procurement_end:
                return f'Wishlist row {index} contains an invalid procurement timeline.'
    return None


def record_quarter(record_item):
    if not record_item.procurement_start:
        return None
    return QUARTERS[(record_item.procurement_start.month - 1) // 3]


def materialize_approved_ppmp_record(record, approver):
    """Create the existing consolidation sources once, retaining exact authorized budgets."""
    materialized = 0
    for source in record.included_items:
        if source.ppmp_item_id:
            continue
        if source.legacy_ppmp_item_id:
            item = db.session.get(PPMPItem, source.legacy_ppmp_item_id)
            if item is None:
                continue
            item.status = 'Approved'
            item.approved_by = approver.id
            item.approved_at = record.approved_at
            item.authorized_budget = source.estimated_budget
        else:
            quantity = Decimal(source.quantity)
            unit_cost = (Decimal(source.estimated_budget) / quantity).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
            item = PPMPItem(
                college_id=record.office_id,
                fiscal_year=record.fiscal_year,
                item_description=source.general_description,
                unit=source.unit_size,
                quantity=source.quantity,
                unit_cost=unit_cost,
                authorized_budget=source.estimated_budget,
                fund_source=source.source_of_funds,
                mode_of_procurement=source.procurement_method,
                procurement_type=source.project_type,
                quarter=record_quarter(source),
                remarks=source.remarks,
                status='Approved',
                created_by=record.prepared_by,
                approved_by=approver.id,
                approved_at=record.approved_at,
            )
            db.session.add(item)
            db.session.flush()
        source.ppmp_item_id = item.id
        materialized += 1
    return materialized


def ppmp_record_response(record):
    result = record.to_dict()
    result['can_delete'] = can_delete_ppmp_record(current_session_user(), record)
    result['comments'] = [
        comment.to_dict() for comment in PPMPComment.query.filter_by(ppmp_record_id=record.id)
        .order_by(PPMPComment.created_at.asc()).all()
    ]
    return result


@app.route('/api/ppmp-records', methods=['GET', 'POST'])
def ppmp_records():
    user = current_session_user()
    if request.method == 'GET':
        if not has_permission(user, 'ppmp.record.view'):
            return jsonify({'error': 'You do not have permission to view PPMP records.'}), 403
        query = visible_ppmp_records()
        if is_ppmp_office_role(user.role):
            if not user.college_id:
                return jsonify([])
            query = query.filter_by(office_id=user.college_id)
        status = (request.args.get('status') or '').strip()
        if status in PPMPRecord.STATUSES:
            query = query.filter_by(status=status)
        return jsonify([
            ppmp_record_response(record)
            for record in query.order_by(PPMPRecord.created_at.desc()).all()
        ])

    if not has_permission(user, 'ppmp.record.create') or not is_ppmp_office_role(user.role):
        return jsonify({'error': 'Only an approved office PPMP user can create a PPMP record.'}), 403
    office = db.session.get(College, user.college_id) if user.college_id else None
    if office is None or not office.is_active:
        return jsonify({'error': 'Your account must be linked to an active office.'}), 409
    data = request.get_json(silent=True) or {}
    raw_fiscal_year = data.get('fiscal_year')
    try:
        fiscal_year = int(raw_fiscal_year)
    except (TypeError, ValueError, OverflowError):
        return jsonify({'error': 'A valid fiscal year is required.'}), 400
    if isinstance(raw_fiscal_year, bool) or (
        isinstance(raw_fiscal_year, float) and raw_fiscal_year != fiscal_year
    ):
        return jsonify({'error': 'A valid fiscal year is required.'}), 400
    if fiscal_year < 2026 or fiscal_year > 2100:
        return jsonify({'error': 'Fiscal year must be between 2026 and 2100.'}), 400
    if not PPMPOrder.query.filter_by(
        fiscal_year=fiscal_year, office_id=office.id, requested_by=user.id,
    ).first():
        return jsonify({'error': 'Choose a fiscal year from one of your existing PPMP requests.'}), 400
    submission_request = None
    raw_submission_request_id = data.get('submission_request_id')
    if raw_submission_request_id is not None and raw_submission_request_id != '':
        try:
            request_id = int(data['submission_request_id'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Select a valid EO PPMP request.'}), 400
        submission_request = db.session.get(PPMPSubmissionRequest, request_id)
        if (submission_request is None or submission_request.college_id != office.id
                or submission_request.fiscal_year != fiscal_year):
            return jsonify({'error': 'The selected EO request does not belong to your office and fiscal year.'}), 403
        if PPMPRecord.query.filter_by(submission_request_id=submission_request.id).first():
            return jsonify({'error': 'A PPMP record already exists for this EO request.'}), 409
    existing = PPMPRecord.query.filter_by(office_id=office.id, fiscal_year=fiscal_year).first()
    if existing:
        return jsonify({'error': f'{existing.reference_number} already covers this office and fiscal year.'}), 409
    now = datetime.utcnow()
    record = PPMPRecord(
        reference_number=f'PPMP-{fiscal_year}-{office.code}-{secrets.token_hex(3).upper()}',
        submission_request_id=submission_request.id if submission_request else None,
        office_id=office.id,
        fiscal_year=fiscal_year,
        status='Draft',
        prepared_by=user.id,
        created_at=now,
    )
    db.session.add(record)
    db.session.flush()
    if submission_request:
        submission_request.status = 'Draft'
    audit('ppmp_record', record.id, 'PPMP_DRAFT_CREATED', {
        'office_id': office.id, 'fiscal_year': fiscal_year,
        'submission_request_id': record.submission_request_id,
    })
    db.session.commit()
    return jsonify(ppmp_record_response(record)), 201


@app.route('/api/ppmp-records/<int:record_id>', methods=['GET', 'PUT'])
@login_required
def ppmp_record_detail(record_id):
    record = db.session.get(PPMPRecord, record_id)
    if record is None or is_deleted_legacy_ppmp_record(record):
        return jsonify({'error': 'PPMP record not found.'}), 404
    user = current_session_user()
    if not can_access_ppmp_record(user, record):
        return jsonify({'error': 'You cannot access another office\'s PPMP record.'}), 403
    if request.method == 'GET':
        return jsonify(ppmp_record_response(record))
    if not can_edit_ppmp_record(user, record):
        return jsonify({'error': 'Only the preparing office can edit a Draft or Returned PPMP.'}), 403
    audit('ppmp_record', record.id, 'PPMP_DRAFT_SAVED', {'status': record.status})
    db.session.commit()
    return jsonify(ppmp_record_response(record))


@app.route('/api/ppmp-records/<int:record_id>', methods=['DELETE'])
@permission_required('ppmp.record.edit')
def delete_ppmp_record(record_id):
    record = PPMPRecord.query.filter_by(id=record_id).with_for_update().one_or_none()
    if record is None:
        return jsonify({'error': 'PPMP record not found.'}), 404
    user = current_session_user()
    if not can_delete_legacy_ppmp_record(user, record) and not (
        is_ppmp_office_role(user.role)
        and user.college_id == record.office_id
        and record.prepared_by == user.id
        and has_permission(user, 'ppmp.record.create')
    ):
        return jsonify({'error': 'Only the preparing office PPMP user can delete this document.'}), 403
    data = request.get_json(silent=True)
    if (not isinstance(data, dict) or set(data) != {'reference_number'}
            or not isinstance(data.get('reference_number'), str)
            or not data['reference_number'].strip()):
        return jsonify({'error': 'Provide the confirmed PPMP document reference number.'}), 400
    if data['reference_number'] != record.reference_number:
        return jsonify({'error': 'This PPMP document has changed. Refresh the documents list before deleting.'}), 409
    if is_deleted_legacy_ppmp_record(record):
        return jsonify({'deleted': record_id, 'reference_number': record.reference_number, 'soft_deleted': True})
    PPMPRecordItem.query.filter_by(ppmp_record_id=record.id).order_by(
        PPMPRecordItem.id,
    ).with_for_update().all()
    if not can_delete_ppmp_record(user, record):
        return jsonify({
            'error': 'Only a never-submitted Draft PPMP document without linked requests, '
                     'procurement records, comments, or review history can be deleted.'
        }), 409
    reference_number = record.reference_number
    if is_legacy_ppmp_document(record):
        # Retain the historical source rows used by requests and APP snapshots;
        # the audit marker removes this display document persistently.
        audit('ppmp_record', record.id, 'PPMP_LEGACY_DOCUMENT_DELETED', {
            'reference_number': reference_number,
            'office_id': record.office_id, 'fiscal_year': record.fiscal_year,
            'item_count': len(record.items),
            'retained_source_item_ids': sorted({
                value for item in record.items
                for value in (item.ppmp_item_id, item.legacy_ppmp_item_id) if value is not None
            }),
        })
        resolve_notification_tasks('ppmp_record', record.id)
        db.session.commit()
        return jsonify({
            'deleted': record_id, 'reference_number': reference_number, 'soft_deleted': True,
            'message': 'Legacy PPMP document deleted. Original procurement records are retained.',
        })
    audit('ppmp_record', record.id, 'PPMP_DRAFT_DELETED', {
        'reference_number': reference_number,
        'office_id': record.office_id,
        'fiscal_year': record.fiscal_year,
        'item_count': len(record.items),
    })
    db.session.delete(record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'This PPMP document is linked to another record and cannot be deleted.'}), 409
    return jsonify({
        'deleted': record_id,
        'reference_number': reference_number,
        'message': 'Draft PPMP document deleted.',
    })


@app.route('/api/ppmp-records/<int:record_id>/items', methods=['POST'])
@login_required
def add_ppmp_record_item(record_id):
    record = db.session.get(PPMPRecord, record_id)
    user = current_session_user()
    if record is None:
        return jsonify({'error': 'PPMP record not found.'}), 404
    if not can_access_ppmp_record(user, record):
        return jsonify({'error': 'You cannot access another office\'s PPMP record.'}), 403
    if not can_edit_ppmp_record(user, record):
        return jsonify({'error': 'This PPMP record is not editable.'}), 409
    try:
        values = parse_ppmp_record_item(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    item = PPMPRecordItem(ppmp_record_id=record.id, created_by=user.id, **values)
    db.session.add(item)
    db.session.flush()
    audit('ppmp_record_item', item.id, 'PPMP_ITEM_ADDED', {'ppmp_record_id': record.id})
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route('/api/ppmp-records/<int:record_id>/items/<int:item_id>', methods=['PUT', 'DELETE'])
@login_required
def update_ppmp_record_item(record_id, item_id):
    record = db.session.get(PPMPRecord, record_id)
    item = db.session.get(PPMPRecordItem, item_id)
    user = current_session_user()
    if record is None or item is None or item.ppmp_record_id != record.id:
        return jsonify({'error': 'PPMP Wishlist item not found.'}), 404
    if not can_access_ppmp_record(user, record):
        return jsonify({'error': 'You cannot access another office\'s PPMP record.'}), 403
    if not can_edit_ppmp_record(user, record):
        return jsonify({'error': 'This PPMP record is not editable.'}), 409
    if request.method == 'DELETE':
        ordered = PPMPOrderItem.query.filter_by(wishlist_item_id=item.id).first()
        if ordered or item.ppmp_item_id:
            item.item_status = 'Removed'
        else:
            db.session.delete(item)
        audit('ppmp_record_item', item.id, 'PPMP_ITEM_REMOVED', {'ppmp_record_id': record.id})
        db.session.commit()
        return jsonify({'deleted': item.id, 'soft_deleted': bool(ordered or item.ppmp_item_id)})
    try:
        values = parse_ppmp_record_item(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    for field, value in values.items():
        setattr(item, field, value)
    audit('ppmp_record_item', item.id, 'PPMP_ITEM_UPDATED', {'ppmp_record_id': record.id})
    db.session.commit()
    return jsonify(item.to_dict())


@app.route('/api/ppmp-records/<int:record_id>/submit', methods=['POST'])
@login_required
def submit_ppmp_record(record_id):
    return jsonify({'error': 'Planning documents are indicative copies. Submit the official PPMP from PPMP Request Records.'}), 409
    record = PPMPRecord.query.filter_by(id=record_id).with_for_update().one_or_none()
    user = current_session_user()
    if record is None:
        return jsonify({'error': 'PPMP record not found.'}), 404
    if not can_access_ppmp_record(user, record):
        return jsonify({'error': 'You cannot access another office\'s PPMP record.'}), 403
    if not can_edit_ppmp_record(user, record):
        return jsonify({'error': 'Only a Draft or Returned PPMP can be submitted once.'}), 409
    validation_error = validate_ppmp_record_for_submission(record)
    if validation_error:
        return jsonify({'error': validation_error}), 400
    previous = record.status
    record.status = 'Submitted'
    record.submitted_at = datetime.utcnow()
    record.decision_note = None
    if record.submission_request:
        record.submission_request.status = 'Submitted'
        record.submission_request.submitted_at = record.submitted_at
    action = 'PPMP_RESUBMITTED' if previous == 'Returned' else 'PPMP_SUBMITTED'
    audit('ppmp_record', record.id, action, {'from': previous, 'to': record.status})
    notify_roles(
        ('EO', 'AA', 'ADMIN'), 'PPMP record submitted',
        f'{record.reference_number} from {record.office.code} is ready for review.',
    )
    db.session.commit()
    return jsonify(ppmp_record_response(record))


@app.route('/api/ppmp-records/<int:record_id>/transition', methods=['POST'])
@login_required
def transition_ppmp_record(record_id):
    return jsonify({'error': 'Planning copies have no approval workflow. Review the official PPMP request instead.'}), 409
    record = PPMPRecord.query.filter_by(id=record_id).with_for_update().one_or_none()
    user = current_session_user()
    if record is None:
        return jsonify({'error': 'PPMP record not found.'}), 404
    if not can_access_ppmp_record(user, record) or not has_permission(user, 'ppmp.record.review'):
        return jsonify({'error': 'You do not have permission to review this PPMP record.'}), 403
    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '').strip().lower()
    note = str(data.get('note') or '').strip() or None
    if action in {'return', 'reject'} and not note:
        return jsonify({'error': 'A reason/comment is required when returning or rejecting a PPMP.'}), 400
    actor = 'EO' if user.role in {'EO', 'AA'} else user.role
    transitions = {
        ('EO', 'Submitted', 'approve'): 'Under Review',
        ('EO', 'Submitted', 'return'): 'Returned',
        ('EO', 'Submitted', 'reject'): 'Rejected',
        ('PROCUREMENT', 'Under Review', 'approve'): 'Pending Admin Approval',
        ('PROCUREMENT', 'Under Review', 'return'): 'Returned',
        ('PROCUREMENT', 'Under Review', 'reject'): 'Rejected',
        ('ADMIN', 'Pending Admin Approval', 'approve'): 'Approved',
        ('ADMIN', 'Pending Admin Approval', 'return'): 'Returned',
        ('ADMIN', 'Pending Admin Approval', 'reject'): 'Rejected',
    }
    target = transitions.get((actor, record.status, action))
    if target is None:
        return jsonify({'error': 'This PPMP record transition is not allowed.'}), 409
    previous = record.status
    now = datetime.utcnow()
    record.status = target
    record.reviewed_by = user.id
    record.reviewed_at = now
    record.decision_note = note
    materialized = 0
    if target == 'Approved':
        record.approved_by = user.id
        record.approved_at = now
        materialized = materialize_approved_ppmp_record(record, user)
    if record.submission_request:
        record.submission_request.status = target if target in {'Returned', 'Approved'} else (
            'Closed' if target == 'Rejected' else 'Submitted'
        )
    if note:
        db.session.add(PPMPComment(
            ppmp_record_id=record.id, author_id=user.id,
            comment_type='PPMP Review', message=note,
        ))
    audit('ppmp_record', record.id, f'PPMP_{action.upper()}', {
        'from': previous, 'to': target, 'materialized_ppmp_items': materialized,
    })
    if target == 'Under Review':
        notify_roles(('PROCUREMENT', 'ADMIN'), 'PPMP ready for Procurement review', f'{record.reference_number} requires review.')
    elif target == 'Pending Admin Approval':
        notify_roles(('ADMIN',), 'PPMP pending Administrator approval', f'{record.reference_number} requires final review.')
    elif record.preparer:
        add_notification(
            [record.preparer], f'PPMP {target.lower()}',
            note or f'{record.reference_number} is now {target}.',
            'success' if target == 'Approved' else 'warning',
        )
    db.session.commit()
    return jsonify(ppmp_record_response(record))


@app.route('/api/ppmp-records/<int:record_id>/comments', methods=['GET', 'POST'])
@login_required
def ppmp_record_comments(record_id):
    record = db.session.get(PPMPRecord, record_id)
    user = current_session_user()
    if record is None:
        return jsonify({'error': 'PPMP record not found.'}), 404
    if not can_access_ppmp_record(user, record):
        return jsonify({'error': 'You cannot access comments for another office\'s PPMP.'}), 403
    if request.method == 'GET':
        comments = PPMPComment.query.filter_by(ppmp_record_id=record.id).order_by(PPMPComment.created_at.asc()).all()
        return jsonify([comment.to_dict() for comment in comments])
    if user.role != 'ADMIN':
        return jsonify({'error': 'Only the Administrator can add PPMP review comments.'}), 403
    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()
    if not message or len(message) > 5000:
        return jsonify({'error': 'A comment of up to 5,000 characters is required.'}), 400
    item_id = data.get('ppmp_record_item_id')
    related_item = None
    if item_id is not None and item_id != '':
        try:
            related_item = db.session.get(PPMPRecordItem, int(item_id))
        except (TypeError, ValueError):
            related_item = None
        if related_item is None or related_item.ppmp_record_id != record.id:
            return jsonify({'error': 'The related Wishlist item does not belong to this PPMP.'}), 400
    comment = PPMPComment(
        ppmp_record_id=record.id,
        ppmp_record_item_id=related_item.id if related_item else None,
        author_id=user.id,
        comment_type='Wishlist Item' if related_item else 'PPMP Review',
        message=message,
    )
    db.session.add(comment)
    db.session.flush()
    audit('ppmp_record', record.id, 'ADMIN_COMMENT_ADDED', {
        'comment_id': comment.id, 'ppmp_record_item_id': comment.ppmp_record_item_id,
    })
    if record.preparer:
        add_notification([record.preparer], 'Administrator PPMP comment', f'New comment on {record.reference_number}.')
    db.session.commit()
    return jsonify(comment.to_dict()), 201


@app.route("/api/ppmp-requests", methods=["GET", "POST"])
def ppmp_submission_requests():
    if request.method == "GET":
        user = current_session_user()
        query = PPMPSubmissionRequest.query
        if user.role not in {'ADMIN', 'EO', 'AA', 'PROCUREMENT', 'BUDGET'}:
            if not is_ppmp_office_role(user.role):
                return jsonify({'error': 'You do not have permission to view PPMP submission requests.'}), 403
            query = query.filter_by(college_id=user.college_id)
        results = []
        for submission_request in query.order_by(PPMPSubmissionRequest.created_at.desc()).all():
            result = submission_request.to_dict()
            record = visible_ppmp_records().filter_by(submission_request_id=submission_request.id).first()
            result['ppmp_record_id'] = record.id if record else None
            result['ppmp_reference_number'] = record.reference_number if record else None
            result['ppmp_status'] = record.status if record else None
            results.append(result)
        return jsonify(results)
    user = current_session_user()
    if user.role not in {'EO', 'AA'} or not has_permission(user, 'ppmp.request.create'):
        return jsonify({"error": "Only EO/Academic Affairs can request PPMP submissions."}), 403
    data = request.get_json(silent=True) or {}
    college = db.session.get(College, data.get("college_id"))
    try:
        fiscal_year = int(data.get("fiscal_year", datetime.utcnow().year))
    except (TypeError, ValueError):
        fiscal_year = 0
    if college is None or not college.is_active or fiscal_year < 2000 or fiscal_year > 2100:
        return jsonify({"error": "A valid college and fiscal year are required."}), 400
    if PPMPSubmissionRequest.query.filter_by(college_id=college.id, fiscal_year=fiscal_year).first():
        return jsonify({"error": "A PPMP request already exists for this college and year."}), 409
    notes = (data.get("notes") or "").strip() or None
    if notes and len(notes) > 5000:
        return jsonify({'error': 'Request details must not exceed 5,000 characters.'}), 400
    due_date = None
    if data.get('due_date'):
        try:
            due_date = datetime.strptime(str(data['due_date']), '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Submission deadline must be a valid date.'}), 400
    record = PPMPSubmissionRequest(college_id=college.id, fiscal_year=fiscal_year, requested_by=user.id,
                                   notes=notes, due_date=due_date)
    db.session.add(record)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A PPMP request already exists for this college and year.'}), 409
    audit("ppmp_submission_request", record.id, "PPMP_REQUEST_CREATED", {
        'college_id': college.id, 'fiscal_year': fiscal_year,
    })
    recipients = User.query.filter_by(college_id=college.id, is_active=True).all()
    add_notification(
        recipients, "New PPMP Request",
        f"Academic Affairs / EO requested your PPMP submission for Fiscal Year {fiscal_year}.",
    )
    db.session.commit()
    return jsonify(record.to_dict()), 201




@app.route("/api/wishlist", methods=["GET", "POST"])
def wishlist():
    if request.method == "GET":
        query = WishlistItem.query
        user = current_session_user()
        if user.role != 'ADMIN':
            query = query.filter_by(status='Available')
        search = (request.args.get("search") or "").strip()
        status = request.args.get("status")
        if search:
            pattern = f"%{search}%"
            query = query.filter(or_(
                WishlistItem.item_description.ilike(pattern),
                WishlistItem.category.ilike(pattern),
                WishlistItem.unit.ilike(pattern),
                WishlistItem.office.ilike(pattern),
            ))
        if status in WishlistItem.STATUSES:
            query = query.filter_by(status=status)
        return jsonify([item.to_dict() for item in query.order_by(WishlistItem.id.desc())])
    user = current_session_user()
    if user.role != 'ADMIN':
        return jsonify({"error": "Only the administrator can add CSE Master List items."}), 403
    data = request.get_json(silent=True) or {}
    required = ("item_description", "category", "unit", "estimated_cost")
    if not all(str(data.get(field, "")).strip() for field in required):
        return jsonify({"error": "Complete all required CSE Master List fields."}), 400
    try:
        cost = float(data["estimated_cost"])
    except (TypeError, ValueError):
        return jsonify({"error": "Estimated cost must be a valid number."}), 400
    if cost < 0:
        return jsonify({"error": "Estimated cost cannot be negative."}), 400
    item = WishlistItem(office=user.office, created_by=user.id, item_description=data["item_description"].strip(),
                        category=data["category"].strip(), unit=data["unit"].strip(), quantity=0,
                        estimated_cost=cost, remarks=(data.get("remarks") or "").strip() or None)
    db.session.add(item)
    db.session.flush()
    audit("wishlist_item", item.id, "CREATE")
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route("/api/wishlist/<int:item_id>", methods=["PUT", "DELETE"])
@admin_required
def update_wishlist(item_id):
    item, user = db.session.get(WishlistItem, item_id), current_session_user()
    if item is None:
        return jsonify({"error": "Wishlist item not found."}), 404
    if item.status not in {"Available", "Returned"}:
        return jsonify({"error": "A requested wishlist item cannot be modified or removed."}), 409
    if request.method == "DELETE":
        linked_order = PPMPOrderItem.query.filter(or_(
            PPMPOrderItem.master_item_id == item.id,
            PPMPOrderItem.legacy_wishlist_item_id == item.id,
        )).first()
        linked_legacy_request = WishlistRequest.query.filter_by(wishlist_item_id=item.id).first()
        if linked_order or linked_legacy_request:
            return jsonify({
                "error": "This CSE Master List item is linked to an existing request and cannot be deleted."
            }), 409
        audit("wishlist_item", item.id, "DELETE")
        db.session.delete(item)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({
                "error": "This CSE Master List item is linked to an existing request and cannot be deleted."
            }), 409
        return jsonify({"deleted": item_id})
    data = request.get_json(silent=True) or {}
    for field in ("item_description", "category", "unit", "remarks"):
        if field in data:
            value = (data[field] or "").strip()
            if field != "remarks" and not value:
                return jsonify({"error": f"{field.replace('_', ' ').title()} is required."}), 400
            setattr(item, field, value or None)
    if "estimated_cost" in data:
        try:
            value = float(data["estimated_cost"])
        except (TypeError, ValueError):
            return jsonify({"error": "Estimated cost must be numeric."}), 400
        if value < 0:
            return jsonify({"error": "Estimated cost cannot be negative."}), 400
        item.estimated_cost = value
    audit("wishlist_item", item.id, "UPDATE")
    db.session.commit()
    return jsonify(item.to_dict())


def materialize_approved_ppmp_order(order, approver):
    """Create procurement rows without ever promoting custom items to the master Wishlist."""
    created = 0
    for source in order.items:
        if source.ppmp_item_id:
            continue
        item = PPMPItem(
            college_id=order.office_id,
            fiscal_year=order.fiscal_year,
            item_description=source.item_name,
            unit=source.unit,
            quantity=source.quantity,
            unit_cost=source.estimated_unit_cost,
            authorized_budget=source.estimated_budget,
            fund_source=source.source_of_funds,
            mode_of_procurement=source.procurement_method,
            procurement_type=source.project_type,
            quarter=order.quarter,
            remarks=source.remarks,
            status='Approved',
            created_by=order.requested_by,
            approved_by=approver.id,
            approved_at=order.decided_at,
        )
        db.session.add(item)
        db.session.flush()
        source.ppmp_item_id = item.id
        created += 1
    return created


def create_order_from_ppmp_wishlist(user, office, data):
    """Create one actual request from approved 12-column PPMP Wishlist rows."""
    raw_ids = data.get('wishlist_item_ids')
    if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 100:
        return jsonify({'error': 'Select between 1 and 100 PPMP Wishlist items.'}), 400
    try:
        item_ids = [int(item_id) for item_id in raw_ids]
    except (TypeError, ValueError):
        return jsonify({'error': 'Every selected PPMP Wishlist item must have a valid identifier.'}), 400
    if len(item_ids) != len(set(item_ids)):
        return jsonify({'error': 'A PPMP Wishlist item can only appear once in a request.'}), 400

    source_items = PPMPRecordItem.query.filter(PPMPRecordItem.id.in_(item_ids)).with_for_update().all()
    if len(source_items) != len(item_ids):
        return jsonify({'error': 'One or more selected PPMP Wishlist items do not exist.'}), 404
    record_ids = {item.ppmp_record_id for item in source_items}
    if len(record_ids) != 1:
        return jsonify({'error': 'All selected items must belong to the same PPMP record.'}), 400
    record = db.session.get(PPMPRecord, record_ids.pop())
    if record is None or record.office_id != office.id:
        return jsonify({'error': 'You cannot request items from another office\'s PPMP.'}), 403
    if is_deleted_legacy_ppmp_record(record):
        return jsonify({'error': 'This legacy PPMP document has been deleted. Use an available approved PPMP document.'}), 409
    if record.status != 'Approved':
        return jsonify({'error': 'Wishlist items can only be requested after the PPMP is approved.'}), 409
    if any(item.item_status == 'Removed' or not item.ppmp_item_id for item in source_items):
        return jsonify({'error': 'A removed or unapproved PPMP Wishlist item cannot be requested.'}), 409
    existing = PPMPOrderItem.query.filter(PPMPOrderItem.wishlist_item_id.in_(item_ids)).first()
    if existing:
        return jsonify({'error': 'One or more selected PPMP Wishlist items already have a request.'}), 409

    remarks = str(data.get('remarks') or '').strip() or None
    if remarks and len(remarks) > 5000:
        return jsonify({'error': 'Wishlist request remarks must not exceed 5,000 characters.'}), 400
    now = datetime.utcnow()
    first = source_items[0]
    order = PPMPOrder(
        reference_number=f'WLR-{now:%Y%m%d}-{secrets.token_hex(5).upper()}',
        office_id=office.id,
        requested_by=user.id,
        fiscal_year=record.fiscal_year,
        fund_source=first.source_of_funds,
        mode_of_procurement=first.procurement_method,
        procurement_type=first.project_type,
        quarter=record_quarter(first),
        status='Submitted',
        remarks=remarks,
        submitted_at=now,
    )
    db.session.add(order)
    db.session.flush()
    for source in source_items:
        quantity = Decimal(source.quantity)
        unit_cost = (Decimal(source.estimated_budget) / quantity).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP,
        )
        db.session.add(PPMPOrderItem(
            order_id=order.id,
            wishlist_item_id=source.id,
            ppmp_item_id=source.ppmp_item_id,
            item_name=source.general_description[:300],
            description=source.general_description,
            category=source.project_type,
            project_type=source.project_type,
            quantity=source.quantity,
            unit=source.unit_size,
            procurement_method=source.procurement_method,
            pre_procurement_conference=source.pre_procurement_conference,
            procurement_start=source.procurement_start,
            procurement_end=source.procurement_end,
            delivery_period=source.delivery_period,
            schedule_as_needed=source.schedule_as_needed,
            source_of_funds=source.source_of_funds,
            estimated_unit_cost=unit_cost,
            estimated_budget=source.estimated_budget,
            supporting_documents=source.supporting_documents,
            remarks=source.remarks,
            created_by=user.id,
            is_custom_item=False,
        ))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'One or more selected Wishlist items already have a request.'}), 409
    audit('wishlist_order', order.id, 'WISHLIST_REQUEST_CREATED', {
        'ppmp_record_id': record.id,
        'wishlist_item_ids': item_ids,
        'status': order.status,
    })
    notify_roles(
        ('PROCUREMENT',), 'Wishlist request ready for APP consolidation',
        f'{order.reference_number} from {office.code} requires APP / Procurement consolidation.',
    )
    db.session.commit()
    return jsonify(order.to_dict()), 201


@app.route('/api/ppmp-orders', methods=['GET', 'POST'])
def ppmp_orders():
    user = current_session_user()
    if request.method == 'GET':
        if not has_permission(user, 'ppmp.order.view'):
            return jsonify({'error': 'You do not have permission to view Wishlist requests.'}), 403
        query = PPMPOrder.query
        if is_ppmp_office_role(user.role):
            if not user.college_id:
                return jsonify([])
            query = query.filter_by(office_id=user.college_id)
        status = (request.args.get('status') or '').strip()
        if status in PPMPOrder.STATUSES:
            query = query.filter_by(status=status)
        return jsonify([order.to_dict() for order in query.order_by(PPMPOrder.submitted_at.desc()).all()])

    if not has_permission(user, 'ppmp.order.create') or not is_ppmp_office_role(user.role):
        return jsonify({'error': 'Only an approved office user can submit a Wishlist request.'}), 403
    office = db.session.get(College, user.college_id) if user.college_id else None
    if office is None or not office.is_active:
        return jsonify({'error': 'Your account must be linked to an active office before submitting a Wishlist request.'}), 409
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'Provide a valid PPMP draft.'}), 400
    if 'wishlist_item_ids' in data:
        return jsonify({'error': 'Create the official PPMP from Selected Items; planning copies cannot create another request.'}), 409
    requested_items = data.get('items')
    if not isinstance(requested_items, list) or not requested_items or len(requested_items) > 100:
        return jsonify({'error': 'Add between 1 and 100 items to the PPMP request.'}), 400
    try:
        fiscal_year = int(data.get('fiscal_year'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Fiscal year must be a valid year.'}), 400
    quarter = str(data.get('quarter') or '').strip()
    if isinstance(data.get('fiscal_year'), bool) or (isinstance(data.get('fiscal_year'), float) and data['fiscal_year'] != fiscal_year) or not 2026 <= fiscal_year <= 2100:
        return jsonify({'error': 'Fiscal year must be between 2026 and 2100.'}), 400
    if quarter not in QUARTERS:
        return jsonify({'error': 'Select a valid quarter.'}), 400

    if OfficialPPMP.query.filter_by(office_id=office.id, fiscal_year=fiscal_year).first():
        return jsonify({'error': 'Your office already has an official PPMP for this fiscal year. Open its existing record.'}), 409
    if PPMPOrder.query.filter_by(office_id=office.id, fiscal_year=fiscal_year).filter(PPMPOrder.status != 'Rejected').first():
        return jsonify({'error': 'Existing PPMP records already cover this office and fiscal year. Ask Admin to designate the official record before creating another.'}), 409

    master_ids = []
    for requested in requested_items:
        if not isinstance(requested, dict):
            return jsonify({'error': 'Every request item must be a valid object.'}), 400
        master_id = requested.get('master_item_id')
        if master_id is not None:
            if type(master_id) is not int or master_id <= 0:
                return jsonify({'error': 'A selected CSE Master List item must have an integer identifier.'}), 400
            try:
                master_ids.append(int(master_id))
            except (TypeError, ValueError):
                return jsonify({'error': 'A selected CSE Master List item has an invalid identifier.'}), 400
    if len(master_ids) != len(set(master_ids)):
        return jsonify({'error': 'A CSE Master List item can only appear once in a request.'}), 400
    masters = (
        WishlistItem.query.filter(WishlistItem.id.in_(master_ids)).with_for_update().all()
        if master_ids else []
    )
    if len(masters) != len(master_ids):
        return jsonify({'error': 'One or more selected CSE Master List items do not exist.'}), 404
    master_by_id = {item.id: item for item in masters}
    if any(item.status != 'Available' for item in masters):
        return jsonify({'error': 'Only available CSE Master List items can be requested.'}), 409
    now = datetime.utcnow()
    order = PPMPOrder(
        reference_number=f'PPMPR-{now:%Y%m%d}-{secrets.token_hex(5).upper()}',
        office_id=office.id,
        requested_by=user.id,
        fiscal_year=fiscal_year,
        quarter=quarter,
        status='Draft',
        workflow_official=True,
        submitted_at=now,
    )
    db.session.add(order)
    try:
        db.session.flush()
        db.session.add(OfficialPPMP(office_id=office.id, fiscal_year=fiscal_year, source_order_id=order.id))
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Your office already has an official PPMP for this fiscal year. Refresh the list.'}), 409
    for requested in requested_items:
        try:
            quantity = positive_decimal(requested.get('quantity'), 'Quantity')
        except ValueError as error:
            db.session.rollback()
            return jsonify({'error': str(error)}), 400
        master_id = requested.get('master_item_id')
        if master_id is not None:
            master = master_by_id[int(master_id)]
            item_name = master.item_description
            description = master.remarks
            category = master.category
            unit = master.unit
            unit_cost = Decimal(master.estimated_cost)
            is_custom = False
        else:
            item_name = str(requested.get('item_name') or '').strip()
            description = str(requested.get('description') or '').strip() or None
            category = str(requested.get('category') or '').strip()
            unit = str(requested.get('unit') or '').strip()
            try:
                unit_cost = positive_decimal(requested.get('estimated_unit_cost'), 'Estimated unit cost', allow_zero=True)
            except ValueError as error:
                db.session.rollback()
                return jsonify({'error': str(error)}), 400
            if not item_name or not category or not unit:
                db.session.rollback()
                return jsonify({'error': 'Name, category, and unit are required for every unlisted item.'}), 400
            if category not in PPMP_ORDER_CATEGORIES:
                db.session.rollback()
                return jsonify({'error': 'Select a valid category for every unlisted item.'}), 400
            if len(item_name) > 300 or len(category) > 80 or len(unit) > 60 or (description and len(description) > 5000):
                db.session.rollback()
                return jsonify({'error': 'An unlisted item exceeds the allowed field length.'}), 400
            if unit_cost < 0:
                db.session.rollback()
                return jsonify({'error': 'An unlisted item price cannot be negative.'}), 400
            is_custom = True
        total = (quantity * unit_cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if total > Decimal('9999999999999999.99'):
            db.session.rollback()
            return jsonify({'error': 'The item budget exceeds the supported range.'}), 400
        db.session.add(PPMPOrderItem(
            order_id=order.id,
            master_item_id=None if is_custom else int(master_id),
            item_name=item_name,
            description=description,
            category=category,
            quantity=quantity,
            unit=unit,
            estimated_unit_cost=unit_cost,
            estimated_budget=total,
            created_by=user.id,
            is_custom_item=is_custom,
        ))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'The PPMP request could not be saved because an item conflicts with existing data.'}), 409
    audit('ppmp_order', order.id, 'OFFICIAL_PPMP_DRAFT_CREATED', {
        'reference_number': order.reference_number,
        'master_item_ids': master_ids,
        'custom_item_count': sum(1 for item in order.items if item.is_custom_item),
        'status': order.status,
    })
    db.session.commit()
    return jsonify(order.to_dict()), 201


def ppmp_order_return_reviewer(order):
    """Recover the returning reviewer for historical records without return_stage."""
    if order.return_stage in {'ADMIN', 'PROCUREMENT'}:
        return order.return_stage
    events = WorkflowAuditLog.query.filter(
        WorkflowAuditLog.entity_type == 'ppmp_order', WorkflowAuditLog.entity_id == order.id,
        WorkflowAuditLog.action.in_(['WISHLIST_REQUEST_RETURNED', 'PPMP_RETURNED', 'RETURN']),
    ).order_by(WorkflowAuditLog.id.desc()).all()
    for event in events:
        role = (event.details or {}).get('reviewer_role') or (event.performer.role if event.performer else None)
        if role in {'ADMIN', 'PROCUREMENT'}:
            return role
        if role in {'EO', 'AA'}:
            return 'PROCUREMENT'
    # Historical Wishlist requests were reviewed and returned by Admin.
    return 'ADMIN'


@app.route('/api/ppmp-orders/<int:order_id>/transition', methods=['POST'])
@login_required
def transition_ppmp_order(order_id):
    order = PPMPOrder.query.filter_by(id=order_id).with_for_update().one_or_none()
    if order is None:
        return jsonify({'error': 'Wishlist request not found.'}), 404
    user = current_session_user()
    if not has_permission(user, 'ppmp.order.view'):
        return jsonify({'error': 'You do not have permission to process Wishlist requests.'}), 403
    if is_ppmp_office_role(user.role) and order.office_id != user.college_id:
        return jsonify({'error': 'You cannot access another office\'s Wishlist request.'}), 403
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip().lower()
    note = (data.get('note') or '').strip() or None
    if action in {'return', 'reject'} and not note:
        return jsonify({'error': 'A reason is required when returning or rejecting a Wishlist request.'}), 400
    if note and len(note) > 5000:
        return jsonify({'error': 'The review note must not exceed 5,000 characters.'}), 400
    actor = 'office' if is_ppmp_office_role(user.role) else ('EO' if user.role == 'AA' else user.role)
    if actor == 'office' and order.requested_by != user.id:
        return jsonify({'error': 'Only the creator can resubmit this PPMP.'}), 403
    returning_reviewer = ppmp_order_return_reviewer(order) if order.status == 'Returned' else None
    resume_status = 'Pending Admin Approval' if returning_reviewer == 'ADMIN' else 'Submitted'
    transitions = {
        ('office', 'Draft', 'submit'): 'Submitted',
        ('office', 'Returned', 'submit'): resume_status,
        ('ADMIN', 'Pending Admin Approval', 'approve'): 'Approved',
        ('ADMIN', 'Pending Admin Approval', 'return'): 'Returned',
        ('ADMIN', 'Pending Admin Approval', 'reject'): 'Rejected',
        ('PROCUREMENT', 'Submitted', 'approve'): 'Pending Admin Approval',
        ('PROCUREMENT', 'Submitted', 'return'): 'Returned',
        ('PROCUREMENT', 'Submitted', 'reject'): 'Rejected',
        ('PROCUREMENT', 'EO Review', 'approve'): 'Pending Admin Approval',
        ('PROCUREMENT', 'EO Review', 'return'): 'Returned',
        ('PROCUREMENT', 'EO Review', 'reject'): 'Rejected',
        ('ADMIN', 'Procurement Review', 'approve'): 'Approved',
        ('ADMIN', 'Procurement Review', 'return'): 'Returned',
        ('ADMIN', 'Procurement Review', 'reject'): 'Rejected',
        ('ADMIN', 'Approved', 'process'): 'Processing',
        ('ADMIN', 'Processing', 'complete'): 'Completed',
    }
    if not order.workflow_official:
        transitions[('ADMIN', 'Requested', 'return')] = 'Returned'
        transitions[('ADMIN', 'Returned', 'return')] = 'Returned'
    target = transitions.get((actor, order.status, action))
    if target is None:
        return jsonify({'error': 'This Wishlist request transition is not allowed.'}), 409
    auto_returned = False
    missing_fields = ppmp_request_report_missing_fields(order) if action in {'submit', 'approve'} else []
    if action == 'approve' and actor == 'ADMIN' and missing_fields:
        action, target, auto_returned = 'return', 'Returned', True
        summary = '; '.join(f'{row["item_name"]}: {", ".join(row["fields"])}' for row in missing_fields[:10])
        note = (f'Returned for completion. {summary}' + (f' Review note: {note}' if note else ''))[:5000]
    if not order.workflow_official and ((action == 'approve' and target == 'Approved') or (action == 'submit' and order.status != 'Returned')):
        return jsonify({'error': 'Admin must designate this historical record as the official PPMP before approval. A Returned record may be corrected and resubmitted to its reviewer.'}), 409
    if action in {'submit', 'approve'} and missing_fields:
        return jsonify({
            'error': 'Complete all required PPMP report fields and valid dates before resubmitting.',
            'missing_fields': missing_fields,
        }), 409

    previous = order.status
    resolve_notification_tasks('ppmp_order', order.id)
    order.status = target
    if action == 'return':
        order.return_stage = actor
    elif action == 'approve':
        order.return_stage = None
    if action == 'submit':
        order.return_stage = returning_reviewer
        order.submitted_at = datetime.utcnow()
    if note:
        order.admin_note = note
    materialized = 0
    if target in {'Approved', 'Rejected', 'Completed'}:
        order.decided_by = user.id
        order.decided_at = datetime.utcnow()
    if target == 'Approved':
        materialized = materialize_approved_ppmp_order(order, user)
    if note:
        db.session.add(PPMPComment(
            wishlist_order_id=order.id,
            author_id=user.id,
            comment_type='Wishlist Request',
            message=note,
        ))
    audit_action = {
        'approve': 'WISHLIST_REQUEST_APPROVED',
        'return': 'WISHLIST_REQUEST_RETURNED',
        'reject': 'WISHLIST_REQUEST_REJECTED',
        'submit': 'WISHLIST_REQUEST_RESUBMITTED',
        'process': 'WISHLIST_REQUEST_PROCESSING',
        'complete': 'WISHLIST_REQUEST_COMPLETED',
    }.get(action, f'WISHLIST_REQUEST_{action.upper()}')
    audit('ppmp_order', order.id, audit_action, {
        'from': previous, 'to': target, 'materialized_ppmp_items': materialized,
        'return_stage': order.return_stage, 'reviewer_role': user.role,
        'automatic_return_for_incomplete_report': auto_returned,
        'items': [ppmp_request_report_item(item, order) for item in order.items],
    })
    notify_ppmp_order_update(order, action, actor, note)
    db.session.commit()
    return jsonify(dict(order.to_dict(), auto_returned=auto_returned))


@app.route('/api/ppmp-orders/<int:order_id>/comments', methods=['GET', 'POST'])
@login_required
def ppmp_order_comments(order_id):
    order = db.session.get(PPMPOrder, order_id)
    user = current_session_user()
    if order is None:
        return jsonify({'error': 'Wishlist request not found.'}), 404
    if not has_permission(user, 'ppmp.order.view'):
        return jsonify({'error': 'You do not have permission to view Wishlist request comments.'}), 403
    if is_ppmp_office_role(user.role) and order.office_id != user.college_id:
        return jsonify({'error': 'You cannot access another office\'s Wishlist request.'}), 403
    if request.method == 'GET':
        comments = PPMPComment.query.filter_by(wishlist_order_id=order.id).order_by(PPMPComment.created_at.asc()).all()
        return jsonify([comment.to_dict() for comment in comments])
    if user.role != 'ADMIN':
        return jsonify({'error': 'Only the Administrator can add Wishlist request comments.'}), 403
    message = str((request.get_json(silent=True) or {}).get('message') or '').strip()
    if not message or len(message) > 5000:
        return jsonify({'error': 'A comment of up to 5,000 characters is required.'}), 400
    comment = PPMPComment(
        wishlist_order_id=order.id,
        author_id=user.id,
        comment_type='Wishlist Request',
        message=message,
    )
    db.session.add(comment)
    db.session.flush()
    audit('wishlist_order', order.id, 'ADMIN_COMMENT_ADDED', {'comment_id': comment.id})
    notify_offices({order.office_id}, 'Administrator PPMP comment',
                   f'{order.reference_number} (FY {order.fiscal_year}): {message}',
                   extra_recipients=[order.requester], target_type='ppmp_order', target_id=order.id)
    db.session.commit()
    return jsonify(comment.to_dict()), 201


def available_ppmp_reports_query(user):
    query = PPMPReport.query.filter_by(is_available=True)
    if user.role != 'ADMIN':
        if not user.college_id:
            return query.filter(text('1 = 0'))
        query = query.filter_by(office_id=user.college_id)
    return query


@app.route('/api/reports/available', methods=['GET', 'POST'])
@permission_required('ppmp.report')
def available_ppmp_reports():
    user = current_session_user()
    if request.method == 'GET':
        reports = available_ppmp_reports_query(user).order_by(PPMPReport.updated_at.desc()).all()
        return jsonify([report.to_dict() for report in reports])
    if user.role != 'ADMIN':
        return jsonify({'error': 'Only the Administrator can make PPMP reports available.'}), 403
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    office = db.session.get(College, data.get('office_id'))
    if not title or len(title) > 180 or office is None or not office.is_active:
        return jsonify({'error': 'A title and valid active office are required.'}), 400
    fiscal_year = None
    if str(data.get('fiscal_year') or '').strip():
        try:
            fiscal_year = int(data['fiscal_year'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Fiscal year must be a valid year.'}), 400
        if not 2000 <= fiscal_year <= 2100:
            return jsonify({'error': 'Fiscal year must be between 2000 and 2100.'}), 400
    report = PPMPReport(
        title=title, office_id=office.id, fiscal_year=fiscal_year,
        updated_by=user.id, is_available=True,
    )
    db.session.add(report)
    db.session.flush()
    audit('ppmp_report', report.id, 'MAKE_AVAILABLE', {
        'office_id': office.id, 'fiscal_year': fiscal_year,
    })
    db.session.commit()
    return jsonify(report.to_dict()), 201


@app.route('/api/reports/available/<int:report_id>', methods=['PUT'])
@admin_required
def update_available_ppmp_report(report_id):
    report = db.session.get(PPMPReport, report_id)
    if report is None:
        return jsonify({'error': 'Available report not found.'}), 404
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    office = db.session.get(College, data.get('office_id'))
    if not title or len(title) > 180 or office is None or not office.is_active:
        return jsonify({'error': 'A title and valid active office are required.'}), 400
    fiscal_year = None
    if str(data.get('fiscal_year') or '').strip():
        try:
            fiscal_year = int(data['fiscal_year'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Fiscal year must be a valid year.'}), 400
        if not 2000 <= fiscal_year <= 2100:
            return jsonify({'error': 'Fiscal year must be between 2000 and 2100.'}), 400
    report.title = title
    report.office_id = office.id
    report.fiscal_year = fiscal_year
    report.updated_by = current_session_user().id
    report.is_available = True
    audit('ppmp_report', report.id, 'UPDATE_AVAILABLE_REPORT', {
        'office_id': office.id, 'fiscal_year': fiscal_year,
    })
    db.session.commit()
    return jsonify(report.to_dict())


def scoped_ppmp_report_orders(user):
    """Return only PPMP order rows authorized for this account and report selection."""
    query = PPMPOrder.query
    report = None
    report_id = request.args.get('report_id', type=int)
    if report_id:
        report = available_ppmp_reports_query(user).filter(PPMPReport.id == report_id).first()
        if report is None:
            return None, None, (jsonify({'error': 'Available report not found.'}), 404)
        query = query.filter_by(office_id=report.office_id)
        if report.fiscal_year:
            query = query.filter_by(fiscal_year=report.fiscal_year)
    else:
        office_id = request.args.get('office_id', type=int)
        if is_ppmp_office_role(user.role):
            if not user.college_id:
                query = query.filter(text('1 = 0'))
            elif office_id and office_id != user.college_id:
                return None, None, (jsonify({'error': 'You cannot access another office report.'}), 403)
            else:
                query = query.filter_by(office_id=user.college_id)
        elif office_id:
            query = query.filter_by(office_id=office_id)
        fiscal_year = request.args.get('fiscal_year', type=int)
        if fiscal_year:
            if not 2000 <= fiscal_year <= 2100:
                return None, None, (jsonify({'error': 'Fiscal year must be between 2000 and 2100.'}), 400)
            query = query.filter_by(fiscal_year=fiscal_year)
    orders = query.order_by(PPMPOrder.submitted_at.asc(), PPMPOrder.created_at.asc()).all()
    return orders, report, None


def authorized_ppmp_request_report(user, order_id, *, require_pending=True):
    order = (PPMPOrder.query.filter_by(id=order_id).with_for_update().one_or_none()
             if require_pending else db.session.get(PPMPOrder, order_id))
    if order is None:
        return None, (jsonify({'error': 'PPMP Request Record not found.'}), 404)
    if is_ppmp_office_role(user.role) and order.office_id != user.college_id:
        return None, (jsonify({'error': 'You cannot access another office PPMP Request Record.'}), 403)
    if require_pending and not can_edit_official_ppmp(user, order):
        return None, (jsonify({'error': 'Only the creator can edit their Draft or Returned PPMP. Submitted and approved records are locked.'}), 409)
    return order, None


def ppmp_report_month(value):
    return value.strftime('%b-%y') if value else ''


def ppmp_request_report_item(item, order):
    return {
        'id': item.id,
        'general_description': item.item_name,
        'project_type': item.project_type or '',
        'quantity_and_size': f'{float(item.quantity or 0):g} {item.unit}',
        'quantity': float(item.quantity or 0),
        'unit': item.unit,
        'procurement_method': item.procurement_method or '',
        'pre_procurement_conference': (
            'Yes' if item.pre_procurement_conference is True
            else 'No' if item.pre_procurement_conference is False else ''
        ),
        'procurement_start': item.procurement_start.isoformat()[:7] if item.procurement_start else '',
        'procurement_start_display': ppmp_report_month(item.procurement_start),
        'procurement_end': item.procurement_end.isoformat()[:7] if item.procurement_end else '',
        'procurement_end_display': ppmp_report_month(item.procurement_end),
        'delivery_period': item.delivery_period.isoformat()[:7] if item.delivery_period else '',
        'delivery_period_display': ppmp_report_month(item.delivery_period),
        'source_of_funds': item.source_of_funds or '',
        'estimated_budget': float(item.estimated_budget or 0),
        'supporting_documents': item.supporting_documents or '',
        'remarks': item.remarks or '',
    }


def ppmp_request_report_payload(order, user):
    missing_fields = ppmp_request_report_missing_fields(order)
    editable = can_edit_official_ppmp(user, order)
    return {
        'id': order.id,
        'source_type': 'official',
        'reference_number': order.reference_number,
        'status': order.status,
        'return_stage': ppmp_order_return_reviewer(order) if order.status == 'Returned' else order.return_stage,
        'return_note': order.admin_note if order.status == 'Returned' else None,
        'requester_name': order.requester.full_name if order.requester else '',
        'can_submit': editable and (order.workflow_official or order.status == 'Returned'),
        'is_complete': not missing_fields,
        'missing_fields': missing_fields,
        'workflow_official': bool(order.workflow_official),
        'is_official': bool(order.workflow_official),
        'requested_by': order.requested_by,
        'office_id': order.office_id,
        'may_provide_app_feedback': user.role == 'ADMIN' or (order.requested_by == user.id and order.office_id == user.college_id),
        'may_create_indicative_copy': bool(order.workflow_official and order.status in {'Approved', 'Processing', 'Completed'} and (
            user.role == 'ADMIN' or (order.requested_by == user.id and order.office_id == user.college_id))),
        'save_url': f'/api/reports/ppmp-orders/{order.id}/items',
        'submit_url': f'/api/ppmp-orders/{order.id}/transition',
        'export_base': f'/api/reports/ppmp-orders/{order.id}/export',
        'fiscal_year': order.fiscal_year,
        'ppmp_document_number': order.ppmp_document_number,
        'end_user_or_implementing_unit': (
            order.office.name if order.office and order.office.name else order.office.code if order.office else ''
        ),
        'editable': editable,
        'procurement_types': PPMP_ORDER_TYPES,
        'procurement_methods': PPMP_REPORT_PROCUREMENT_METHODS,
        'fund_sources': PPMP_ORDER_FUND_SOURCES,
        'items': [ppmp_request_report_item(item, order) for item in order.items],
        'history': workflow_history('ppmp_order', order.id),
        'comments': [comment.to_dict() for comment in PPMPComment.query.filter_by(
            wishlist_order_id=order.id).order_by(PPMPComment.id).all()],
    }


def ppmp_request_report_missing_fields(order):
    if not order.items:
        return [{'item_id': None, 'item_name': 'PPMP', 'fields': ['at least one requested item']}]
    errors = []
    for item in order.items:
        fields = []
        for valid, label in (
            (bool((item.item_name or '').strip()), 'item description'),
            (item.project_type in PPMP_ORDER_TYPES, 'project type'),
            (bool(item.quantity is not None and item.quantity > 0), 'quantity greater than zero'),
            (bool((item.unit or '').strip()), 'unit / size'),
            (item.procurement_method in PPMP_REPORT_PROCUREMENT_METHODS, 'recommended procurement mode'),
            (item.pre_procurement_conference is not None, 'pre-procurement conference (Yes/No)'),
            (item.procurement_start is not None, 'procurement start'),
            (item.procurement_end is not None, 'procurement end'),
            (item.delivery_period is not None, 'expected delivery'),
            (item.source_of_funds in PPMP_ORDER_FUND_SOURCES, 'source of funds'),
            (bool(item.estimated_budget is not None and item.estimated_budget >= 0), 'estimated budget'),
        ):
            if not valid:
                fields.append(label)
        if item.procurement_start and item.procurement_end and item.procurement_end < item.procurement_start:
            fields.append('procurement end on or after procurement start')
        if item.procurement_end and item.delivery_period and item.delivery_period < item.procurement_end:
            fields.append('delivery on or after procurement end')
        if fields:
            errors.append({'item_id': item.id, 'item_name': item.item_name or 'Unnamed item', 'fields': fields})
    return errors


def ppmp_request_report_is_complete(order):
    return not ppmp_request_report_missing_fields(order)


@app.route('/api/reports/ppmp-orders/<int:order_id>')
@permission_required('ppmp.report')
def ppmp_request_report_detail(order_id):
    user = current_session_user()
    order, error = authorized_ppmp_request_report(user, order_id, require_pending=False)
    if error:
        return error
    return jsonify(ppmp_request_report_payload(order, user))


def ppmp_request_report_item_changes(data):
    """Validate report fields without changing an item or writing to the database."""
    allowed_fields = {
        'project_type',
        'procurement_method', 'pre_procurement_conference',
        'procurement_start', 'procurement_end', 'delivery_period',
        'source_of_funds', 'remarks',
    }
    if not isinstance(data, dict) or not data or set(data) - allowed_fields:
        raise ValueError('Only Columns 2, 4 through 9, and 12 can be updated in this report.')
    changes = {}
    if 'project_type' in data:
        project_type = str(data.get('project_type') or '').strip()
        if project_type and project_type not in PPMP_ORDER_TYPES:
            raise ValueError('Select a valid Procurement Type.')
        changes['project_type'] = project_type or None
    if 'procurement_method' in data:
        method = str(data.get('procurement_method') or '').strip()
        if method and method not in PPMP_REPORT_PROCUREMENT_METHODS:
            raise ValueError('Select a valid Recommended Mode of Procurement.')
        changes['procurement_method'] = method or None
    if 'pre_procurement_conference' in data:
        value = data.get('pre_procurement_conference')
        if value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError('Select a valid Pre-Procured conference value.')
        changes['pre_procurement_conference'] = (
            None if str(value or '').strip() == ''
            else parse_controlled_boolean(value, 'Pre-Procured conference')
        )
    for field_name, label in (
        ('procurement_start', 'Start of Procurement Activity'),
        ('procurement_end', 'End of Procurement Activity'),
        ('delivery_period', 'Expected Delivery Implementation Period'),
    ):
        if field_name in data:
            value = str(data.get(field_name) or '').strip()
            changes[field_name] = parse_month_value(value, label) if value else None
    if 'source_of_funds' in data:
        source_of_funds = str(data.get('source_of_funds') or '').strip()
        if source_of_funds and source_of_funds not in PPMP_ORDER_FUND_SOURCES:
            raise ValueError('Select a valid Source of Funds.')
        changes['source_of_funds'] = source_of_funds or None
    if 'remarks' in data:
        remarks = str(data.get('remarks') or '').strip()
        if len(remarks) > 5000:
            raise ValueError('Remarks must not exceed 5,000 characters.')
        changes['remarks'] = remarks or None
    return changes


@app.route('/api/reports/ppmp-orders/<int:order_id>/items/<int:item_id>', methods=['PUT'])
@permission_required('ppmp.report')
def update_ppmp_request_report_item(order_id, item_id):
    user = current_session_user()
    order, error = authorized_ppmp_request_report(user, order_id)
    if error:
        return error
    item = PPMPOrderItem.query.filter_by(id=item_id, order_id=order.id).one_or_none()
    if item is None:
        return jsonify({'error': 'Requested item not found in this PPMP Request Record.'}), 404
    data = request.get_json(silent=True)
    try:
        changes = extended_report_changes(sys.modules[__name__], data)
        validate_report_timeline(item, changes)
    except ValueError as error_value:
        return jsonify({'error': str(error_value)}), 400
    for field_name, value in changes.items():
        setattr(item, 'item_name' if field_name == 'general_description' else field_name, value)
    if 'quantity' in changes or 'estimated_budget' in changes:
        item.estimated_unit_cost = (Decimal(item.estimated_budget) / Decimal(item.quantity)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    audit('ppmp_order_item', item.id, 'REPORT_FIELDS_UPDATED', {
        'order_id': order.id, 'fields': sorted(changes),
    })
    db.session.commit()
    return jsonify(ppmp_request_report_item(item, order))


@app.route('/api/reports/ppmp-orders/<int:order_id>/items', methods=['PUT'])
@permission_required('ppmp.report')
def update_ppmp_request_report_items(order_id):
    user = current_session_user()
    order, error = authorized_ppmp_request_report(user, order_id)
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {'items', 'ppmp_document_number'} or 'items' not in data:
        return jsonify({'error': 'Provide report changes to save.'}), 400
    rows = data['items']
    if not isinstance(rows, list):
        return jsonify({'error': 'Report items must be a list.'}), 400
    document_number = None
    if 'ppmp_document_number' in data:
        document_number = data['ppmp_document_number']
        if type(document_number) is not int or not 1 <= document_number <= 999999999:
            return jsonify({'error': 'PPMP document number must be a positive whole number.'}), 400
    if not rows and document_number is None:
        return jsonify({'error': 'Provide at least one report change to save.'}), 400
    validated_rows = []
    item_ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'fields'}:
            return jsonify({'error': 'Each report item must contain an id and editable fields.'}), 400
        item_id = row['id']
        if type(item_id) is not int or item_id <= 0:
            return jsonify({'error': 'Each report item must have a valid integer id.'}), 400
        if item_id in item_ids:
            return jsonify({'error': 'A report item can only be included once per save.'}), 400
        try:
            changes = extended_report_changes(sys.modules[__name__], row['fields'])
        except ValueError as error_value:
            return jsonify({'error': str(error_value)}), 400
        item_ids.add(item_id)
        validated_rows.append((item_id, changes))
    items = {
        item.id: item for item in PPMPOrderItem.query.filter(
            PPMPOrderItem.order_id == order.id,
            PPMPOrderItem.id.in_(item_ids),
        ).all()
    }
    if set(items) != item_ids:
        return jsonify({'error': 'Requested item not found in this PPMP Request Record.'}), 404
    try:
        for item_id, changes in validated_rows:
            validate_report_timeline(items[item_id], changes)
    except ValueError as error_value:
        return jsonify({'error': str(error_value)}), 400
    for item_id, changes in validated_rows:
        item = items[item_id]
        before = ppmp_request_report_item(item, order)
        for field_name, value in changes.items():
            setattr(item, 'item_name' if field_name == 'general_description' else field_name, value)
        if 'quantity' in changes or 'estimated_budget' in changes:
            item.estimated_unit_cost = (Decimal(item.estimated_budget) / Decimal(item.quantity)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        audit('ppmp_order_item', item.id, 'REPORT_FIELDS_UPDATED', {
            'order_id': order.id, 'fields': sorted(changes),
            'before': before, 'after': ppmp_request_report_item(item, order),
        })
    if document_number is not None and document_number != order.ppmp_document_number:
        previous_number = order.ppmp_document_number
        order.ppmp_document_number = document_number
        audit('ppmp_order', order.id, 'REPORT_NUMBER_UPDATED', {
            'from': previous_number, 'to': document_number,
        })
    db.session.commit()
    return jsonify(ppmp_request_report_payload(order, user))


def build_ppmp_order_report(orders):
    status_counts = {status: 0 for status in PPMPOrder.STATUSES}
    by_office = {}
    item_frequency = {}
    monthly_trend = {}
    source_distribution = {
        'PPMP Wishlist Item': 0,
        'CSE Master List': 0,
        'Custom / Unlisted': 0,
    }
    total_quantity = 0.0
    total_amount = 0.0
    for order in orders:
        status_counts[order.status] = status_counts.get(order.status, 0) + 1
        office_label = order.office.code if order.office else 'Unassigned legacy office'
        by_office[office_label] = by_office.get(office_label, 0) + 1
        date_value = order.submitted_at or order.created_at
        period = date_value.strftime('%Y-%m') if date_value else 'Unknown'
        monthly_trend[period] = monthly_trend.get(period, 0) + 1
        for item in order.items:
            quantity = float(item.quantity or 0)
            total_quantity += quantity
            total_amount += float(item.estimated_budget or 0)
            item_frequency[item.item_name] = item_frequency.get(item.item_name, 0) + quantity
            label = item.to_dict()['source_type']
            source_distribution[label] += 1
    pending_statuses = {
        'Requested', 'Pending Admin Approval',
        'Submitted', 'EO Review', 'Procurement Review', 'Returned',
    }
    approved_statuses = {'Approved', 'Processing', 'Completed'}
    return {
        'summary': {
            'total_requests': len(orders),
            'pending_requests': sum(status_counts.get(status, 0) for status in pending_statuses),
            'approved_requests': sum(status_counts.get(status, 0) for status in approved_statuses),
            'rejected_requests': status_counts.get('Rejected', 0),
            'total_ordered_items': total_quantity,
            'total_requested_amount': total_amount,
        },
        'by_status': status_counts,
        'source_distribution': source_distribution,
        'by_office': by_office,
        'item_frequency': dict(sorted(item_frequency.items(), key=lambda row: row[1], reverse=True)[:10]),
        'monthly_trend': dict(sorted(monthly_trend.items())),
        'records': [dict(
            order.to_dict(),
            is_pending_report=order.status in PPMP_REPORT_PENDING_STATUSES,
        ) for order in reversed(orders)],
    }


@app.route('/api/reports/ppmp-orders')
@permission_required('ppmp.report')
def ppmp_order_reports():
    orders, report, error = scoped_ppmp_report_orders(current_session_user())
    if error:
        return error
    payload = build_ppmp_order_report(orders)
    payload['report'] = report.to_dict() if report else None
    return jsonify(payload)


def ppmp_report_export_data():
    user = current_session_user()
    orders, report, error = scoped_ppmp_report_orders(user)
    if error:
        return None, None, None, error
    title = report.title if report else 'Authorized PPMP Items Report'
    return orders, report, title, None


@app.route('/api/reports/ppmp-orders/export/pdf')
@permission_required('ppmp.export')
def export_ppmp_order_report_pdf():
    orders, report, title, error = ppmp_report_export_data()
    if error:
        return error
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), rightMargin=12 * mm, leftMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(xml_escape(title), styles['Title'])]
    if report:
        scope = f"Office: {report.office.code if report.office else ''} | Fiscal Year: {report.fiscal_year or 'All years'}"
        story.append(Paragraph(xml_escape(scope), styles['Normal']))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow():%Y-%m-%d %H:%M UTC}", styles['Normal'],
    ))
    story.append(Spacer(1, 6 * mm))
    rows = [['Reference', 'Office', 'Fiscal Year', 'Submitted', 'Items', 'Amount', 'Status']]
    for order in orders:
        item = order.to_dict()
        rows.append([
            item['reference_number'], item.get('office_code') or item.get('office_name') or '',
            str(item['fiscal_year']), (item.get('submitted_at') or '')[:10],
            f"{float(item.get('total_quantity') or 0):,.2f}",
            f"PHP {float(item.get('total_amount') or 0):,.2f}", item['status'],
        ])
    if len(rows) == 1:
        rows.append(['No authorized PPMP request records.', '', '', '', '', '', ''])
    table = Table(rows, repeatRows=1, colWidths=[42*mm, 30*mm, 20*mm, 25*mm, 20*mm, 34*mm, 30*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#173f73')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#cbd5e1')),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.append(table)
    document.build(story)
    buffer.seek(0)
    audit('ppmp_report', report.id if report else 0, 'EXPORT_PDF', {'rows': len(orders)})
    db.session.commit()
    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                     download_name='authorized_ppmp_report.pdf')


@app.route('/api/reports/ppmp-orders/export/excel')
@permission_required('ppmp.export')
def export_ppmp_order_report_excel():
    orders, report, title, error = ppmp_report_export_data()
    if error:
        return error
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'PPMP Report'
    sheet.append([title])
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=7)
    sheet['A1'].font = Font(bold=True, size=15, color='173F73')
    sheet.append(['Reference', 'Office', 'Fiscal Year', 'Submitted', 'Items', 'Amount', 'Status'])
    for cell in sheet[2]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='173F73')
    for order in orders:
        item = order.to_dict()
        sheet.append([
            item['reference_number'], item.get('office_code') or item.get('office_name') or '',
            item['fiscal_year'], (item.get('submitted_at') or '')[:10],
            float(item.get('total_quantity') or 0), float(item.get('total_amount') or 0), item['status'],
        ])
    sheet.column_dimensions['A'].width = 26
    sheet.column_dimensions['B'].width = 24
    for column in ('C', 'D', 'E', 'F', 'G'):
        sheet.column_dimensions[column].width = 18
    for cell in sheet['F'][2:]:
        cell.number_format = '#,##0.00'
    sheet.freeze_panes = 'A3'
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    audit('ppmp_report', report.id if report else 0, 'EXPORT_EXCEL', {'rows': len(orders)})
    db.session.commit()
    return send_file(
        buffer, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='authorized_ppmp_report.xlsx',
    )


def selected_ppmp_request_export(order_id):
    order, error = authorized_ppmp_request_report(current_session_user(), order_id, require_pending=False)
    if error:
        return None, error
    if not ppmp_request_report_is_complete(order):
        return None, (jsonify({
            'error': 'Complete Columns 2 and 4 through 9 for every requested item before exporting.'
        }), 409)
    return order, None


def selected_ppmp_request_rows(order):
    return [[
        item.item_name,
        item.project_type or '',
        f'{float(item.quantity or 0):g} {item.unit}',
        item.procurement_method or '',
        'Yes' if item.pre_procurement_conference else 'No',
        ppmp_report_month(item.procurement_start),
        ppmp_report_month(item.procurement_end),
        ppmp_report_month(item.delivery_period),
        item.source_of_funds or '',
        float(item.estimated_budget or 0),
        item.supporting_documents or '',
        item.remarks or '',
    ] for item in order.items]


@app.route('/api/reports/ppmp-orders/<int:order_id>/export/pdf')
@permission_required('ppmp.export')
def export_selected_ppmp_request_pdf(order_id=None, *, document=None, indicative=False):
    order = document
    if order is None:
        order, error = selected_ppmp_request_export(order_id)
        if error:
            return error
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A3), rightMargin=7 * mm, leftMargin=7 * mm,
        topMargin=7 * mm, bottomMargin=7 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = styles['Title'].clone('PPMPRequestTitle')
    title_style.fontName = 'Helvetica-Bold'
    title_style.fontSize = 15
    title_style.leading = 18
    title_style.alignment = 1
    title_style.spaceAfter = 0
    body_style = styles['Normal'].clone('PPMPRequestBody')
    body_style.fontSize = 8
    body_style.leading = 10
    cell_style = styles['Normal'].clone('PPMPRequestCell')
    cell_style.fontSize = 5.2
    cell_style.leading = 6.2
    cell_style.wordWrap = 'CJK'
    cell_style.alignment = 1
    description_style = cell_style.clone('PPMPRequestDescription')
    description_style.alignment = 0
    header_style = cell_style.clone('PPMPRequestHeader')
    header_style.fontName = 'Helvetica-Bold'
    header_style.alignment = 1
    logo_path = os.path.join(app.root_path, 'static', 'isu-seal.jpg')
    logo = ReportImage(logo_path, width=20 * mm, height=20 * mm)
    header = Table([
        [logo, Paragraph(f'PROJECT PROCUREMENT MANAGEMENT PLAN (PPMP) NO. {order.ppmp_document_number}', title_style)],
    ], colWidths=[28 * mm, 360 * mm])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    office_name = order.office.name if order.office and order.office.name else order.office.code if order.office else ''
    story = [
        header, Spacer(1, 3 * mm),
        Paragraph('INDICATIVE COPY' if indicative else 'OFFICIAL PPMP', body_style),
        Paragraph(f'<b>Fiscal Year:</b> {order.fiscal_year}', body_style),
        Paragraph(f'<b>End-User or Implementing Unit:</b> {xml_escape(office_name)}', body_style),
        Spacer(1, 3 * mm),
    ]
    report_rows = [[Paragraph(xml_escape(value), header_style) for value in PPMP_REPORT_COLUMNS]]
    for row in selected_ppmp_request_rows(order):
        display = list(row)
        display[9] = f'Php {row[9]:,.2f}'
        report_rows.append([Paragraph(xml_escape(str(value)), description_style if index == 0 else cell_style)
                            for index, value in enumerate(display)])
    total_budget = sum((Decimal(item.estimated_budget or 0) for item in order.items), Decimal('0.00'))
    report_rows.append([''] * 8 + [Paragraph('<b>TOTAL BUDGET</b>', header_style),
                                     Paragraph(f'<b>Php {total_budget:,.2f}</b>', header_style), '', ''])
    column_widths = [48, 39, 27, 48, 31, 25, 25, 31, 25, 34, 47, 42]
    report_table = Table(
        report_rows, repeatRows=1, colWidths=[value * mm for value in column_widths],
    )
    report_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D9EAF7')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('GRID', (0, 0), (-1, -1), 0.45, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
        ('ALIGN', (4, 1), (9, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(report_table)
    document.build(story)
    buffer.seek(0)
    audit('indicative_ppmp' if indicative else 'ppmp_order', order.id, 'EXPORT_12_COLUMN_PDF', {'item_count': len(order.items)})
    db.session.commit()
    return send_file(
        buffer, mimetype='application/pdf', as_attachment=True,
        download_name=f'{order.reference_number}_PPMP.pdf',
    )


@app.route('/api/reports/ppmp-orders/<int:order_id>/export/excel')
@permission_required('ppmp.export')
def export_selected_ppmp_request_excel(order_id=None, *, document=None, indicative=False):
    order = document
    if order is None:
        order, error = selected_ppmp_request_export(order_id)
        if error:
            return error
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'PPMP Report'
    office_name = order.office.name if order.office and order.office.name else order.office.code if order.office else ''
    sheet.append([f'PROJECT PROCUREMENT MANAGEMENT PLAN (PPMP) NO. {order.ppmp_document_number}'])
    sheet.merge_cells('A1:L1')
    sheet['A1'].font = Font(bold=True, size=14)
    sheet['A1'].alignment = Alignment(horizontal='center', vertical='center')
    sheet.append(['Fiscal Year:', order.fiscal_year])
    sheet.append(['End-User or Implementing Unit:', office_name])
    sheet.append([])
    sheet.append(list(PPMP_REPORT_COLUMNS))
    for row in selected_ppmp_request_rows(order):
        sheet.append(row)
    total_budget = sum((Decimal(item.estimated_budget or 0) for item in order.items), Decimal('0.00'))
    sheet.append([''] * 8 + ['TOTAL BUDGET', float(total_budget), '', ''])
    sheet.cell(4, 1, 'INDICATIVE COPY' if indicative else 'OFFICIAL PPMP')
    for cell in sheet[5]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='D9EAF7')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'),
        )
    for row in sheet.iter_rows(min_row=6, max_col=12):
        for index, cell in enumerate(row):
            cell.alignment = Alignment(horizontal='left' if index == 0 else 'center', vertical='top', wrap_text=True)
            cell.border = Border(
                left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin'),
            )
        row[9].number_format = '"Php "#,##0.00'
    widths = [42, 35, 24, 45, 28, 22, 22, 28, 22, 30, 40, 35]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[5].height = 90
    sheet.freeze_panes = 'A6'
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_area = f'A1:L{sheet.max_row}'
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    audit('indicative_ppmp' if indicative else 'ppmp_order', order.id, 'EXPORT_12_COLUMN_EXCEL', {'item_count': len(order.items)})
    db.session.commit()
    return send_file(
        buffer, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=f'{order.reference_number}_PPMP.xlsx',
    )


@app.route('/api/surveys', methods=['GET', 'POST'])
def surveys():
    user = current_session_user()
    if request.method == 'GET':
        query = Survey.query
        if user.role not in {'ADMIN', 'EO'}:
            query = query.join(SurveyRecipient).filter(SurveyRecipient.college_id == user.college_id)
        result = []
        for survey in query.order_by(Survey.created_at.desc()).all():
            item = survey.to_dict()
            item['recipients'] = [row.to_dict() for row in SurveyRecipient.query.filter_by(survey_id=survey.id).all()]
            result.append(item)
        return jsonify(result)
    if not has_permission(user, 'survey.manage'):
        return jsonify({'error': 'Only EO/Academic Affairs can create surveys.'}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    college_ids = list(dict.fromkeys(data.get('college_ids') or []))
    if not title or not college_ids:
        return jsonify({'error': 'A title and at least one college are required.'}), 400
    colleges = College.query.filter(College.id.in_(college_ids), College.is_active.is_(True)).all()
    if len(colleges) != len(college_ids):
        return jsonify({'error': 'One or more selected colleges are invalid.'}), 400
    survey = Survey(title=title, description=(data.get('description') or '').strip() or None,
                    fiscal_year=int(data.get('fiscal_year') or datetime.utcnow().year), created_by=user.id)
    db.session.add(survey)
    db.session.flush()
    for college in colleges:
        db.session.add(SurveyRecipient(survey_id=survey.id, college_id=college.id))
        add_notification(User.query.filter_by(college_id=college.id, is_active=True).all(),
                         'New optional PPMP survey', title)
    audit('survey', survey.id, 'CREATE', {'college_ids': college_ids})
    db.session.commit()
    return jsonify(survey.to_dict()), 201


@app.route('/api/surveys/<int:survey_id>/respond', methods=['POST'])
@login_required
def respond_to_survey(survey_id):
    user = current_session_user()
    recipient = SurveyRecipient.query.filter_by(survey_id=survey_id, college_id=user.college_id).first()
    survey = db.session.get(Survey, survey_id)
    if recipient is None or survey is None or not survey.is_enabled:
        return jsonify({'error': 'This survey is unavailable for your college.'}), 403
    response = ((request.get_json(silent=True) or {}).get('response') or '').strip()
    if not response:
        return jsonify({'error': 'A response is required.'}), 400
    recipient.response, recipient.responded_by, recipient.responded_at = response, user.id, datetime.utcnow()
    audit('survey', survey_id, 'RESPOND', {'college_id': user.college_id})
    db.session.commit()
    return jsonify(recipient.to_dict())


@app.route("/api/summary")
def summary():
    user = current_session_user()
    items = [item for item in PPMPItem.query.all() if can_access_ppmp(user, item)]
    return jsonify(get_summary(items=items))


@app.route('/api/dashboard/ppmp')
@permission_required('ppmp.view')
def ppmp_dashboard_data():
    user = current_session_user()
    items = [item for item in PPMPItem.query.all() if can_access_ppmp(user, item)]
    status_counts = {status: 0 for status in PPMPItem.STATUSES}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    item_ids = [item.id for item in items]
    consolidated_ids = set()
    if item_ids:
        consolidated_ids = {row.ppmp_item_id for row in ConsolidationSource.query.filter(
            ConsolidationSource.ppmp_item_id.in_(item_ids)).all()}
    request_query = PPMPSubmissionRequest.query
    if user.role not in {'ADMIN', 'EO', 'AA', 'PROCUREMENT', 'BUDGET'}:
        request_query = request_query.filter_by(college_id=user.college_id)
    request_counts = {status: request_query.filter_by(status=status).count()
                      for status in PPMPSubmissionRequest.STATUSES}
    record_query = visible_ppmp_records()
    if is_ppmp_office_role(user.role):
        record_query = record_query.filter_by(office_id=user.college_id)
    records = record_query.order_by(PPMPRecord.updated_at.desc()).all()
    record_counts = {status: 0 for status in PPMPRecord.STATUSES}
    for record in records:
        record_counts[record.status] = record_counts.get(record.status, 0) + 1
    total_record_items = sum(len(record.included_items) for record in records)
    order_query = PPMPOrder.query
    if is_ppmp_office_role(user.role):
        order_query = order_query.filter_by(office_id=user.college_id)
    wishlist_order_counts = {status: order_query.filter_by(status=status).count()
                             for status in PPMPOrder.STATUSES}
    return jsonify({
        'total_items': len(items),
        'total_record_items': total_record_items,
        'available_master_items': WishlistItem.query.filter_by(status='Available').count(),
        'status_counts': status_counts,
        'request_counts': request_counts,
        'record_counts': record_counts,
        'total_records': len(records),
        'order_pending': sum(
            wishlist_order_counts.get(status, 0)
            for status in (
                'Requested', 'Pending Admin Approval',
                'Submitted', 'EO Review', 'Procurement Review', 'Returned',
            )
        ),
        'wishlist_order_counts': wishlist_order_counts,
        'eligible_for_consolidation': sum(1 for item in items if item.status == 'Approved' and item.id not in consolidated_ids),
        'consolidated_items': len(consolidated_ids),
        'recent_records': [record.to_dict(include_items=False) for record in records[:5]],
        'recent_items': [item.to_dict() for item in sorted(items, key=lambda row: row.updated_at or row.created_at, reverse=True)[:5]],
    })


from flask import has_request_context
from models import APPBatchLink, APPItemContribution, APPWorkflowRegistry
from procurement_workflow import (
    APP_OPEN_STATUSES, APP_REVIEW_ROLES, INSTITUTION_OFFICE,
    app_snapshot, apply_contribution_update, export_office_contributions,
    export_project_title, materialize_batch_sources, precise_number,
    prepare_contribution_update, source_snapshot, validate_row_allocations,
)


def can_access_app(user, plan):
    return bool(user and has_permission(user, 'app.view'))


def can_edit_app(user, plan):
    return bool(
        user and user.role == 'ADMIN' and has_permission(user, 'app.edit')
        and plan.status in {'Draft', 'Returned'}
    )


def can_complete_added_app_item(user, plan, item):
    return bool(user and user.role == 'ADMIN'
                and plan.status in {'Submitted', 'Under Review', 'For Admin Approval'}
                and item.id in (plan.source_details or {}).get('pending_item_ids', []))


def can_set_app_procurement_mode(user, plan, item):
    """BAC owns this APP field, including new rows added after its review."""
    return bool(
        user and user.role == 'BAC CHAIRMAN' and has_permission(user, 'app.review')
        and plan.status in {'Submitted', 'Under Review', 'For Admin Approval'}
        and (expected_app_reviewer(plan) == 'BAC CHAIRMAN' or (
            not item.mode_of_procurement
            and item.id in (plan.source_details or {}).get('pending_bac_mode_item_ids', [])
        ))
    )


def sync_app_mode_tasks(plan):
    """Track BAC assignments separately from the fields Admin must complete."""
    pending_ids = sorted(item.id for item in plan.items if not item.mode_of_procurement)
    plan.source_details = {**(plan.source_details or {}), 'pending_bac_mode_item_ids': pending_ids}
    resolve_notification_tasks('app', plan.id, action_stage='BAC_MODE')
    if pending_ids and plan.status in {'Submitted', 'Under Review', 'For Admin Approval'}:
        notify_roles(('BAC CHAIRMAN',), 'APP procurement modes need BAC assignment',
                     f'{app_notification_label(plan)} has {len(pending_ids)} row(s) requiring your Mode of Procurement selection. '
                     'Open the APP and save each selection before review can proceed.',
                     target_type='app', target_id=plan.id, action_stage='BAC_MODE')


def parse_app_item(data):
    text_fields = {
        'project_title': (3000, True),
        'implementing_unit': (200, True),
        'general_description': (120, True),
        'bid_evaluation_criteria': (3000, False),
        'source_of_fund': (120, True),
        'procurement_strategy_tools': (5000, False),
        'remarks': (5000, False),
    }
    values = {}
    for field, (limit, required) in text_fields.items():
        value = str(data.get(field) or '').strip()
        if required and not value:
            raise ValueError(f'{field.replace("_", " ").title()} is required.')
        if len(value) > limit:
            raise ValueError(f'{field.replace("_", " ").title()} must not exceed {limit:,} characters.')
        values[field] = value or None
    if values['general_description'] not in set(PPMPRecordItem.PROJECT_TYPES) | set(PPMP_ORDER_TYPES) | set(PPMPItem.TYPES):
        raise ValueError('Select a valid general project description.')
    if values['source_of_fund'] not in set(PPMPRecordItem.FUND_SOURCES) | set(PPMP_ORDER_FUND_SOURCES):
        raise ValueError('Select a valid source of fund.')
    early_value = data.get('early_procurement_activity')
    values['early_procurement_activity'] = (
        None if early_value in {None, ''}
        else parse_controlled_boolean(early_value, 'Early procurement activity')
    )
    start_value, end_value = data.get('procurement_start'), data.get('procurement_end')
    values['procurement_start'] = parse_month_value(start_value, 'Procurement start') if start_value else None
    values['procurement_end'] = parse_month_value(end_value, 'Procurement end') if end_value else None
    if (values['procurement_start'] and values['procurement_end']
            and values['procurement_end'] < values['procurement_start']):
        raise ValueError('Procurement end cannot be earlier than procurement start.')
    values['estimated_budget'] = precise_number(data.get('estimated_budget'), 'Estimated/approved budget', money=True)
    return values


def app_item_validation_error(item, index=1, *, require_procurement_mode=True):
    if (require_procurement_mode
            and item.mode_of_procurement not in set(APP_MODES_OF_PROCUREMENT) | set(PPMP_REPORT_PROCUREMENT_METHODS)):
        return f'BAC Chairman must select and save a valid Mode of Procurement for APP row {index}.'
    if (not item.project_title or not item.implementing_unit
                or item.general_description not in set(PPMPRecordItem.PROJECT_TYPES) | set(PPMP_ORDER_TYPES) | set(PPMPItem.TYPES)
                or item.early_procurement_activity is None
                or not item.bid_evaluation_criteria
                or item.source_of_fund not in set(PPMPRecordItem.FUND_SOURCES) | set(PPMP_ORDER_FUND_SOURCES)
                or Decimal(item.estimated_budget or 0) < 0):
        return f'APP row {index} is incomplete or contains an invalid controlled value.'
    as_needed = bool(item.contributions) and all(
        contribution.source_snapshot.get('schedule_as_needed') for contribution in item.contributions)
    if (not item.procurement_start or not item.procurement_end) and not as_needed:
        return f'APP row {index} requires procurement start and end months.'
    if item.procurement_start and item.procurement_end and item.procurement_end < item.procurement_start:
        return f'APP row {index} contains an invalid procurement timeline.'
    try:
        validate_row_allocations(item)
    except ValueError as error:
        return f'APP row {index}: {error}'
    return None


def validate_app_for_submission(plan, *, require_procurement_mode=True):
    if not plan.sections:
        return 'Add at least one APP section before submitting.'
    if not plan.items:
        return 'Add at least one APP item before submitting.'
    for index, item in enumerate(plan.items, 1):
        error = app_item_validation_error(item, index, require_procurement_mode=require_procurement_mode)
        if error:
            return error
    return None


def materialize_app_items(plan, batch_sources, creator):
    return materialize_batch_sources(plan, batch_sources, creator)


def app_audit_snapshot(plan, action, details=None):
    db.session.flush()
    payload = dict(details or {})
    payload.update({'revision': plan.revision, 'snapshot': app_snapshot(plan)})
    audit('app', plan.id, action, payload)


def app_history_dict(plan):
    entries = WorkflowAuditLog.query.filter_by(entity_type='app', entity_id=plan.id).order_by(WorkflowAuditLog.id).all()
    return [{
        'id': row.id, 'action': row.action, 'details': row.details or {},
        'revision': (row.details or {}).get('revision'),
        'snapshot': (row.details or {}).get('snapshot'),
        'performed_by_name': row.performer.full_name if row.performer else 'System',
        'performed_by_role': row.performer.role if row.performer else None,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    } for row in entries]


def app_detail_dict(plan):
    result = plan.to_dict(include_details=True)
    result['expected_reviewer'] = expected_app_reviewer(plan)
    result['can_edit'] = can_edit_app(current_session_user(), plan) if has_request_context() else False
    result['audit_history'] = app_history_dict(plan)
    result['review_sequence'] = list(APP_REVIEW_ROLES)
    batch_ids = [link.batch_id for link in plan.batch_links]
    if not batch_ids and plan.consolidation_batch_id is not None:
        batch_ids = [plan.consolidation_batch_id]
    result['source'] = {
        'source_type': plan.source_type,
        'source_details': plan.source_details or {},
        'consolidation_batch_id': plan.consolidation_batch_id,
        'app_cycle': plan.consolidation_batch.app_cycle if plan.consolidation_batch else None,
        'fiscal_year': plan.consolidation_batch.fiscal_year if plan.consolidation_batch else None,
        'consolidated_item_count': (
            ConsolidationSource.query.filter(ConsolidationSource.batch_id.in_(batch_ids)).count()
            if batch_ids else 0
        ),
        'batch_ids': batch_ids,
    }
    active_user = current_session_user() if has_request_context() else None
    items_by_id = {item.id: item for item in plan.items}
    for section in result.get('sections', []):
        for row in section.get('items', []):
            row['schedule_as_needed'] = bool(row.get('contributions')) and all(
                entry['source_snapshot'].get('schedule_as_needed') for entry in row['contributions']
            )
            row['is_pending_completion'] = row['id'] in (plan.source_details or {}).get('pending_item_ids', [])
            row['can_edit'] = result['can_edit'] or bool(
                has_request_context() and current_session_user() and current_session_user().role == 'ADMIN'
                and row['is_pending_completion'] and plan.status in {'Submitted', 'Under Review', 'For Admin Approval'})
            row['can_set_procurement_mode'] = can_set_app_procurement_mode(active_user, plan, items_by_id[row['id']])
    return result


def expected_app_reviewer(plan):
    if plan.status in {'Approved', 'Finalized', 'Rejected', 'Imported'}:
        return None
    if plan.current_review_role in APP_REVIEW_ROLES:
        return plan.current_review_role
    if plan.status == 'Returned' and plan.return_review_role in APP_REVIEW_ROLES:
        return plan.return_review_role
    history = APPApproval.query.filter_by(app_id=plan.id).order_by(APPApproval.id).all()
    if plan.status == 'Returned':
        returned = next((row for row in reversed(history) if row.action == 'RETURN'), None)
        if returned:
            return returned.reviewer_role or (returned.performer.role if returned.performer else 'BAC CHAIRMAN')
    approved_roles = {
        approval.reviewer_role or approval.performer.role
        for approval in history if approval.action == 'APPROVE' and (approval.reviewer_role or approval.performer)
    }
    return next((role for role in APP_REVIEW_ROLES if role not in approved_roles), 'ADMIN')


@app.route('/api/dashboard/app')
@permission_required('app.view')
def app_dashboard_data():
    user = current_session_user()
    plans = AnnualProcurementPlan.query.order_by(AnnualProcurementPlan.updated_at.desc()).all()
    status_counts = {status: 0 for status in AnnualProcurementPlan.STATUSES}
    for plan in plans:
        status_counts[plan.status] = status_counts.get(plan.status, 0) + 1
    pending_actions = 0
    for plan in plans:
        if user.role == 'ADMIN' and plan.status in {'Draft', 'Returned'}:
            pending_actions += 1
        elif plan.status == 'Under Review' and expected_app_reviewer(plan) == user.role:
            pending_actions += 1
        elif plan.status == 'For Admin Approval' and user.role == 'ADMIN':
            pending_actions += 1
    return jsonify({
        'total_plans': len(plans),
        'status_counts': status_counts,
        'app_count': sum(1 for plan in plans if plan.plan_type == 'APP'),
        'app_cse_count': sum(1 for plan in plans if plan.plan_type == 'APP_CSE'),
        'pending_actions': pending_actions,
        'consolidation_batches': ConsolidationBatch.query.count(),
        'consolidated_sources': ConsolidationSource.query.count(),
        'recent_plans': [plan.to_dict() for plan in plans[:5]],
    })


@app.route("/api/consolidated")
@roles_required('ADMIN')
def consolidated():
    result = []
    for college in College.query.filter_by(is_active=True).order_by(College.code):
        items = [item.to_dict() for item in college.ppmp_items.order_by(PPMPItem.id.desc()).all()]
        by_fund, by_mode = {}, {}
        for item in items:
            by_fund[item["fund_source"]] = by_fund.get(item["fund_source"], 0) + item["total_cost"]
            by_mode[item["mode_of_procurement"]] = by_mode.get(item["mode_of_procurement"], 0) + item["total_cost"]
        result.append({"college_id": college.id, "college_code": college.code, "college_name": college.name,
                       "items": items, "total": sum(item["total_cost"] for item in items),
                       "by_fund": by_fund, "by_mode": by_mode, "item_count": len(items)})
    return jsonify(result)


def consolidation_item_dict(item):
    result = item.to_dict()
    result.update(source_snapshot(item))
    # Keep ordinary API numbers while the saved source snapshot uses exact decimals.
    result['quantity'] = float(item.quantity or 0)
    result['estimated_budget'] = float(Decimal(result['estimated_budget']))
    result['consolidation_batch_id'] = None
    return result


def consolidation_batch_dict(batch):
    sources = ConsolidationSource.query.filter_by(batch_id=batch.id).order_by(ConsolidationSource.id).all()
    link = APPBatchLink.query.filter_by(batch_id=batch.id).first()
    plan = link.app if link else AnnualProcurementPlan.query.filter_by(consolidation_batch_id=batch.id).first()
    return {
        'id': batch.id, 'fiscal_year': batch.fiscal_year, 'app_cycle': batch.app_cycle,
        'created_at': batch.created_at.isoformat() if batch.created_at else None,
        'item_count': len(sources), 'source_ppmp_item_ids': [source.ppmp_item_id for source in sources],
        'offices': sorted({source.ppmp_item.college.code for source in sources if source.ppmp_item.college}),
        'sources': [consolidation_item_dict(source.ppmp_item) for source in sources],
        'app_id': plan.id if plan else None, 'app_status': plan.status if plan else None,
        'app_revision': plan.revision if plan else None,
    }


@app.route('/api/consolidation-eligible')
@roles_required('ADMIN')
def consolidation_eligible():
    fiscal_year = request.args.get('fiscal_year', type=int)
    if request.args.get('fiscal_year') and fiscal_year is None:
        return jsonify({'error': 'Fiscal year must be an integer.'}), 400
    consolidated_ids = db.session.query(ConsolidationSource.ppmp_item_id)
    query = PPMPItem.query.filter(PPMPItem.status == 'Approved', ~PPMPItem.id.in_(consolidated_ids))
    approved_items = query.all()
    years = sorted({
        item.fiscal_year for item in approved_items
        if PPMPOrderItem.query.join(PPMPOrder).filter(
            PPMPOrderItem.ppmp_item_id == item.id,
            PPMPOrder.workflow_official.is_(True), PPMPOrder.status == 'Approved',
        ).first()
    })
    if fiscal_year is not None:
        query = query.filter_by(fiscal_year=fiscal_year)
    items, errors = [], []
    for item in query.order_by(PPMPItem.fiscal_year, PPMPItem.college_id, PPMPItem.id).all():
        source = PPMPOrderItem.query.filter_by(ppmp_item_id=item.id).first()
        if not source or not source.order.workflow_official or source.order.status != 'Approved':
            continue
        try:
            items.append(consolidation_item_dict(item))
        except ValueError as error:
            errors.append({'ppmp_item_id': item.id, 'error': str(error)})
    return jsonify({'items': items, 'fiscal_years': years, 'invalid_sources': errors})


@app.route("/api/consolidation-batches", methods=["GET", "POST"])
@roles_required('ADMIN')
def consolidation_batches():
    if request.method == "GET":
        batches = ConsolidationBatch.query.order_by(ConsolidationBatch.created_at.desc()).all()
        return jsonify([consolidation_batch_dict(batch) for batch in batches])
    data = request.get_json(silent=True) or {}
    fiscal_year = data.get('fiscal_year')
    item_ids = data.get("ppmp_item_ids") or []
    order_ids = data.get('ppmp_order_ids') or []
    if (type(fiscal_year) is not int or not 2026 <= fiscal_year <= 9999
            or not isinstance(item_ids, list) or not isinstance(order_ids, list)
            or any(type(value) is not int for value in item_ids + order_ids)
            or not (item_ids or order_ids)):
        return jsonify({'error': 'Select a fiscal year from 2026 onward and at least one approved PPMP source.'}), 400
    if order_ids:
        orders = PPMPOrder.query.filter(PPMPOrder.id.in_(set(order_ids))).order_by(PPMPOrder.id).with_for_update().all()
        if len(orders) != len(set(order_ids)) or any(
            not order.workflow_official or order.status != 'Approved' or order.fiscal_year != fiscal_year
            or not order.items or any(row.ppmp_item_id is None for row in order.items)
            for order in orders
        ):
            return jsonify({'error': 'Select only final approved official PPMPs from this fiscal year.'}), 409
        item_ids += [row.ppmp_item_id for order in orders for row in order.items]
    item_ids = sorted(set(item_ids))
    items = PPMPItem.query.filter(PPMPItem.id.in_(item_ids)).order_by(PPMPItem.id).with_for_update().all()
    if len(items) != len(item_ids):
        return jsonify({'error': 'One or more PPMP source items no longer exist.'}), 409
    if any(item.status != 'Approved' or item.fiscal_year != fiscal_year for item in items):
        return jsonify({'error': 'Every selected PPMP item must be approved and match the batch fiscal year.'}), 409
    try:
        for item in items:
            source_snapshot(item)
            source = PPMPOrderItem.query.filter_by(ppmp_item_id=item.id).first()
            if not source or not source.order.workflow_official or source.order.status != 'Approved':
                raise ValueError('Every source must belong to a designated, finally approved official PPMP.')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    existing = {source.ppmp_item_id for source in ConsolidationSource.query.filter(ConsolidationSource.ppmp_item_id.in_(item_ids)).all()}
    if existing:
        return jsonify({"error": "One or more PPMP items have already been consolidated.", "item_ids": sorted(existing)}), 409
    batch = ConsolidationBatch(fiscal_year=fiscal_year, app_cycle=f'BATCH-{secrets.token_hex(12).upper()}', created_by=current_session_user().id)
    db.session.add(batch)
    try:
        db.session.flush()
        for item in items:
            db.session.add(ConsolidationSource(batch_id=batch.id, ppmp_item_id=item.id))
        db.session.flush()
        audit('consolidation_batch', batch.id, 'CREATE', {
            'ppmp_item_ids': item_ids, 'sources': [source_snapshot(item) for item in items],
        })
        notify_offices({item.college_id for item in items}, 'PPMP selected for APP consolidation',
                       f'Admin included your approved PPMP items in consolidation batch #{batch.id}, FY {fiscal_year}.')
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'These PPMP sources were consolidated concurrently. Refresh the eligible list.'}), 409
    return jsonify(consolidation_batch_dict(batch)), 201


@app.route("/api/apps", methods=["GET", "POST"])
def annual_procurement_plans():
    user = current_session_user()
    if request.method == "GET":
        if not has_permission(user, 'app.view'):
            return jsonify({"error": "You do not have permission to view APP records."}), 403
        records = []
        for plan in AnnualProcurementPlan.query.order_by(AnnualProcurementPlan.created_at.desc()):
            record = plan.to_dict()
            record['expected_reviewer'] = expected_app_reviewer(plan)
            records.append(record)
        return jsonify(records)
    if user is None or user.role != 'ADMIN':
        return jsonify({'error': 'Only Admin may create or extend consolidated APP drafts.'}), 403
    data = request.get_json(silent=True) or {}
    batch_id = data.get('batch_id', data.get('consolidation_batch_id'))
    batch = ConsolidationBatch.query.filter_by(id=batch_id).with_for_update().first() if type(batch_id) is int else None
    if batch is None or data.get('plan_type', 'APP') != 'APP':
        return jsonify({'error': 'Select a valid consolidation batch for the institution-wide APP.'}), 400
    if data.get('fiscal_year', batch.fiscal_year) != batch.fiscal_year:
        return jsonify({'error': 'APP and consolidation fiscal years must match.'}), 400
    if APPBatchLink.query.filter_by(batch_id=batch.id).first() or AnnualProcurementPlan.query.filter_by(consolidation_batch_id=batch.id).first():
        return jsonify({'error': 'This batch has already been attached to an APP.'}), 409
    batch_sources = ConsolidationSource.query.filter_by(batch_id=batch.id).order_by(ConsolidationSource.id).all()
    if not batch_sources:
        return jsonify({'error': 'The selected consolidation batch contains no approved source items.'}), 400
    source_ids = [source.ppmp_item_id for source in batch_sources]
    PPMPItem.query.filter(PPMPItem.id.in_(source_ids)).order_by(PPMPItem.id).with_for_update().all()
    if APPItemContribution.query.filter(APPItemContribution.source_ppmp_item_id.in_(source_ids)).first():
        return jsonify({'error': 'This batch contains a source already included in an APP.'}), 409
    plan = (AnnualProcurementPlan.query.filter(
        AnnualProcurementPlan.workflow_version == 2,
        AnnualProcurementPlan.fiscal_year == batch.fiscal_year,
        AnnualProcurementPlan.status.in_(APP_OPEN_STATUSES),
    ).order_by(AnnualProcurementPlan.id.desc()).with_for_update().first())
    extending = plan is not None
    try:
        if plan is None:
            registries = APPWorkflowRegistry.query.filter_by(fiscal_year=batch.fiscal_year).order_by(APPWorkflowRegistry.sequence).with_for_update().all()
            sequence = max((registry.sequence for registry in registries), default=-1) + 1
            annual = next((registry.app for registry in registries if registry.sequence == 0), None)
            if sequence and (annual is None or annual.status not in {'Approved', 'Finalized'}):
                return jsonify({'error': 'The annual APP must be finally approved before creating a supplemental APP.'}), 409
            plan = AnnualProcurementPlan(
                office=INSTITUTION_OFFICE if not sequence else f'{INSTITUTION_OFFICE} - SUPPLEMENTAL #{sequence}',
                fiscal_year=batch.fiscal_year, plan_type='APP', workflow_version=2,
                consolidation_batch_id=batch.id, source_type='CONSOLIDATION', revision=1,
                supplemental_parent_id=annual.id if sequence else None,
                source_details={'institution_wide': True, 'supplemental_number': sequence},
                created_by=user.id, remarks=str(data.get('remarks') or '').strip() or None,
            )
            db.session.add(plan)
            db.session.flush()
            db.session.add(APPWorkflowRegistry(app_id=plan.id, fiscal_year=batch.fiscal_year, sequence=sequence))
        else:
            plan.revision = (plan.revision or 1) + 1
        db.session.add(APPBatchLink(app=plan, batch_id=batch.id, added_by=user.id))
        db.session.flush()
        previous_item_ids = {item.id for item in plan.items}
        snapshots = materialize_app_items(plan, batch_sources, user)
        if extending and plan.status in {'Submitted', 'Under Review', 'For Admin Approval'}:
            pending = set((plan.source_details or {}).get('pending_item_ids', []))
            pending.update(item.id for item in plan.items if item.id not in previous_item_ids
                           and app_item_validation_error(item, require_procurement_mode=False))
            plan.source_details = {**(plan.source_details or {}), 'pending_item_ids': sorted(pending)}
        sync_app_mode_tasks(plan)
        app_audit_snapshot(plan, 'APP_BATCH_ADDED' if extending else 'APP_DRAFT_CREATED', {
            'consolidation_batch_id': batch.id,
            'source_ppmp_item_ids': source_ids, 'added_sources': snapshots,
            'continuing_reviewer': expected_app_reviewer(plan) if extending else None,
            'note': str(data.get('note') or '').strip() or None,
        })
        if extending and plan.status in {'Under Review', 'For Admin Approval', 'Submitted'}:
            notify_roles((expected_app_reviewer(plan),), 'APP batch added during review',
                         f'{app_notification_label(plan)} includes new source items and requires your review. Completed reviews remain recorded.',
                         target_type='app', target_id=plan.id, action_stage=f'REVIEW:{expected_app_reviewer(plan)}')
        notify_app_offices(plan, 'APP batch added' if extending else 'APP draft prepared',
                           f'{app_notification_label(plan)} now includes approved PPMP items from your office or college. '
                           f'Current status: {plan.status}.')
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Another action attached this batch or created this fiscal-year APP. Refresh and try again.'}), 409
    except ValueError as error:
        db.session.rollback()
        return jsonify({'error': str(error)}), 400
    return jsonify(app_detail_dict(plan)), 200 if extending else 201


@app.route('/api/apps/metadata')
@permission_required('app.view')
def app_metadata():
    return jsonify({
        'modes_of_procurement': list(dict.fromkeys((*APP_MODES_OF_PROCUREMENT, *PPMP_REPORT_PROCUREMENT_METHODS))),
        'early_procurement_options': ('Yes', 'No'),
        'sources_of_fund': list(dict.fromkeys((*PPMPRecordItem.FUND_SOURCES, *PPMP_ORDER_FUND_SOURCES))),
        'general_descriptions': list(dict.fromkeys((*PPMPRecordItem.PROJECT_TYPES, *PPMP_ORDER_TYPES, *PPMPItem.TYPES))),
        'review_sequence': list(APP_REVIEW_ROLES),
        'suggested_sections': (
            'General Requirements',
            'Miscellaneous Items (for Direct Acquisition only) Sec 32.2 of RA No. 12009',
            'Common Use Supplies and Equipment (CSE)',
            'Capital Outlay',
        ),
    })


@app.route('/api/apps/<int:app_id>')
@permission_required('app.view')
def app_detail(app_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    if not can_access_app(user, plan):
        return jsonify({'error': 'You are not authorized to view this APP record.'}), 403
    return jsonify(app_detail_dict(plan))


@app.route('/api/apps/<int:app_id>/history')
@permission_required('app.view')
def app_history(app_id):
    plan = db.session.get(AnnualProcurementPlan, app_id)
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    return jsonify({'audit_history': app_history_dict(plan), 'approval_history': [row.to_dict() for row in plan.approvals]})


@app.route('/api/apps/<int:app_id>/sections', methods=['POST'])
@permission_required('app.edit')
def create_app_section(app_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    if not can_edit_app(user, plan):
        return jsonify({'error': 'Only Admin may edit an APP while Draft or Returned.'}), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 180:
        return jsonify({'error': 'Section name is required and must not exceed 180 characters.'}), 400
    sort_order = max((section.sort_order for section in plan.sections), default=0) + 10
    section = APPSection(app_id=plan.id, name=name, sort_order=sort_order, created_by=user.id)
    db.session.add(section)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'This APP already contains a section with that name.'}), 409
    plan.revision = (plan.revision or 1) + 1
    db.session.expire(plan, ['sections'])
    app_audit_snapshot(plan, 'APP_SECTION_ADDED', {'section_id': section.id, 'name': name})
    db.session.commit()
    return jsonify(section.to_dict()), 201


@app.route('/api/apps/<int:app_id>/sections/<int:section_id>', methods=['DELETE'])
@permission_required('app.edit')
def delete_app_section(app_id, section_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    section = APPSection.query.filter_by(id=section_id, app_id=app_id).first()
    if plan is None or section is None:
        return jsonify({'error': 'APP section not found.'}), 404
    if not can_edit_app(user, plan):
        return jsonify({'error': 'Only Admin may edit an APP while Draft or Returned.'}), 403
    if section.items:
        return jsonify({'error': 'Move or remove this section’s APP items before deleting it.'}), 409
    section_name = section.name
    db.session.delete(section)
    db.session.flush()
    db.session.expire(plan, ['sections'])
    plan.revision = (plan.revision or 1) + 1
    app_audit_snapshot(plan, 'APP_SECTION_REMOVED', {'section_id': section_id, 'name': section_name})
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/apps/<int:app_id>/items', methods=['POST'])
@permission_required('app.edit')
def create_app_item(app_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    if not can_edit_app(user, plan):
        return jsonify({'error': 'Only Admin may edit an APP while Draft or Returned.'}), 403
    if plan.workflow_version == 2:
        return jsonify({'error': 'Add approved PPMP sources through a consolidation batch to retain office allocations.'}), 409
    data = request.get_json(silent=True) or {}
    if 'mode_of_procurement' in data:
        return jsonify({'error': 'Only BAC Chairman may set the APP Mode of Procurement during review.'}), 403
    section = APPSection.query.filter_by(id=data.get('section_id'), app_id=plan.id).first()
    if section is None:
        return jsonify({'error': 'Select a valid APP section.'}), 400
    try:
        values = parse_app_item(data)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    item = APPItem(app=plan, section=section, created_by=user.id, mode_of_procurement='', **values)
    db.session.add(item)
    db.session.flush()
    plan.revision = (plan.revision or 1) + 1
    sync_app_mode_tasks(plan)
    app_audit_snapshot(plan, 'APP_ITEM_ADDED', {'app_item_id': item.id, 'section_id': section.id})
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route('/api/apps/<int:app_id>/items/<int:item_id>', methods=['PUT', 'DELETE'])
@permission_required('app.edit')
def update_app_item(app_id, item_id):
    plan, user = AnnualProcurementPlan.query.filter_by(id=app_id).with_for_update().first(), current_session_user()
    item = APPItem.query.filter_by(id=item_id, app_id=app_id).first()
    if plan is None or item is None:
        return jsonify({'error': 'APP item not found.'}), 404
    completing_new_item = can_complete_added_app_item(user, plan, item)
    if not can_edit_app(user, plan) and not completing_new_item:
        return jsonify({'error': 'Only Admin may edit an APP while Draft or Returned.'}), 403
    if request.method == 'DELETE':
        if item.contributions or plan.workflow_version == 2:
            return jsonify({'error': 'Consolidated source rows must retain their office contributions. Revise allocations instead.'}), 409
        source_id = item.source_ppmp_item_id
        db.session.delete(item)
        db.session.flush()
        db.session.expire(plan, ['items'])
        plan.revision = (plan.revision or 1) + 1
        sync_app_mode_tasks(plan)
        app_audit_snapshot(plan, 'APP_ITEM_REMOVED', {'app_item_id': item_id, 'source_ppmp_item_id': source_id})
        db.session.commit()
        return jsonify({'success': True})
    data = request.get_json(silent=True) or {}
    if 'mode_of_procurement' in data:
        return jsonify({'error': 'Only BAC Chairman may set the APP Mode of Procurement during review.'}), 403
    if completing_new_item and 'contributions' in data:
        return jsonify({'error': 'Office allocations can be revised after the APP is returned. Complete the new row fields here.'}), 409
    section = APPSection.query.filter_by(id=data.get('section_id', item.section_id), app_id=plan.id).first()
    if section is None:
        return jsonify({'error': 'Select a valid APP section.'}), 400
    try:
        values = parse_app_item({**item.to_dict(), **data})
        allocation_update = prepare_contribution_update(item, data) if 'contributions' in data else None
        if allocation_update:
            values['estimated_budget'] = allocation_update[2]
        elif item.contributions and (
            values['estimated_budget'] != Decimal(item.estimated_budget)
            or ('quantity' in data and precise_number(data['quantity'], 'Row quantity', positive=True) != Decimal(item.quantity))
        ):
            raise ValueError('Specify each office contribution when changing a merged quantity or budget.')
        if item.contributions and values['implementing_unit'] != item.implementing_unit:
            raise ValueError('The contributing offices are retained from the approved PPMP sources.')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    if any(values[field] != getattr(item, field) for field in (
        'project_title', 'general_description',
        'procurement_start', 'procurement_end', 'source_of_fund',
    )):
        item.merge_key = None
    for field, value in values.items():
        setattr(item, field, value)
    item.section_id = section.id
    if allocation_update:
        apply_contribution_update(item, allocation_update)
    if completing_new_item and not app_item_validation_error(item, require_procurement_mode=False):
        plan.source_details = {
            **(plan.source_details or {}),
            'pending_item_ids': [value for value in (plan.source_details or {}).get('pending_item_ids', []) if value != item.id],
        }
    plan.revision = (plan.revision or 1) + 1
    app_audit_snapshot(plan, 'APP_ITEM_UPDATED', {
        'app_item_id': item.id, 'section_id': section.id,
        'note': str(data.get('note') or '').strip() or None,
    })
    if allocation_update:
        notify_app_offices(plan, 'APP office contributions updated',
                           f'Admin revised the office quantities or budgets for {item.project_title} in '
                           f'{app_notification_label(plan)}. The approved PPMP sources remain unchanged.',
                           app_items=[item])
    db.session.commit()
    return jsonify(item.to_dict())


@app.route('/api/apps/<int:app_id>/items/<int:item_id>/procurement-mode', methods=['PUT'])
@roles_required('BAC CHAIRMAN')
def set_app_procurement_mode(app_id, item_id):
    plan = AnnualProcurementPlan.query.filter_by(id=app_id).with_for_update().first()
    item = APPItem.query.filter_by(id=item_id, app_id=app_id).first()
    user = current_session_user()
    if plan is None or item is None:
        return jsonify({'error': 'APP item not found.'}), 404
    if not can_set_app_procurement_mode(user, plan, item):
        return jsonify({'error': 'BAC Chairman may set procurement modes during BAC review, or for pending new rows during a later review stage.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'mode_of_procurement'}:
        return jsonify({'error': 'Provide only the Mode of Procurement for this APP row.'}), 400
    mode = data['mode_of_procurement']
    if (not isinstance(mode, str) or mode.strip() not in
            set(APP_MODES_OF_PROCUREMENT) | set(PPMP_REPORT_PROCUREMENT_METHODS)):
        return jsonify({'error': 'Select a valid Mode of Procurement.'}), 400
    mode = mode.strip()
    previous_mode = item.mode_of_procurement
    item.mode_of_procurement = mode
    if previous_mode != mode:
        # Future sources may join only if their recommendation still matches
        # BAC's APP decision and all other original merge fields are unchanged.
        if not item.contributions or any(
                row.source_snapshot.get('mode_of_procurement') != mode for row in item.contributions):
            item.merge_key = None
    plan.revision = (plan.revision or 1) + 1
    sync_app_mode_tasks(plan)
    app_audit_snapshot(plan, 'APP_PROCUREMENT_MODE_SET', {
        'app_item_id': item.id, 'previous_mode': previous_mode,
        'mode_of_procurement': mode, 'reviewer_role': user.role,
        'continuing_reviewer': expected_app_reviewer(plan),
    })
    db.session.commit()
    return jsonify({'ok': True, 'app': app_detail_dict(plan)})


@app.route('/api/apps/<int:app_id>/items/<int:item_id>/contributions', methods=['PUT'])
@permission_required('app.edit')
def update_app_contributions(app_id, item_id):
    plan, user = AnnualProcurementPlan.query.filter_by(id=app_id).with_for_update().first(), current_session_user()
    item = APPItem.query.filter_by(id=item_id, app_id=app_id).first()
    if plan is None or item is None:
        return jsonify({'error': 'APP item not found.'}), 404
    if not can_edit_app(user, plan):
        return jsonify({'error': 'Only Admin may revise office contributions while the APP is Draft or Returned.'}), 403
    data = request.get_json(silent=True) or {}
    try:
        prepared = prepare_contribution_update(item, data)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    apply_contribution_update(item, prepared)
    plan.revision = (plan.revision or 1) + 1
    app_audit_snapshot(plan, 'APP_CONTRIBUTIONS_UPDATED', {
        'app_item_id': item.id, 'note': str(data.get('note') or '').strip() or None,
    })
    notify_app_offices(plan, 'APP office contributions updated',
                       f'Admin revised the office quantities or budgets for {item.project_title} in '
                       f'{app_notification_label(plan)}. The approved PPMP sources remain unchanged.',
                       app_items=[item])
    db.session.commit()
    return jsonify(item.to_dict())


@app.route('/api/apps/<int:app_id>/comments', methods=['POST'])
@permission_required('app.view')
def create_app_comment(app_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()
    if not message or len(message) > 5000:
        return jsonify({'error': 'Comment is required and must not exceed 5,000 characters.'}), 400
    item_id = data.get('app_item_id')
    if item_id is not None and APPItem.query.filter_by(id=item_id, app_id=plan.id).first() is None:
        return jsonify({'error': 'The selected APP item does not belong to this APP record.'}), 400
    comment = APPComment(app_id=plan.id, app_item_id=item_id, author_id=user.id, message=message)
    db.session.add(comment)
    app_audit_snapshot(plan, 'APP_COMMENT_ADDED', {'app_item_id': item_id, 'message': message})
    if user.role != 'ADMIN':
        notify_roles(('ADMIN',), 'APP review comment',
                     f'{app_notification_label(plan)}: {user.role} commented: {message}',
                     target_type='app', target_id=plan.id)
    notify_app_offices(plan, 'APP review comment',
                       f'{app_notification_label(plan)}: {user.role} commented: {message}',
                       app_items=[item for item in plan.items if item.id == item_id] if item_id else None)
    db.session.commit()
    return jsonify(comment.to_dict()), 201


@app.route("/api/apps/<int:app_id>/transition", methods=["POST"])
def transition_app(app_id):
    plan, user = AnnualProcurementPlan.query.filter_by(id=app_id).with_for_update().first(), current_session_user()
    if plan is None:
        return jsonify({"error": "APP record not found."}), 404
    if user is None:
        return jsonify({"error": "Authentication required."}), 401
    data = request.get_json(silent=True) or {}
    action, note = data.get('action'), str(data.get('note') or '').strip() or None
    if note and len(note) > 5000:
        return jsonify({'error': 'Review notes must not exceed 5,000 characters.'}), 400
    if action in {'return', 'reject'} and not note:
        return jsonify({'error': 'A reason is required when returning or rejecting an APP.'}), 400
    if action == 'submit':
        if not can_edit_app(user, plan) or not has_permission(user, 'app.submit'):
            return jsonify({'error': 'Only Admin may complete and submit an APP while Draft or Returned.'}), 403
        validation_error = validate_app_for_submission(plan, require_procurement_mode=False)
        if validation_error:
            return jsonify({'error': validation_error}), 400
    expected = expected_app_reviewer(plan)
    previous = plan.status
    next_role = None
    if action == 'submit':
        next_role = (plan.return_review_role or expected) if previous == 'Returned' else expected
        next_role = next_role if next_role in APP_REVIEW_ROLES else 'BAC CHAIRMAN'
        target = 'For Admin Approval' if next_role == 'ADMIN' else 'Under Review'
        plan.current_review_role, plan.return_review_role = next_role, None
    elif action in {'approve', 'return', 'reject'}:
        if not has_permission(user, 'app.review') or user.role != expected:
            return jsonify({'error': 'Only the current assigned reviewer may perform this APP review.'}), 403
        if previous not in {'Submitted', 'Under Review', 'For Admin Approval'}:
            return jsonify({'error': 'This APP is not awaiting review.'}), 409
        if action == 'approve':
            validation_error = validate_app_for_submission(plan)
            if validation_error:
                return jsonify({'error': f'The APP must be complete before approval. {validation_error}'}), 409
            approved_roles = {
                row.reviewer_role or (row.performer.role if row.performer else None)
                for row in plan.approvals if row.action == 'APPROVE'
            } | {user.role}
            next_role = next((role for role in APP_REVIEW_ROLES if role not in approved_roles), None)
            if user.role == 'ADMIN':
                target, next_role = 'Finalized', None
            else:
                target = 'For Admin Approval' if next_role == 'ADMIN' else 'Under Review'
            plan.current_review_role, plan.return_review_role = next_role, None
        else:
            target = 'Returned' if action == 'return' else 'Rejected'
            plan.return_review_role = user.role if action == 'return' else None
            plan.current_review_role = user.role if action == 'return' else None
            next_role = 'ADMIN' if action == 'return' else None
    elif action == 'finalize' and user.role == 'ADMIN' and previous == 'Approved' and plan.workflow_version != 2:
        target = 'Finalized'
        plan.current_review_role = None
    else:
        return jsonify({'error': 'This APP transition is not allowed.'}), 409
    resolve_notification_tasks('app', plan.id)
    plan.status = target
    db.session.flush()
    sync_app_mode_tasks(plan)
    db.session.add(APPApproval(
        app=plan, action=action.upper(), performed_by=user.id, reviewer_role=user.role,
        note=note, snapshot=app_snapshot(plan),
    ))
    if note:
        db.session.add(APPComment(app_id=plan.id, author_id=user.id, message=note))
    app_audit_snapshot(plan, action.upper(), {
        'from': previous, 'to': target, 'reviewer_role': user.role,
        'return_to_reviewer': plan.return_review_role, 'note': note,
    })
    if next_role:
        task = 'correction using office feedback' if target == 'Returned' else 'review'
        performed_action = ('resubmitted' if action == 'submit' and previous == 'Returned'
                            else {'submit': 'submitted', 'approve': 'approved', 'return': 'returned'}[action])
        notify_roles((next_role,), f'APP awaiting {next_role} {"correction" if target == "Returned" else "review"}',
                     f'{app_notification_label(plan)} requires your {task} after {user.role} '
                     f'{performed_action} it. '
                     f'{note or ""}'.strip(), 'warning' if target == 'Returned' else 'info',
                     target_type='app', target_id=plan.id,
                     action_stage='CORRECTION' if target == 'Returned' else f'REVIEW:{next_role}')
    progress = {
        'submit': f'was {"resubmitted" if previous == "Returned" else "submitted"} by Admin for {next_role} review.',
        'approve': (f'was approved by {user.role} and is awaiting {next_role} review.' if next_role
                    else 'received final Administrator approval and is now finalized.'),
        'return': f'was returned by {user.role}. Admin will correct it using office feedback. '
                  'Open your official PPMP record to send feedback to Admin.',
        'reject': f'was rejected by {user.role}.',
        'finalize': 'has been finalized by Admin.',
    }[action]
    if next_role != 'ADMIN' and user.role != 'ADMIN':
        notify_roles(('ADMIN',), f'APP {target.lower()}',
                     f'{app_notification_label(plan)} {progress}' + (f' Review note: {note}' if note else ''),
                     'warning' if target == 'Rejected' else 'info', target_type='app', target_id=plan.id)
    notify_app_offices(plan, 'APP office feedback requested' if action == 'return' else f'APP {target.lower()}',
                       f'{app_notification_label(plan)} {progress}' + (f' Review note: {note}' if note else ''),
                       'warning' if target in {'Returned', 'Rejected'} else
                       'success' if target == 'Finalized' else 'info',
                       action_stage='OFFICE_FEEDBACK' if action == 'return' else None)
    db.session.commit()
    return jsonify(app_detail_dict(plan))


@app.route('/api/ppmp-orders/<int:order_id>/app-feedback', methods=['GET', 'POST'])
@permission_required('ppmp.report')
def official_ppmp_app_feedback(order_id):
    order, user = db.session.get(PPMPOrder, order_id), current_session_user()
    if order is None:
        return jsonify({'error': 'PPMP record not found.'}), 404
    if user.role != 'ADMIN' and (order.requested_by != user.id or order.office_id != user.college_id):
        return jsonify({'error': 'Only the office creator or Admin may access this PPMP office feedback.'}), 403
    source_ids = [item.ppmp_item_id for item in order.items if item.ppmp_item_id is not None]
    allocations = APPItemContribution.query.filter(APPItemContribution.source_ppmp_item_id.in_(source_ids)).all()
    linked_plans = {allocation.app_item.app_id: allocation.app_item.app for allocation in allocations}
    if request.method == 'GET':
        result = []
        for app_id, plan in linked_plans.items():
            own_allocations = [row for row in allocations if row.app_item.app_id == app_id]
            own_item_ids = {row.app_item_id for row in own_allocations}
            source_creator_ids = {row.source_ppmp_item.created_by for item in plan.items for row in item.contributions}
            comments = [
                row.to_dict() for row in plan.comments
                if (row.author_id == user.id or (row.author and row.author.role in APP_REVIEW_ROLES)
                    or (row.author_id not in source_creator_ids and row.app_item_id in own_item_ids))
                and (row.app_item_id is None or row.app_item_id in own_item_ids)
            ]
            result.append({
                'app_id': plan.id, 'fiscal_year': plan.fiscal_year, 'status': plan.status,
                'revision': plan.revision, 'expected_reviewer': expected_app_reviewer(plan),
                'is_supplemental': plan.supplemental_parent_id is not None,
                'contributions': [row.to_dict() for row in own_allocations], 'comments': comments,
            })
        return jsonify({'apps': result})
    data = request.get_json(silent=True) or {}
    plan = linked_plans.get(data.get('app_id'))
    if plan is None:
        return jsonify({'error': 'Select an APP containing a contribution from this PPMP.'}), 400
    message = str(data.get('message') or '').strip()
    if not message or len(message) > 5000:
        return jsonify({'error': 'Feedback is required and must not exceed 5,000 characters.'}), 400
    item_id = data.get('app_item_id')
    if item_id is not None and not any(row.app_item_id == item_id for row in allocations if row.app_item.app_id == plan.id):
        return jsonify({'error': 'Select an APP row containing this office contribution.'}), 400
    comment = APPComment(app=plan, app_item_id=item_id, author_id=user.id, message=message)
    db.session.add(comment)
    app_audit_snapshot(plan, 'APP_OFFICE_FEEDBACK', {
        'source_order_id': order.id, 'office_id': order.office_id,
        'app_item_id': item_id, 'message': message,
    })
    office_recipient_ids = db.session.query(User.id).filter(or_(
        User.college_id == order.office_id,
        User.office == order.office.code if order.office else User.college_id == order.office_id,
    ))
    resolve_notification_tasks('app', plan.id, action_stage='OFFICE_FEEDBACK',
                               recipient_ids=office_recipient_ids)
    notify_roles(('ADMIN',), 'Office feedback on APP',
                 f'{order.office.code if order.office else user.office} sent feedback for APP FY {plan.fiscal_year}: {message}',
                 target_type='app', target_id=plan.id)
    db.session.commit()
    return jsonify(comment.to_dict()), 201


def app_approval_identity(plan, role):
    return next((
        approval.performer.full_name for approval in reversed(plan.approvals)
        if approval.action in {'APPROVE', 'FINALIZE'} and approval.performer
        and approval.performer.role == role
    ), '')


@app.route('/api/apps/<int:app_id>/export/pdf')
@permission_required('app.export')
def export_app_pdf(app_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    if not can_access_app(user, plan):
        return jsonify({'error': 'You are not authorized to export this APP.'}), 403
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=landscape(A3), rightMargin=8*mm, leftMargin=8*mm,
        topMargin=8*mm, bottomMargin=12*mm,
        title=f'{plan.plan_type} FY {plan.fiscal_year}', author=user.full_name,
    )
    styles = getSampleStyleSheet()
    small = styles['BodyText'].clone('APPCell')
    small.fontSize, small.leading = 5.5, 6.5
    def cell(value):
        return Paragraph(str(value or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'), small)
    headers = [
        'Project Title', 'End-User / Implementing Unit', 'General Description of Project',
        'Mode of Procurement', 'Early Procurement Activity?',
        'Criteria for Bid Evaluation (including Sustainability and Domestic Preference)',
        'Start', 'End', 'Source of Fund', 'Estimated / Approved Budget (PHP)',
        'Procurement Strategy or Tools', 'Remarks',
    ]
    rows = [
        ['PROCUREMENT PROJECT DETAILS', '', '', '', '', '', 'PROJECTED TIMELINE (MM/YYYY)', '',
         'FUNDING DETAILS', '', 'PROCUREMENT STRATEGY OR TOOLS', 'REMARKS'],
        [cell(header) for header in headers],
    ]
    section_rows = []
    for section in plan.sections:
        section_rows.append(len(rows))
        rows.append([cell(section.name)] + [''] * 11)
        for item in section.items:
            rows.append([
                cell(export_project_title(item)), cell(export_office_contributions(item)), cell(item.general_description),
                cell(item.mode_of_procurement), cell('Yes' if item.early_procurement_activity else 'No'
                                                     if item.early_procurement_activity is False else ''),
                cell(item.bid_evaluation_criteria), cell(APPItem.month_label(item.procurement_start)),
                cell(APPItem.month_label(item.procurement_end)), cell(item.source_of_fund),
                f'{float(item.estimated_budget or 0):,.2f}', cell(item.procurement_strategy_tools),
                cell(item.remarks),
            ])
        rows.append([cell(f'TOTAL {section.name.upper()}')] + [''] * 8 + [f'{section.total_budget:,.2f}', '', ''])
    rows.append([cell('TOTAL AMOUNT OF ESTIMATED BUDGET')] + [''] * 8 + [f'{plan.totals()["overall"]:,.2f}', '', ''])
    widths = [45, 31, 31, 33, 21, 36, 22, 22, 29, 31, 37, 37]
    table = Table(rows, repeatRows=2, colWidths=[width * mm for width in widths])
    style = [
        ('SPAN', (0, 0), (5, 0)), ('SPAN', (6, 0), (7, 0)), ('SPAN', (8, 0), (9, 0)),
        ('SPAN', (10, 0), (10, 1)), ('SPAN', (11, 0), (11, 1)),
        ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#1b3a6b')),
        ('TEXTCOLOR', (0, 0), (-1, 1), colors.white),
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), .3, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 5.5),
        ('ALIGN', (9, 2), (9, -1), 'RIGHT'),
    ]
    for row_index in section_rows:
        style.extend([
            ('SPAN', (0, row_index), (-1, row_index)),
            ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#dbeafe')),
            ('FONTNAME', (0, row_index), (-1, row_index), 'Helvetica-Bold'),
        ])
    table.setStyle(TableStyle(style))
    recommendations = ', '.join(filter(None, (
        app_approval_identity(plan, 'BAC CHAIRMAN'), app_approval_identity(plan, 'BUDGET'),
        app_approval_identity(plan, 'EO'),
    )))
    signatures = Table([
        ['Prepared by', 'Recommended / Reviewed by', 'Approved by'],
        [plan.creator.full_name if plan.creator else '', recommendations,
         app_approval_identity(plan, 'ADMIN')],
    ], colWidths=[130*mm, 130*mm, 130*mm])
    signatures.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    story = [
        Paragraph('Isabela State University – Cauayan City', styles['Title']),
        Paragraph(f'Annual Procurement Plan — {plan.plan_type.replace("_", " ")} — FY {plan.fiscal_year}', styles['Heading2']),
        Paragraph(f'Office: {plan.office} &nbsp;&nbsp; Status: {plan.status}', styles['Normal']),
        Spacer(1, 4*mm), table, Spacer(1, 8*mm),
        Paragraph(f'Total EPA Projects: PHP {plan.totals()["early_procurement"]:,.2f}', styles['Normal']),
        Paragraph(f'Total CSE / PS-DBM: PHP {plan.totals()["cse"]:,.2f}', styles['Normal']),
        Paragraph(f'Total Estimated Budget: PHP {plan.totals()["overall"]:,.2f}', styles['Heading3']),
        Spacer(1, 7*mm), signatures,
    ]
    document.build(
        story,
        onFirstPage=lambda canvas, doc: canvas.drawRightString(410*mm, 6*mm, f'Page {doc.page}'),
        onLaterPages=lambda canvas, doc: canvas.drawRightString(410*mm, 6*mm, f'Page {doc.page}'),
    )
    audit('app', plan.id, 'APP_EXPORT_PDF', {'items': len(plan.items)})
    db.session.commit()
    output.seek(0)
    return send_file(
        output, as_attachment=True, mimetype='application/pdf',
        download_name=f'{plan.plan_type}_{plan.office}_{plan.fiscal_year}.pdf',
    )


@app.route('/api/apps/<int:app_id>/export/excel')
@permission_required('app.export')
def export_app_excel(app_id):
    plan, user = db.session.get(AnnualProcurementPlan, app_id), current_session_user()
    if plan is None:
        return jsonify({'error': 'APP record not found.'}), 404
    if not can_access_app(user, plan):
        return jsonify({'error': 'You are not authorized to export this APP.'}), 403
    workbook, worksheet = Workbook(), None
    worksheet = workbook.active
    worksheet.title = 'APP Digital Table'
    navy = PatternFill('solid', fgColor='1B3A6B')
    pale = PatternFill('solid', fgColor='DBEAFE')
    border = Border(*(Side(style='thin', color='94A3B8') for _ in range(4)))
    worksheet.append([f'ANNUAL PROCUREMENT PLAN — {plan.plan_type.replace("_", " ")} — FY {plan.fiscal_year}'])
    worksheet.merge_cells('A1:L1')
    worksheet['A1'].font, worksheet['A1'].fill = Font(bold=True, color='FFFFFF', size=14), navy
    worksheet['A1'].alignment = Alignment(horizontal='center')
    worksheet.append(['PROCUREMENT PROJECT DETAILS', '', '', '', '', '', 'PROJECTED TIMELINE (MM/YYYY)', '',
                      'FUNDING DETAILS', '', 'PROCUREMENT STRATEGY OR TOOLS', 'REMARKS'])
    worksheet.merge_cells('A2:F2'); worksheet.merge_cells('G2:H2'); worksheet.merge_cells('I2:J2')
    worksheet.merge_cells('K2:K3'); worksheet.merge_cells('L2:L3')
    worksheet.append([
        'Project Title', 'End-User / Implementing Unit', 'General Description of Project',
        'Mode of Procurement', 'Early Procurement Activity?', 'Criteria for Bid Evaluation',
        'Start', 'End', 'Source of Fund', 'Estimated / Approved Budget (PHP)', '', '',
    ])
    for row in worksheet.iter_rows(min_row=2, max_row=3, min_col=1, max_col=12):
        for cell_value in row:
            cell_value.fill, cell_value.font = navy, Font(bold=True, color='FFFFFF')
            cell_value.alignment, cell_value.border = Alignment(horizontal='center', vertical='center', wrap_text=True), border
    for section in plan.sections:
        worksheet.append([section.name])
        section_row = worksheet.max_row
        worksheet.merge_cells(start_row=section_row, start_column=1, end_row=section_row, end_column=12)
        worksheet.cell(section_row, 1).fill = pale
        worksheet.cell(section_row, 1).font = Font(bold=True)
        for item in section.items:
            worksheet.append([
                export_project_title(item), export_office_contributions(item), item.general_description,
                item.mode_of_procurement,
                'Yes' if item.early_procurement_activity else 'No' if item.early_procurement_activity is False else '',
                item.bid_evaluation_criteria, APPItem.month_label(item.procurement_start),
                APPItem.month_label(item.procurement_end), item.source_of_fund,
                float(item.estimated_budget or 0), item.procurement_strategy_tools, item.remarks,
            ])
        worksheet.append([f'TOTAL {section.name.upper()}', '', '', '', '', '', '', '', '', section.total_budget, '', ''])
    worksheet.append(['TOTAL AMOUNT OF ESTIMATED BUDGET', '', '', '', '', '', '', '', '', plan.totals()['overall'], '', ''])
    worksheet.append([])
    worksheet.append(['Prepared by', '', '', '', 'Recommended / Reviewed by', '', '', '', 'Approved by'])
    worksheet.append([
        plan.creator.full_name if plan.creator else '', '', '', '',
        ', '.join(filter(None, (app_approval_identity(plan, 'BAC CHAIRMAN'),
                                app_approval_identity(plan, 'BUDGET'), app_approval_identity(plan, 'EO')))),
        '', '', '', app_approval_identity(plan, 'ADMIN'),
    ])
    for row in worksheet.iter_rows(min_row=4, max_row=worksheet.max_row, min_col=1, max_col=12):
        for cell_value in row:
            cell_value.border = border
            cell_value.alignment = Alignment(vertical='top', wrap_text=True)
    widths = [36, 25, 25, 28, 20, 32, 14, 14, 25, 22, 30, 30]
    for index, width in enumerate(widths, 1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    worksheet.freeze_panes = 'A4'
    worksheet.sheet_view.showGridLines = False
    output = io.BytesIO()
    workbook.save(output)
    audit('app', plan.id, 'APP_EXPORT_EXCEL', {'items': len(plan.items)})
    db.session.commit()
    output.seek(0)
    return send_file(
        output, as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name=f'{plan.plan_type}_{plan.office}_{plan.fiscal_year}.xlsx',
    )


@app.route('/api/notifications', methods=['GET', 'DELETE'])
@login_required
def notifications():
    user = current_session_user()
    query = PPMPNotification.query.filter_by(recipient_id=user.id)
    if request.method == 'DELETE':
        query.delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'success': True})
    rows = query.filter(PPMPNotification.resolved_at.is_(None)).order_by(
        PPMPNotification.created_at.desc(), PPMPNotification.id.desc(),
    ).all()
    active = [payload for row in rows
              if (payload := notification_payload(row, sys.modules[__name__], user)) is not None]
    payload = active[:100]
    if request.args.get('summary') == '1':
        payload = {'notifications': payload, 'unread_count': sum(not row['is_read'] for row in active)}
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/notifications/read', methods=['POST'])
@login_required
def read_notifications():
    data = request.get_json(silent=True)
    ids = data.get('ids') if isinstance(data, dict) else None
    if (not isinstance(ids, list) or len(ids) > 100
            or any(type(value) is not int or value <= 0 for value in ids)):
        return jsonify({'error': 'Provide up to 100 notification IDs to mark as read.'}), 400
    PPMPNotification.query.filter(
        PPMPNotification.recipient_id == current_session_user().id,
        PPMPNotification.id.in_(ids), PPMPNotification.is_read.is_(False),
    ).update({'is_read': True, 'read_at': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def read_notification(notification_id):
    user = current_session_user()
    notification = PPMPNotification.query.filter_by(id=notification_id, recipient_id=user.id).first()
    if notification is None:
        return jsonify({'error': 'Notification not found.'}), 404
    notification.is_read, notification.read_at = True, datetime.utcnow()
    data = request.get_json(silent=True) or {}
    _, completed, stage = notification_context(notification, sys.modules[__name__], user)
    if completed or (isinstance(data, dict) and data.get('opened') is True and not stage):
        notification.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify(dict(notification.to_dict(), removed=notification.resolved_at is not None))


@app.route('/api/notifications/<int:notification_id>/target')
@login_required
def notification_target(notification_id):
    user = current_session_user()
    notification = PPMPNotification.query.filter_by(id=notification_id, recipient_id=user.id).first()
    if notification is None:
        return jsonify({'error': 'Notification not found.'}), 404
    target, completed, stage = notification_context(notification, sys.modules[__name__], user)
    response = jsonify({'target': None if completed else target, 'completed': completed,
                        'action_required': bool(stage)})
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/admin/audit-log')
@admin_required
def workflow_audit_log():
    rows = WorkflowAuditLog.query.order_by(WorkflowAuditLog.created_at.desc()).limit(500).all()
    return jsonify([{'id': row.id, 'entity_type': row.entity_type, 'entity_id': row.entity_id,
                     'action': row.action, 'performed_by': row.performed_by, 'ip_address': row.ip_address,
                     'details': row.details, 'created_at': row.created_at.isoformat() if row.created_at else None}
                    for row in rows])


@app.route('/api/export/pdf')
@permission_required('ppmp.export')
def export_pdf():
    user = current_session_user()
    items = [item for item in get_ppmp_items(college_id=request.args.get('college_id', type=int))
             if can_access_ppmp(user, item)]
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=10*mm, leftMargin=10*mm,
                                 topMargin=10*mm, bottomMargin=12*mm,
                                 title='PPMP Summary Report', author=user.full_name)
    styles = getSampleStyleSheet()
    rows = [['Office/College', 'Description', 'Unit', 'Qty', 'Unit Cost', 'Total', 'Status']]
    for item in items:
        rows.append([item.college.code if item.college else '', item.item_description, item.unit,
                     f'{float(item.quantity):,.2f}', f'{float(item.unit_cost):,.2f}',
                     f'{item.total_cost:,.2f}', item.status])
    total = sum(item.total_cost for item in items)
    rows.append(['', 'AUTHORIZED TOTAL', '', '', '', f'{total:,.2f}', ''])
    table = Table(rows, repeatRows=1, colWidths=[27*mm, 78*mm, 18*mm, 18*mm, 27*mm, 30*mm, 28*mm])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1b3a6b')),
                               ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                               ('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),
                               ('VALIGN',(0,0),(-1,-1),'TOP'),('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold')]))
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    story = [Paragraph('Isabela State University – Cauayan City', styles['Title']),
             Paragraph('PPMP Summary Report', styles['Heading2']),
             Paragraph(f'Generated {generated} by {user.full_name} ({user.role})', styles['Normal']), Spacer(1, 5*mm), table]
    document.build(story, onFirstPage=lambda canvas, doc: canvas.drawRightString(280*mm, 7*mm, f'Page {doc.page}'),
                   onLaterPages=lambda canvas, doc: canvas.drawRightString(280*mm, 7*mm, f'Page {doc.page}'))
    audit('report', 0, 'EXPORT_PDF', {'records': len(items)})
    db.session.commit()
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f'PPMP_{datetime.now():%Y%m%d_%H%M%S}.pdf', mimetype='application/pdf')


@app.route("/api/export/excel")
@permission_required('ppmp.export')
def export_excel():
    items = get_ppmp_items(college_id=request.args.get("college_id", type=int))
    user = current_session_user()
    items = [item for item in items if can_access_ppmp(user, item)]
    audit('report', 0, 'EXPORT_EXCEL', {'records': len(items)})
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "PPMP Consolidated"
    headers = ["#", "College", "Item Description", "Unit", "Qty", "Unit Cost", "Total Cost", "Fund Source", "Mode of Procurement", "Quarter", "Status"]
    widths = [4, 22, 35, 10, 6, 14, 14, 10, 28, 16, 12]
    fill = PatternFill("solid", fgColor="1B3A6B")
    side = Side(style="thin", color="AAAAAA")
    worksheet.append(["PROCUREMENT MANAGEMENT PLAN (PPMP)"])
    worksheet.merge_cells("A1:K1")
    worksheet["A1"].font, worksheet["A1"].fill = Font(bold=True, color="FFFFFF", size=14), fill
    worksheet["A1"].alignment = Alignment(horizontal="center")
    worksheet.append(headers)
    for index in range(1, len(headers) + 1):
        cell = worksheet.cell(2, index)
        cell.font, cell.fill, cell.border = Font(bold=True, color="FFFFFF"), fill, Border(side, side, side, side)
        worksheet.column_dimensions[get_column_letter(index)].width = widths[index - 1]
    for index, item in enumerate(items, 1):
        worksheet.append([index, item.college.code, item.item_description, item.unit, float(item.quantity), float(item.unit_cost), item.total_cost, item.fund_source, item.mode_of_procurement, item.quarter, item.status])
    output = io.BytesIO()
    workbook.save(output)
    db.session.commit()
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"PPMP_{datetime.now():%Y%m%d_%H%M%S}.xlsx")


register_ppmp_workflow_routes(sys.modules[__name__])


if __name__ == "__main__":
    try:
        print('Dependencies loaded. Checking database connection and schema...', flush=True)
        migration_requested = '--migrate-only' in sys.argv or '--reset-database' in sys.argv
        initialize_database(apply_migrations=migration_requested)
    except RuntimeError as error:
        print(f"Startup aborted: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    if '--migrate-only' in sys.argv:
        print('Database migration completed successfully; no data was reset.')
    elif "--reset-database" in sys.argv:
        with app.app_context():
            reset_database()
        print("Database reset complete. Only admin/admin1234 is available.")
    else:
        print('Database ready. Starting PPMP web server...', flush=True)
        app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=int(os.getenv("FLASK_PORT", "5000")), host="0.0.0.0")

