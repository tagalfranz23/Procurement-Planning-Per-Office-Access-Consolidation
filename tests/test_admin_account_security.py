"""Account administration regressions. All writes use guarded SQLite memory fixtures."""
import json
import os
import unittest
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['FLASK_SECRET_KEY'] = 'admin-account-security-tests-only'

import app as application
from models import College, PasswordResetRequest, PPMPNotification, User, WorkflowAuditLog, db
from werkzeug.security import check_password_hash, generate_password_hash


class AdminAccountSecurityTests(unittest.TestCase):
    PASSWORD = 'fixture-account-password'
    NEW_PASSWORD = 'fixture-replacement-password'
    CODE = 'fixture-reset-code'

    def setUp(self):
        application.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.context = application.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.assertEqual(db.engine.url.drivername, 'sqlite')
        self.assertEqual(db.engine.url.database, ':memory:', 'Refusing to mutate a persistent database.')
        db.drop_all()
        db.create_all()
        self.addCleanup(self.clear_database)
        application._RESET_RATE_BUCKETS.clear()
        self.fixture_hash = generate_password_hash(self.PASSWORD)
        self.admin = User(username='fixture_admin', full_name='Fixture Administrator',
                          email='fixture-admin@test.local', password_hash=self.fixture_hash,
                          role='ADMIN', office='ADMINISTRATION', account_status='ACTIVE', is_active=True)
        self.target = User(username='fixture_office', full_name='Fixture Office',
                           email='fixture-office@test.local', password_hash=self.fixture_hash,
                           role='CBAO', office='CBAO', account_status='ACTIVE', is_active=True)
        db.session.add_all([self.admin, self.target])
        db.session.commit()
        self.client = application.app.test_client()

    def clear_database(self):
        self.assertEqual(db.engine.url.database, ':memory:')
        db.session.remove()
        db.drop_all()

    def authenticate(self, user=None, client=None, **overrides):
        user = user or self.admin
        client = client or self.client
        with client.session_transaction() as session:
            session.clear()
            session.update(user_id=user.id, role=user.role, auth_version=int(user.auth_version or 0))
            session.update(overrides)

    def payload(self, **changes):
        payload = dict(first_name='Fixture', middle_name='Test', last_name='Procurement',
                       email='fixture-created@test.local', username='fixture_created',
                       password=self.PASSWORD, password_confirmation=self.PASSWORD,
                       role='PROCUREMENT', office='PROCUREMENT')
        payload.update(changes)
        return payload

    def register(self, **changes):
        return self.client.post('/api/auth/register', json=self.payload(**changes))

    def reset_payload(self, user=None, **changes):
        user = user or self.target
        payload = dict(email=user.email, code=self.CODE, password=self.NEW_PASSWORD,
                       password_confirmation=self.NEW_PASSWORD)
        payload.update(changes)
        return payload

    def reset_request(self, user=None, **changes):
        user = user or self.target
        values = dict(user_id=user.id, status='CODE_ISSUED',
                      token_hash=application.password_reset_digest(self.CODE),
                      expires_at=datetime.utcnow() + timedelta(minutes=15), approved_by=self.admin.id)
        values.update(changes)
        request = PasswordResetRequest(**values)
        db.session.add(request)
        db.session.commit()
        return request

    def assert_no_credentials(self, value, *secrets):
        serialized = value if isinstance(value, str) else json.dumps(value)
        for secret in (self.PASSWORD, self.NEW_PASSWORD, self.fixture_hash, *secrets):
            self.assertNotIn(secret, serialized)
        self.assertNotIn('password_hash', serialized)
        self.assertNotIn('token_hash', serialized)

    def account_endpoints(self):
        return (
            ('POST', '/api/auth/register', self.payload()),
            ('GET', '/api/auth/available-roles', None),
            ('POST', '/api/auth/forgot-password', {'email': self.target.email}),
            ('POST', '/api/auth/reset-password', self.reset_payload()),
        )

    def test_public_login_keeps_existing_controls_and_removes_account_forms(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for required in ('isu-seal.jpg', 'Isabela State University', 'Cauayan Campus',
                         'Project Procurement Management Plan System', 'id="username"',
                         'id="password"', 'data-password="password"', 'Remember me',
                         'Log In', 'Check Account Status'):
            self.assertIn(required, html)
        for removed in ('Forgot Password?', 'Need an account?', 'id="register-form"',
                        'id="forgot-form"', 'id="reset-form"', 'openRegister',
                        '/api/auth/register', '/api/auth/forgot-password', '/api/auth/reset-password'):
            self.assertNotIn(removed, html)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_anonymous_direct_account_requests_are_denied_without_mutation(self):
        request = self.reset_request()
        before = self.target.password_hash
        for method, path, payload in self.account_endpoints():
            with self.subTest(path=path):
                response = self.client.open(path, method=method, json=payload)
                self.assertEqual(response.status_code, 401)
        for path in ('/register', '/forgot-password', '/reset-password'):
            self.assertIn(self.client.get(path).status_code, (401, 403, 404, 405))
        self.assertEqual(User.query.count(), 2)
        self.assertEqual(self.target.password_hash, before)
        self.assertEqual(request.status, 'CODE_ISSUED')

    def test_every_non_admin_role_is_denied_even_with_forged_admin_session_role(self):
        self.reset_request()
        for index, role in enumerate(User.ROLES):
            if role == 'ADMIN':
                continue
            user = User.query.filter_by(role=role).first()
            if user is None:
                user = User(username=f'fixture_role_{index}', full_name=f'Fixture role {index}',
                            email=f'fixture-role-{index}@test.local', password_hash=self.fixture_hash,
                            role=role, office=role, account_status='ACTIVE', is_active=True)
                db.session.add(user)
                db.session.commit()
            self.authenticate(user, role='ADMIN')
            for method, path, payload in self.account_endpoints():
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.client.open(path, method=method, json=payload).status_code, 403)
            html = self.client.get('/').get_data(as_text=True)
            self.assertNotIn('id="account-registration-nav"', html)
            self.assertNotIn('id="panel-account-registration"', html)
        self.assertIsNone(User.query.filter_by(username='fixture_created').first())
        self.assertEqual(self.target.password_hash, self.fixture_hash)

    def test_inactive_and_stale_admin_sessions_cannot_manage_accounts(self):
        for changes, session_version in (({'is_active': False}, 0),
                                         ({'account_status': 'SUSPENDED'}, 0),
                                         ({'auth_version': 1}, 0)):
            with self.subTest(changes=changes):
                self.admin.is_active, self.admin.account_status, self.admin.auth_version = True, 'ACTIVE', 0
                for key, value in changes.items():
                    setattr(self.admin, key, value)
                db.session.commit()
                for method, path, payload in self.account_endpoints():
                    self.authenticate(auth_version=session_version)
                    self.assertEqual(self.client.open(path, method=method, json=payload).status_code, 401)
        self.assertEqual(User.query.count(), 2)

    def test_admin_registration_ui_and_roles_load_without_template_error(self):
        self.authenticate()
        html = self.client.get('/').get_data(as_text=True)
        for required in ('id="account-registration-nav"', 'Account Registration',
                         'id="panel-account-registration"', 'id="admin-register-form"',
                         'id="admin-forgot-form"', 'id="admin-reset-form"'):
            self.assertIn(required, html)
        roles = self.client.get('/api/auth/available-roles')
        self.assertEqual(roles.status_code, 200)
        self.assertIn('PROCUREMENT', roles.get_json()['roles'])
        self.assertNotIn('ADMIN', roles.get_json()['roles'])
        self.assertNotIn('CBAO', roles.get_json()['roles'])

    def test_existing_approval_controls_are_inside_account_registration(self):
        self.authenticate()
        html = self.client.get('/').get_data(as_text=True)
        panel = html.split('<section class="panel" id="panel-account-registration"', 1)[1].split('</section>', 1)[0]
        for required in ('Pending Account Registrations', 'id="pending-user-list"',
                         'id="pending-user-count"', 'onclick="refreshAccountAdministration()"'):
            self.assertIn(required, panel)
        self.assertEqual(html.count('id="pending-user-list"'), 1)
        self.assertEqual(html.count('id="pending-user-count"'), 1)
        self.assertNotIn('id="admin-approval-nav"', html)
        self.assertNotIn('id="panel-admin-approval"', html)
        self.assertIn('onclick="approvePendingUser(${user.id}, this)"', html)
        self.assertIn('onclick="rejectPendingUser(${user.id}, this)"', html)
        self.assertIn('onclick="togglePendingUser(${user.id})"', html)

    def test_admin_creates_hashed_pending_account_in_existing_user_model(self):
        self.authenticate()
        response = self.register()
        self.assertEqual(response.status_code, 201)
        created = User.query.filter_by(username='fixture_created').one()
        self.assertEqual(User.__tablename__, 'users')
        self.assertEqual(User.query.count(), 3)
        self.assertEqual(created.full_name, 'Fixture Test Procurement')
        self.assertEqual((created.role, created.office, created.account_status, created.is_active),
                         ('PROCUREMENT', 'PROCUREMENT', 'PENDING', False))
        self.assertNotEqual(created.password_hash, self.PASSWORD)
        self.assertTrue(check_password_hash(created.password_hash, self.PASSWORD))
        self.assert_no_credentials(response.get_json(), created.password_hash)
        self.assert_no_credentials(created.to_dict(), created.password_hash)
        self.assert_no_credentials(self.client.get('/api/admin/pending-users').get_json(), created.password_hash)
        self.assert_no_credentials(self.client.get('/api/admin/audit-log').get_json(), created.password_hash)
        self.assertEqual(self.client.get('/api/auth/me').get_json()['user']['id'], self.admin.id)

    def test_required_registration_fields_are_preserved(self):
        self.authenticate()
        for field in ('first_name', 'last_name', 'email', 'username', 'password',
                      'password_confirmation', 'role', 'office'):
            with self.subTest(field=field):
                self.assertEqual(self.register(**{field: ''}).status_code, 400)
        self.assertEqual(User.query.count(), 2)

    def test_email_password_role_and_office_validation_is_preserved(self):
        self.authenticate()
        cases = (
            ({'email': 'invalid-email'}, 400),
            ({'password': 'short', 'password_confirmation': 'short'}, 400),
            ({'password_confirmation': 'fixture-mismatch'}, 400),
            ({'role': 'ADMIN', 'office': 'ADMINISTRATION'}, 403),
            ({'role': 'UNKNOWN_ROLE'}, 403),
            ({'office': 'UNKNOWN_OFFICE'}, 400),
            ({'role': 'CED', 'office': 'CAS'}, 400),
        )
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.register(**changes).status_code, expected)
        self.assertEqual(User.query.count(), 2)

    def test_unique_username_email_and_reserved_role_are_preserved(self):
        self.authenticate()
        self.assertEqual(self.register().status_code, 201)
        cases = (
            ({'role': 'EO', 'office': 'EO', 'email': 'another@test.local'}, 'username'),
            ({'role': 'EO', 'office': 'EO', 'username': 'fixture_second'}, 'email'),
            ({'username': 'fixture_second', 'email': 'another@test.local'}, 'role'),
        )
        for changes, expected in cases:
            with self.subTest(rule=expected):
                response = self.register(**changes)
                self.assertEqual(response.status_code, 409)
                self.assertIn(expected, response.get_json()['error'].lower())
        roles = self.client.get('/api/auth/available-roles').get_json()
        self.assertNotIn('PROCUREMENT', roles['roles'])
        self.assertFalse(next(row for row in roles['role_options'] if row['name'] == 'PROCUREMENT')['available'])
        self.assertEqual(User.query.count(), 3)

    def test_custom_active_office_links_existing_college(self):
        office = College(code='TEST_OFFICE', name='Fixture operational office', is_active=True)
        db.session.add(office)
        db.session.commit()
        self.authenticate()
        self.assertEqual(self.register(role=office.code, office=office.code).status_code, 201)
        self.assertEqual(User.query.filter_by(username='fixture_created').one().college_id, office.id)

    def test_admin_created_account_uses_existing_status_and_approval_flow(self):
        self.authenticate()
        registered = self.register(role='CED', office='CED')
        self.assertEqual(registered.status_code, 201)
        token = registered.get_json()['registration_token']
        created = User.query.filter_by(username='fixture_created').one()
        public = application.app.test_client()
        pending = public.post('/api/auth/registration-status', json={'registration_token': token})
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.get_json()['account_status'], 'PENDING')
        self.assertEqual(set(pending.get_json()), {'account_status', 'message'})
        blocked = public.post('/api/auth/login', json={'username': created.username, 'password': self.PASSWORD})
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.get_json()['code'], 'ACCOUNT_PENDING')
        self.assertEqual(self.client.post(f'/api/admin/pending-users/{created.id}/approve').status_code, 200)
        self.assertEqual((created.account_status, created.is_active), ('ACTIVE', True))
        self.assertEqual(db.session.get(College, created.college_id).code, 'CED')
        active = public.post('/api/auth/registration-status', json={'registration_token': token})
        self.assertEqual(active.get_json()['account_status'], 'ACTIVE')
        self.assertEqual(public.post('/api/auth/login', json={
            'username': created.username, 'password': self.PASSWORD,
        }).status_code, 200)
        self.assertEqual(PPMPNotification.query.filter_by(recipient_id=created.id, title='Account approved').count(), 1)

    def test_existing_login_remember_logout_and_status_reference_security_remain(self):
        original_hash = self.target.password_hash
        response = self.client.post('/api/auth/login', json={
            'username': self.target.username, 'password': self.PASSWORD, 'remember_me': True,
        })
        self.assertEqual(response.status_code, 200)
        self.assert_no_credentials(response.get_json())
        with self.client.session_transaction() as session:
            self.assertTrue(session.permanent)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.target.password_hash, original_hash)
        for token in ('', 'fixture-invalid-reference'):
            self.assertEqual(self.client.post('/api/auth/registration-status', json={
                'registration_token': token,
            }).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/login', json={
            'username': self.target.username, 'password': 'fixture-incorrect-password',
        }).status_code, 401)

    def test_admin_recovery_preserves_existing_unconfigured_delivery_behavior(self):
        self.authenticate()
        known = self.client.post('/api/auth/forgot-password', json={'email': self.target.email})
        unknown = self.client.post('/api/auth/forgot-password', json={'email': 'fixture-unknown@test.local'})
        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.get_json(), unknown.get_json())
        self.assertEqual(known.get_json()['message'], application.PASSWORD_RESET_REQUEST_MESSAGE)
        self.assertEqual(PasswordResetRequest.query.count(), 0)
        self.assertEqual(self.client.post('/api/auth/forgot-password', json={'email': 'bad'}).status_code, 400)
        self.assert_no_credentials(known.get_json())

    def test_reset_requires_existing_code_and_keeps_password_validation(self):
        self.authenticate()
        self.assertEqual(self.client.post('/api/auth/reset-password', json=self.reset_payload()).status_code, 400)
        request = self.reset_request()
        for changes in ({'email': 'bad'}, {'code': ''},
                        {'password': 'short', 'password_confirmation': 'short'},
                        {'password_confirmation': 'fixture-mismatch'},
                        {'password': self.PASSWORD, 'password_confirmation': self.PASSWORD}):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post('/api/auth/reset-password',
                                                 json=self.reset_payload(**changes)).status_code, 400)
        self.assertEqual(self.target.password_hash, self.fixture_hash)
        self.assertEqual(request.status, 'CODE_ISSUED')

    def test_admin_reset_hashes_password_consumes_code_and_revokes_target_sessions(self):
        other = application.app.test_client()
        self.authenticate(self.target, client=other)
        request = self.reset_request()
        previous = self.reset_request(status='PENDING', token_hash=None)
        self.authenticate()
        response = self.client.post('/api/auth/reset-password', json=self.reset_payload())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json().get('session_invalidated', False))
        self.assertTrue(check_password_hash(self.target.password_hash, self.NEW_PASSWORD))
        self.assertFalse(check_password_hash(self.target.password_hash, self.PASSWORD))
        self.assertEqual((self.target.auth_version, request.status, request.token_hash), (1, 'USED', None))
        self.assertIsNotNone(request.used_at)
        self.assertEqual(previous.status, 'EXPIRED')
        self.assertEqual(other.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.get('/api/auth/me').get_json()['user']['id'], self.admin.id)
        self.assertEqual(self.client.post('/api/auth/reset-password', json=self.reset_payload()).status_code, 400)
        self.assert_no_credentials(response.get_json(), self.target.password_hash, self.CODE)
        self.assert_no_credentials(self.client.get('/api/admin/audit-log').get_json(), self.target.password_hash, self.CODE)
        public = application.app.test_client()
        self.assertEqual(public.post('/api/auth/login', json={
            'username': self.target.username, 'password': self.PASSWORD,
        }).status_code, 401)
        self.assertEqual(public.post('/api/auth/login', json={
            'username': self.target.username, 'password': self.NEW_PASSWORD,
        }).status_code, 200)

    def test_admin_self_reset_invalidates_its_own_session(self):
        self.reset_request(self.admin)
        self.authenticate()
        response = self.client.post('/api/auth/reset-password', json=self.reset_payload(self.admin))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['session_invalidated'])
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertTrue(check_password_hash(self.admin.password_hash, self.NEW_PASSWORD))

    def test_expired_and_five_incorrect_reset_attempts_do_not_change_password(self):
        expired = self.reset_request(expires_at=datetime.utcnow() - timedelta(seconds=1))
        self.authenticate()
        self.assertEqual(self.client.post('/api/auth/reset-password', json=self.reset_payload()).status_code, 400)
        self.assertEqual(expired.status, 'EXPIRED')
        current = self.reset_request()
        for _ in range(5):
            self.assertEqual(self.client.post('/api/auth/reset-password', json=self.reset_payload(
                code='fixture-wrong-code',
            )).status_code, 400)
        self.assertEqual((current.status, current.attempt_count), ('EXPIRED', 5))
        self.assertEqual(self.client.post('/api/auth/reset-password', json=self.reset_payload()).status_code, 400)
        self.assertEqual(self.target.password_hash, self.fixture_hash)

    def test_cross_origin_account_mutations_are_rejected(self):
        self.reset_request()
        self.authenticate()
        for method, path, payload in self.account_endpoints():
            if method != 'POST':
                continue
            with self.subTest(path=path):
                response = self.client.open(path, method=method, json=payload,
                                            headers={'Origin': 'https://fixture-other.example'})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(User.query.count(), 2)
        self.assertEqual(self.target.password_hash, self.fixture_hash)


if __name__ == '__main__':
    unittest.main()
