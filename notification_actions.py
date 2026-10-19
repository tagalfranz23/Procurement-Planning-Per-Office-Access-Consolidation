"""Notification destinations and review-task completion, including older messages."""
import re
from datetime import datetime, timedelta

from models import (
    AnnualProcurementPlan, APPItem, APPItemContribution, PPMPItem, PPMPNotification,
    PPMPOrder, PPMPOrderItem, PPMPRecord, PPMPRecordItem, User, db,
)


def legacy_notification_target(notification):
    title, message = notification.title.lower(), notification.message
    if notification.ppmp_item_id:
        stage = ('ADMIN' if 'final approval' in title else 'PROCUREMENT' if 'procurement review' in title
                 else 'EO' if 'submitted' in title else None)
        return 'ppmp_item', notification.ppmp_item_id, stage
    reference = re.search(r'\b(?:PPMPR|PPMP|LEGACY-PPMP)-[A-Za-z0-9_-]+', message)
    if reference:
        order = PPMPOrder.query.filter_by(reference_number=reference.group()).first()
        record = None if order else PPMPRecord.query.filter_by(reference_number=reference.group()).first()
        if order or record:
            stage = None
            role = notification.recipient.role if notification.recipient else None
            if role == 'ADMIN' and ('pending approval' in title or 'administrator' in title or 'final approval' in title):
                # Administrator comments and informational approval results are not review tasks.
                if 'comment' not in title and ('pending' in title or 'review' in title or 'approval' in title):
                    stage = 'ADMIN'
            elif role == 'PROCUREMENT' and ('ready' in title or 'awaiting' in title):
                stage = 'PROCUREMENT'
            elif 'returned' in title:
                stage = 'CREATOR'
            return 'ppmp_order' if order else 'ppmp_record', (order or record).id, stage
    if title == 'new account awaiting approval':
        name = message.partition(' registered and needs')[0]
        candidates = User.query.filter_by(full_name=name).all()
        if notification.created_at:
            candidates = [user for user in candidates if user.created_at and
                          abs(user.created_at - notification.created_at) <= timedelta(minutes=2)]
        if len(candidates) == 1:
            return 'account', candidates[0].id, 'PENDING'
        return 'accounts', None, None
    match = re.search(r'\b(?:Supplemental )?APP #(\d+)\b', message)
    plan = db.session.get(AnnualProcurementPlan, int(match.group(1))) if match else None
    if not plan and title.startswith('app'):
        year = re.search(r'\bAPP FY (\d{4})\b', message)
        if year:
            query = AnnualProcurementPlan.query.filter_by(fiscal_year=int(year.group(1)))
            if notification.created_at:
                query = query.filter(AnnualProcurementPlan.created_at <= notification.created_at)
            plans = query.all()
            # Never guess which document to open when multiple APPs match an old message.
            plan = plans[0] if len(plans) == 1 else None
    if plan:
        role = notification.recipient.role if notification.recipient else None
        stage = None
        if title == 'app pending action' or 'awaiting' in title or 'batch added during review' in title:
            stage = 'CORRECTION' if role == 'ADMIN' and plan.status == 'Returned' else f'REVIEW:{role}'
        elif 'feedback requested' in title:
            stage = 'OFFICE_FEEDBACK'
        return 'app', plan.id, stage
    if title.startswith('app') or ' on app' in title:
        return 'apps', None, None
    if 'ppmp' in title or 'wishlist' in title:
        return 'ppmp_requests', None, None
    return 'profile', notification.recipient_id, None


def notification_context(notification, application, user):
    """Return a permitted destination and whether the original task is still open."""
    kind, target_id, stage = (notification.target_type, notification.target_id, notification.action_stage)
    if not kind:
        kind, target_id, stage = legacy_notification_target(notification)
    completed = notification.resolved_at is not None
    destination = {'kind': kind, 'id': target_id}
    if kind == 'account':
        account = db.session.get(User, target_id)
        completed |= not account or account.account_status != 'PENDING' or user.role != 'ADMIN'
    elif kind in {'ppmp_order', 'ppmp_record', 'ppmp_item'}:
        model = {'ppmp_order': PPMPOrder, 'ppmp_record': PPMPRecord, 'ppmp_item': PPMPItem}[kind]
        document = db.session.get(model, target_id)
        if document is None:
            return destination, True, stage
        office_id = document.college_id if kind == 'ppmp_item' else document.office_id
        permission = 'ppmp.view' if kind == 'ppmp_item' else 'ppmp.report'
        completed |= not application.has_permission(user, permission)
        completed |= application.is_ppmp_office_role(user.role) and office_id != user.college_id
        if stage:
            statuses = {
                'ADMIN': {'Requested', 'Pending Admin Approval', 'Procurement Review'},
                'PROCUREMENT': {'Submitted', 'EO Review', 'Under Review'},
                'EO': {'Submitted'}, 'CREATOR': {'Returned'},
            }
            completed |= document.status not in statuses.get(stage, set())
            if stage != 'CREATOR':
                completed |= user.role != stage
        if kind == 'ppmp_item':
            order_row = PPMPOrderItem.query.filter_by(ppmp_item_id=document.id).first()
            record_row = None if order_row else PPMPRecordItem.query.filter_by(ppmp_item_id=document.id).first()
            destination = ({'kind': 'ppmp_order', 'id': order_row.order_id} if order_row else
                           {'kind': 'ppmp_record', 'id': record_row.ppmp_record_id} if record_row else
                           {'kind': 'ppmp_dashboard', 'id': document.id})
    elif kind == 'app':
        plan = db.session.get(AnnualProcurementPlan, target_id)
        if plan is None:
            return destination, True, stage
        if stage == 'CORRECTION':
            completed |= plan.status != 'Returned' or user.role != 'ADMIN'
        elif stage == 'OFFICE_FEEDBACK':
            completed |= plan.status != 'Returned'
        elif stage == 'BAC_MODE':
            pending_mode_ids = (plan.source_details or {}).get('pending_bac_mode_item_ids', [])
            has_pending_mode = any(
                item.id in pending_mode_ids and not str(item.mode_of_procurement or '').strip()
                for item in plan.items
            )
            completed |= (user.role != 'BAC CHAIRMAN'
                          or plan.status not in {'Submitted', 'Under Review', 'For Admin Approval'}
                          or not has_pending_mode)
        elif stage and stage.startswith('REVIEW:'):
            role = stage.partition(':')[2]
            completed |= (plan.status not in {'Submitted', 'Under Review', 'For Admin Approval'}
                          or application.expected_app_reviewer(plan) != role or user.role != role)
        if not application.has_permission(user, 'app.view'):
            # Offices can open their own source and feedback, not other offices' APP data.
            source_ids = db.session.query(APPItemContribution.source_ppmp_item_id).join(APPItem).filter(
                APPItem.app_id == plan.id, APPItemContribution.office_id == user.college_id,
            )
            order = PPMPOrder.query.join(PPMPOrderItem).filter(
                PPMPOrder.office_id == user.college_id,
                PPMPOrderItem.ppmp_item_id.in_(source_ids),
            ).order_by(PPMPOrder.id).first()
            if order is None or not application.has_permission(user, 'ppmp.report'):
                completed = True
            else:
                destination = {'kind': 'ppmp_order', 'id': order.id, 'app_id': plan.id}
    elif kind == 'accounts':
        completed |= user.role != 'ADMIN'
    elif kind == 'apps':
        completed |= not application.has_permission(user, 'app.view')
    elif kind == 'ppmp_requests':
        completed |= not application.has_permission(user, 'ppmp.order.view')
    return destination, bool(completed), stage


def notification_payload(notification, application, user):
    destination, completed, stage = notification_context(notification, application, user)
    if completed:
        return None
    return dict(notification.to_dict(), target=destination, action_required=bool(stage))


def resolve_notification_tasks(target_type, target_id, *, action_stage=None, recipient_ids=None):
    """Resolve all recipients' tasks atomically with the successful workflow action."""
    query = PPMPNotification.query.filter(
        PPMPNotification.target_type == target_type, PPMPNotification.target_id == target_id,
        PPMPNotification.action_stage.isnot(None), PPMPNotification.resolved_at.is_(None),
    )
    if action_stage is not None:
        query = query.filter(PPMPNotification.action_stage == action_stage)
    if recipient_ids is not None:
        query = query.filter(PPMPNotification.recipient_id.in_(recipient_ids))
    query.update({'resolved_at': datetime.utcnow()}, synchronize_session=False)


def backfill_notification_links(application):
    """Run only during explicit migration; preserve messages and read history."""
    for notification in PPMPNotification.query.filter_by(target_type=None).all():
        kind, target_id, stage = legacy_notification_target(notification)
        notification.target_type, notification.target_id, notification.action_stage = kind, target_id, stage
        if notification.recipient:
            _, completed, _ = notification_context(notification, application, notification.recipient)
            if completed:
                notification.resolved_at = datetime.utcnow()
    db.session.commit()
