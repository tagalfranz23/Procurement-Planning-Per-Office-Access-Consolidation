# Procurement Management System — Master Revision Record

**System:** Web-Based Procurement Management System / PPMP and APP Platform  
**Institution:** Isabela State University — Cauayan City  
**Authoritative record updated:** 2026-10-15 (Asia/Manila)  
**Repository:** `C:\Users\Admin\Downloads\PPMP_System\ppmp`

This is the single authoritative record for past revisions, implemented changes, database changes, security decisions, verification evidence, known limitations, and newly requested work. Older plans and change logs are historical inputs; when they conflict with this file, this file reflects the latest inspected state.

## Status legend

- **Implemented:** Present in the current source code.
- **Verified:** Inspected and exercised by a stated test or runtime check.
- **Partial:** Some required behavior exists, but the complete requirement is not finished.
- **Requested:** Included in an approved revision specification but not yet implemented.
- **Blocked:** Requires a business decision, credentials, infrastructure, or data reconciliation.
- **Superseded:** Historical behavior replaced by a later revision.

Do not describe a requested or partial feature as complete without adding verification evidence here.

---

# 1. Current architecture

## Application

- Python Flask application with Flask-SQLAlchemy.
- SQLite database by default through Flask-SQLAlchemy; MariaDB remains available through an explicit `DATABASE_URL` for recovery or alternate deployment.
- Server-rendered login and single-page dashboard templates.
- `openpyxl` Excel reporting and ReportLab server-side PDF reporting.
- Optional local Socket.IO/Node notification helper; core Flask workflows do not depend on it.

## Identity and access

- One user row contains one current operational role.
- `users.email` is unique.
- `users.role` is nullable and unique, enforcing one current account per role.
- An archived or rejected account preserves its former assignment in `released_role` and releases the current role.
- Account lifecycle values: `PENDING`, `ACTIVE`, `SUSPENDED`, `ARCHIVED`, and `REJECTED`.
- Office and role remain separate user attributes.
- Module access is derived from server-side role permissions; Procurement, EO, and Budget do not require duplicate PPMP/APP accounts.
- Permissions are currently defined in the Flask application’s `ROLE_PERMISSIONS` mapping rather than in dedicated database tables.

## Primary workflows

- PPMP: Office Draft/Returned → Submitted → EO Review → Procurement Review → Admin Approved.
- PPMP Wishlist: one PPMP document contains multiple independent 12-column procurement rows; adding or editing a Draft row does not create an order.
- Wishlist requests: an authorized office user explicitly selects an item from an Approved PPMP → Pending Admin Approval → Approved/Returned/Rejected → Processing/Completed.
- Legacy master/custom request data remains preserved for backward compatibility, but the primary PPMP Wishlist navigation opens the official 12-column planning document.
- Consolidation: Approved PPMP → persisted consolidation batch/source links → APP draft.
- APP/APP-CSE: Procurement → BAC Chairman → EO → Budget → Admin Approval → Finalized.
- Optional surveys: EO creates and targets selected colleges; selected colleges may respond.
- Department PPMP: one annual CSE-based response from each of CED, CBM, CAS, CCSICT, CCJE, IAT, and PS goes directly to Academic Affairs. AA prepares a separate editable review copy for each submitted department PPMP. The annual collection is Ready to Submit after all seven departments submit or report No PPMP and every submitted copy is Reviewed.

---

# 2. Revision history

## 2026-10-15 - Local Department PPMP schema activation

**Status:** Activated and verified on the local SQLite database after the original implementation.

- Created and verified an SQLite online backup of `ppmp/ppmp.sqlite` at `ppmp/backups/ppmp_before_department_schema_20261015_013250_261181.sqlite` before activation.
- Ran the existing `ensure_department_wishlist_schema()` routine to create exactly the four missing `department_ppmp_*` tables. Broader migrations were not run; the new tables are empty.
- Per-table SHA-256 row fingerprints confirmed that all 160 existing rows across 27 tables exactly matched the pre-activation backup. SQLite `quick_check` and `initialize_database(apply_migrations=False)` both passed.
- No application behavior was changed, no accounts or demo rows were created, and no remote database was touched. The implementation-stage notes below remain historical statements about that earlier work.

## 2026-10-15 - Department PPMP intake and Academic Affairs review collection

**Status:** Implemented and locally verified, subject to the three confirmed pre-existing legacy UI test failures recorded below. Production PostgreSQL deployment has not been observed.

### Approved workflow

- Each of CED, CBM, CAS, CCSICT, CCJE, IAT, and PS has one role-scoped account, using the existing one-account-per-role registration and Administrator approval rules.
- A department selects available entries from the shared CSE Master List, enters quantities and optional notes, and submits one PPMP request for its fiscal year directly to AA. It can instead record No PPMP. A No PPMP response can later be replaced by that year's request; a submitted PPMP remains locked.
- Only AA receives the **Department Wishlist** sidebar and access to the seven-department collection. Each department receives its own **Department PPMP** workspace and original submission. Other roles, including Administrator, cannot open the new intake/review API.
- AA creates one review copy per submitted PPMP and may edit its item details, quantities, unit costs and notes, add/remove lines, save Draft, and mark Reviewed. Changes apply to the AA copy and preserve the submitted original and CSE catalog values.
- Editing a reviewed copy makes it Draft until AA marks it Reviewed again. The collection is Ready to Submit only when all seven departments are Submitted or No PPMP and every Submitted department has a Reviewed copy.
- The collection keeps separate reviewed PPMPs for departments with requests and explicit No PPMP responses for the rest. Ready to Submit is a computed readiness state; no downstream recipient or submission transition was specified for this revision.

### Data, security, and deployment

- Added `department_ppmp_submissions`, `department_ppmp_submission_items`, `department_ppmp_review_copies`, and `department_ppmp_review_items`. The annual department header and one review copy per submission have database uniqueness constraints; positive quantities and non-negative costs are constrained.
- Added authenticated, server-authorized `/api/department-wishlist` intake and AA-only review-copy routes. Submission and review actions retain actor/timestamp metadata, audit events, and existing in-system notification delivery.
- Existing PPMP records/orders, EO review, consolidation, APP, reports, CSE maintenance, and account lifecycle remain in their existing workflow. Department roles receive only the new intake permissions.
- No local or production database was migrated, reset, seeded, or altered while implementing this revision. On Render with PostgreSQL, WSGI startup uses Render's built-in `RENDER=true` flag to add only the four new department tables if missing, using a transaction and PostgreSQL advisory lock. It then performs the normal read-only schema verification. This narrow bootstrap does not run unrelated existing-table migrations, reset/seed data, or require a paid pre-deploy command. Other installations use the existing `python app.py --migrate-only` path after backup. Render documents its built-in flag in [Environment Variables and Secrets](https://render.com/docs/environment-variables).

### Affected files and verification

- Application: `ppmp/models.py`, `ppmp/app.py`, `ppmp/wsgi.py`, and `ppmp/templates/index.html`; workflow regression: `ppmp/tests/test_revision.py`; documentation: this record, living manual, README, changelog, and generated controlled PDF.
- The isolated annual department-to-AA regression passed, including own-department routing, duplicate annual submission rejection, AA copy editing, original/catalog preservation, seven-department readiness, and denial for Administrator.
- Python compilation and Jinja template validation passed. The regression run executed 35 tests: 32 passed and three legacy UI assertions failed. The same three failures were reproduced on the downloaded pre-revision GitHub baseline `da3e895`, establishing that they preceded this change. The PDF-dependent regression ran after PyPDF2 was installed.
- Applying the four-table additive schema routine twice to an isolated SQLite database succeeded and preserved its existing user and CSE catalog records. No live database was used for this check.
- Headless Edge passed 32 workflow/UI assertions with zero uncaught JavaScript errors. Checks covered all seven department landings and annual responses, the AA-only menu with Administrator/Cashier controls hidden, CSE search and year-specific draft persistence, submission of both visible and search-hidden selected rows, long catalog names, AA copy creation/editing/review with safely handled quoted text, original preservation, and readiness becoming complete, resetting on Draft edits, and restoring after re-review. Dashboard and Login inline scripts parsed successfully. Layout screenshots were visually inspected.
- Production PostgreSQL deployment and its startup bootstrap have not been observed. The verification evidence above is local and isolated; no live database or production workflow was changed by these checks.

## 2026-09-04 - Offices management removal and official 12-column PPMP Wishlist correction

**Status:** Implemented and verified.

### User-requested removal

- Removed the Administrator **Offices** navigation entry, the Administration Only Offices panel, the Managed Offices list, and all Add/Edit/Activate/Deactivate controls shown in the supplied screenshot.
- Removed the corresponding `/api/admin/offices` create/list/update management endpoints and their browser handlers.
- Removed the Managed Offices statistic and its unnecessary Administrator dashboard request.
- Did not delete or alter `colleges` rows, foreign keys, users, PPMP history, consolidation sources, or APP records. Office identity remains an internal ownership and authorization relationship, and the existing read-only `/api/colleges` directory remains available to authorized workflows such as EO requesting a PPMP from a selected office.
- Account approval now safely links or creates the structural row for a configured office code, so removing the management screen does not recreate the earlier account-approval blocker. Dynamic or inactive unknown offices are not silently accepted.

### Reference-image and PPMP/Wishlist correction

- Confirmed that the two supplied FY2026 paper forms map to the official 12 fields already represented by `PPMPRecordItem`: description/objective, project type, quantity/size, procurement method, pre-procurement Yes/No, start, end, delivery, fund source, estimated budget, supporting documents, and remarks.
- Made **PPMP Wishlist** navigation open the official 12-column PPMP planning workspace for Administrator and authorized office users. The Administrator sees the same records and complete 12-column table.
- Preserved controlled dropdowns for procurement method and pre-procurement Yes/No, month-based scheduling including As Needed, Decimal monetary storage, multiple rows, Draft editing, submission locking, comments, return/revision, and separate approval history.
- Restored the separate request action for eligible rows in an Approved PPMP. Creating/editing a PPMP Wishlist row still does not create an order.
- A selected approved PPMP Wishlist row now creates a `PPMPOrder` in **Pending Admin Approval**, stores an immutable 12-field snapshot in `PPMPOrderItem`, and references the originating `PPMPRecordItem` and already-approved procurement row.
- Administrator Approve/Return/Reject is enforced server-side. Approval of the Wishlist request does not duplicate the existing `ppmp_items` consolidation source.
- Kept the PPMP document workflow separate from the Wishlist request workflow and retained authorization checks preventing one office from requesting another office's PPMP rows.
- No rows from the photographed forms were inserted into the live database. The images define the real field structure and valid value patterns; actual procurement records continue to come only from authorized user entry, preventing fabricated or duplicate production data.

### Files/modules changed

- `ppmp/app.py`: removed Offices management APIs, protected account-to-office linking, restored approved-PPMP-item request creation, direct Administrator order decisions, audit events, notifications, reporting sources, and pending counts.
- `ppmp/models.py`: clarified Wishlist request status/source serialization while preserving historical statuses.
- `ppmp/templates/index.html`: removed Offices management UI, made the 12-column PPMP Wishlist primary, enabled eligible row selection, and separated PPMP Records from Wishlist Requests in labels and actions.
- `ppmp/templates/login.html`: reused the existing ISU seal as the browser favicon.
- `ppmp/tests/test_revision.py`: replaced removed-office tests and added full 12-column Draft → PPMP review → Approved → Wishlist request → Administrator approval coverage, including cross-office denial and no-duplicate materialization.

### Verification evidence

- Fresh pre-change backup: `backups/ppmp_db_before_offices_removal_20260904.sql` (45,273 bytes).
- `python -m py_compile app.py models.py tests\test_revision.py`: passed.
- `python -m unittest discover -s tests -q`: 20 tests passed.
- Playwright Administrator browser check: 0 Offices navigation entries, 0 Offices panels, primary PPMP planning panel visible, 12 numbered columns rendered, Column 4 rendered as a select, Column 5 exposed only Select/Yes/No, and no browser console or page errors.
- The optional Node/Socket.IO client now connects only when `WEBSOCKET_URL` is configured, preventing connection errors when the optional notification hub is not running.
- Read-only MariaDB preflight: 22 expected tables; no duplicate roles/emails; no legacy placeholder roles; no APP reconciliation conflicts.
- Production row counts were identical before and after migration: 1 office identity, 4 users, 0 PPMP documents, 0 PPMP document rows, 1 preserved legacy Wishlist order, 1 preserved order item, 0 materialized PPMP items, and 0 APP plans.
- The preserved `LEGACY-WR-00000001` remained at its existing `Procurement Review` status; no historical status or content was overwritten.
- No production database reset, deletion, or sample-data insertion was performed.

### Superseded behavior

- This revision supersedes the 2026-09-04 sidebar decision that exposed **Offices** and made the seven-column master catalog the primary Wishlist screen.
- Historical master/custom request records and APIs remain compatible so existing data is not destroyed, but they are not used as the official 12-column PPMP document or as a substitute for a PPMP Wishlist row.

---

## 2026-09-04 - Administrator Dashboard and PPMP ordering major revision

**Status:** Implemented, migrated, and verified.

### Objective and implemented behavior

- Simplified the Administrator sidebar to Admin Overview, PPMP Wishlist, PPMP Requests, Account Approval, APP Plans, Reports, and Offices. The Administrator PPMP/APP Dashboard sidebar links, duplicate Wishlist link, Consolidation link, and old Management Offices/Office Directory navigation were removed.
- Preserved separate PPMP and APP Dashboard routes and retained both shortcuts on Admin Overview.
- Changed Accounts & Recovery to Account Approval and retained backend enforcement that pending/rejected accounts cannot sign in. Forgot Password remains separate and does not create an Administrator reset queue.
- Made the database-backed master PPMP Wishlist the visible Wishlist page. Administrator item creation writes to `wishlist_items`; office-user unlisted items write only to `ppmp_order_items`.
- Added mixed master/custom PPMP order submission with server-side validation and immutable request snapshots. Browser-supplied master item descriptions, prices, units, and categories are not trusted.
- Routed submitted orders through Office -> EO/AA -> Procurement -> Administrator review. Final approval materializes procurement rows without inserting custom items into the master Wishlist.
- Connected Administrator report cards, status/source donuts, office/item bars, trend line, and detailed table to real `ppmp_orders` and `ppmp_order_items` records.
- Kept PPMP planning documents accessible inside the PPMP Wishlist workspace without adding another Administrator sidebar module.
- Retained the global responsive loading overlay, 30-second request timeout, `finally` cleanup, and duplicate-submit button guards.

### Root causes corrected

- The new master/custom ordering interface had been hidden as a legacy panel while the visible page and `/api/ppmp-orders` route still used the superseded `wishlist_item_ids` contract.
- `PPMPOrder`/`PPMPOrderItem` lacked the order-level procurement fields and master/custom source columns required by the new interface.
- Report JavaScript expected order-shaped records and source-distribution data, but the report route returned PPMP-document records.
- Legacy `Pending Admin Approval` Wishlist requests mapped to the wrong stage in the revised multi-review workflow.
- During final workspace synchronization, the Flask/database bootstrap lines in `app.py` were collapsed, causing `SyntaxError: unmatched ')'` at line 148. The damaged bootstrap and authentication decorator were restored and reverified.

### Database migration and data protection

- Fresh backup created before live migration: `backups/ppmp_db_before_admin_major_revision_20260904.sql` (33,020 bytes).
- Applied only additive schema changes with `python app.py --migrate-only`; no database reset or fake business data was used.
- Added four required tables to the live MariaDB schema: `ppmp_records`, `ppmp_record_items`, `ppmp_orders`, and `ppmp_order_items`.
- Added/backfilled order fiscal year, fund source, procurement mode/type, quarter, master item reference, category, unit price, and custom-item indicator fields.
- Preserved legacy Wishlist request sources and migrated their stage idempotently.
- Archived the previously designated legacy `franz`/`COLLEGE_ENCODER` account by releasing its current role while preserving notification and audit foreign-key history; the row was not deleted.

### Files/modules changed

- `ppmp/app.py`: Flask/database bootstrap repair, additive migration, master/custom PPMP order API, workflow transitions, materialization, dashboard counts, and real order reports.
- `ppmp/models.py`: revised PPMP order statuses and master/custom request-item schema/serialization.
- `ppmp/templates/index.html`: final Administrator navigation, visible master Wishlist/order UI, PPMP planning access, central request display, reporting, and loading guards.
- `ppmp/tests/test_revision.py`: migration idempotence, navigation/panel state, master/custom separation, approval, authorization, reports, loading, and regression assertions.

### Verification evidence

- `python -m py_compile app.py models.py tests\test_revision.py`: passed.
- `python -m unittest discover -s tests -v`: 19 tests passed.
- `python scripts\db_preflight.py`: MariaDB 12.2.2 connected; 22 tables present; no duplicate roles/emails; no legacy placeholder roles; migration readiness passed.
- `python app.py`: normal startup passed at `http://127.0.0.1:5000`.
- Live HTTP checks: login page returned 200, role-availability API returned 200, and Forgot Password was visible.

### Remaining operational risks

- The running server is Flask's development server; production deployment still requires a WSGI server and HTTPS termination.
- Replace the development Flask secret and default/bootstrap Administrator password through environment variables before production.
- SMTP delivery remains intentionally deferred; the current Forgot Password page reports that limitation without creating an Administrator approval queue.
- Python 3.13 reports non-blocking `datetime.utcnow()` deprecation warnings; these do not prevent startup but should be migrated to timezone-aware timestamps in a separate controlled revision.

---

## 2026-08-27 - Safe PPMP Dashboard component removal

**Status:** Implemented and verified.

- Removed only these PPMP Dashboard presentation components: **Budget by Office**, **Budget by Fund Source**, **Budget by Procurement Type**, **Budget by Quarter**, and **Total Procurement Amount**.
- Removed their dashboard-only DOM elements, JavaScript renderer, the dashboard API's unused `total_amount` field, and the summary API's dashboard-only `by_type` aggregation.
- Preserved `total_amount`, `by_college`, `by_fund`, and `by_quarter` in the shared summary/report contract because the Reports panel still depends on those values.
- Preserved PPMP procurement type, fund source, quarter, unit cost, and generated total cost fields because PPMP entry, filters, reports, consolidation, and exports still depend on them.
- Preserved Wishlist `category` and `estimated_cost` fields, UI controls, API validation, and stored values because they are owned by the active Wishlist workflow rather than the removed PPMP Dashboard.
- No table, column, constraint, index, relationship, migration, or production record was deleted or modified. A database rollback is therefore unnecessary.
- Verification: isolated regression tests confirm the removed components and exclusive API data are absent while PPMP dashboards, PPMP entry/filter fields, Reports, and Wishlist controls remain available. Source compilation and the complete test suite were also run.
- Rollback plan: restore the removed PPMP Dashboard markup/renderer and its two exclusive response fields from source history. No database restoration is required.

## 2026-08-26 — Administrator-assisted Forgot Password recovery

**Status:** Implemented and verified; SMTP delivery intentionally deferred.

- Added a visible **Forgot Password?** action plus request and new-password views on the login page.
- Added generic reset-request responses so the public endpoint does not disclose whether an email address exists.
- Added administrator-only password recovery requests inside **Accounts & Recovery**.
- Until SMTP is configured, an administrator must verify the requester offline and issue a cryptographically random one-time code that is shown only in the issuance response.
- Reset codes are stored only as SHA-256 hashes, expire after 15 minutes, allow no more than five failed comparisons, and become unusable after a successful reset.
- Added request/verification throttling, password confirmation and hashing, audit events, and user notification after a password change.
- Added `users.auth_version`; a successful reset increments it and invalidates older authenticated sessions.
- Added the additive `password_reset_requests` table and `users.auth_version` migration. Existing operational data is not deleted or reset.
- Added ReportLab to the Python dependency manifest because authenticated Flask PDF exports already import it.
- Verification: Python compilation and all 12 isolated regression tests pass, including public-response parity, administrator authorization, invalid-code rejection, successful reset, old-password rejection, code replay prevention, and old-session revocation.

## 2026-08-26 — Administrator Management Offices and separate PPMP/APP dashboards

**Status:** Implemented and verified.

- Replaced the universal Colleges sidebar selector with an administrator-only **Management Offices** dropdown containing Office Directory and Add Office actions.
- Added protected administrator APIs to list, create, edit, activate, and deactivate managed offices without deleting linked PPMP or account history.
- Linked matching registrations and existing office accounts to managed office records so authorized users can create and access their own PPMP items.
- Kept Management Offices markup out of non-administrator dashboard responses and retained server-side administrator authorization on every management endpoint.
- Added a distinct Admin Overview plus separate PPMP Dashboard and APP Dashboard panels backed by separate real-data summary APIs.
- Replaced obsolete PPMP Pending/Cancelled UI actions with the recorded Office → EO → Procurement → Admin workflow and required reasons for return/reject actions.
- Added role-aware PPMP and APP action buttons so dashboards no longer display actions that the signed-in role cannot perform.
- Changed visible organizational terminology from College to Office while retaining the existing `colleges` table and foreign keys for safe backward compatibility.
- No production records were seeded, reset, deleted, or migrated for this revision; the existing organizational table was reused.
- Verification: Python compilation passed and all 11 isolated regression tests passed, including admin-only rendering, office authorization, account-to-office linking and approval safeguards, distinct dashboards, database startup safety, and the complete PPMP approval chain.
- Browser automation was attempted through the Playwright workflow, but the local environment has no Node.js runtime; isolated Flask rendering/API integration checks were used as the available fallback.

## 2026-08-17 — MariaDB production storage and removal of sample transactions

**Status:** Implemented; later migration guidance corrected.

- Replaced in-memory PPMP storage with SQLAlchemy/MariaDB models and queries.
- Removed automatic sample PPMP, budget, approval, notification, report, and dashboard data.
- Added database-backed users, colleges, PPMP items, audit records, notifications, and consolidation logs.
- Added an initial administrator bootstrap with a Werkzeug password hash.
- Added a destructive `--reset-database` development command.
- Removed legacy schema/demo navigation and Node demo-database fallbacks.
- Added real empty states instead of sample dashboard statistics.

**Important correction:** `--reset-database` must never be used as an existing-system migration. It intentionally deletes operational records and is only for a disposable development database.

## 2026-08-17 — MariaDB connection hardening

**Status:** Implemented; later strengthened.

- Standardized direct `mysql.connector` connectivity.
- Added actionable handling for unsupported `auth_gssapi_client` authentication.
- Added MariaDB service-account guidance.
- Added connection validation before application startup.
- Later revisions restored environment configuration through `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DATABASE_URL`, and `FLASK_SECRET_KEY`.

## 2026-08-17 — Username authentication

**Status:** Implemented.

- Added session-based username/password login.
- Added password-hash verification, remembered sessions, logout, and current-user APIs.
- Protected non-public API routes from unauthenticated access.
- Added ISU branding and login loading feedback.

## 2026-08-17 — Role-selector login/registration

**Status:** Superseded.

- Historical UI separated Administrator, PPMP Users, and APP Users at login.
- This approach was later replaced because operational roles may require both PPMP and APP permissions under one account.
- Current login is a single account login; registration selects an available operational role and office.

## 2026-08-17 — Responsive/collapsible navigation

**Status:** Implemented.

- Added desktop sidebar collapse and mobile sidebar open/close controls.
- Preserved dashboard and college-filter navigation.

## 2026-08-20 — Dashboard and authentication UX refinements

**Status:** Implemented.

- Repaired logout loading, session invalidation, socket cleanup, and history replacement.
- Prevented indefinite Socket.IO reconnect attempts when the optional service is offline.
- Improved navigation, password controls, keyboard accessibility, and transitions.
- Corrected same-origin dashboard API requests so browser session cookies are retained.
- Initialized optional live-update status as Offline instead of displaying stale connection state.

## 2026-08-24 — Administrator account approval

**Status:** Implemented.

- Added an administrator-only account-approval view.
- Added protected APIs for pending-account listing and activation.
- Registration creates administrator notifications.
- Approval activates the existing account and notifies the user.
- Pending listings now use `account_status = PENDING`, not every inactive account.
- Preserved server-side administrator authorization.

## 2026-08-25 — Major PPMP/APP architecture revision

**Status:** Implemented in major part; gaps are listed in Section 5.

### Account and role rules

- Expanded placeholder module roles into operational roles/offices.
- Enforced unique email and unique live role at the database level.
- Pending registrations reserve roles.
- Added transaction flush and `IntegrityError` rollback for concurrent registrations.
- Added account suspension, archival/rejection, and historical role release.
- Added a role-availability registration API.
- Preserved one account for Procurement, EO, and Budget across both modules.

### Authorization and security

- Added server-side permission checks for PPMP, Wishlist, consolidation, APP, reports, exports, surveys, and administration.
- Added record-level PPMP ownership/college checks.
- Prevented browser-submitted PPMP status fields from directly controlling workflow state.
- Added workflow transition validation by role, status, permission, and ownership.
- Added same-origin rejection for cross-site mutating API requests.
- Strengthened session cookie settings (`HttpOnly`, `SameSite=Lax`, production Secure flag).
- Added audit IP capture where available.

### PPMP

- Added controlled Draft, Submitted, EO Review, Procurement Review, Returned, Approved, and Rejected stages.
- Added return/resubmit behavior.
- Added EO college submission requests and notifications.
- Added persistent PPMP comments/notes.
- Preserved approved source PPMP records during consolidation.

### Wishlist

- Added persisted Wishlist items and Wishlist requests.
- Added item search/status filtering and quantity/cost validation.
- Restricted edits/deletes to authorized owners/admin users and editable states.
- Required administrator decision before processing.
- Added approve, reject, and return transitions with notifications and audit events.

### Surveys

- Added optional surveys and college recipients.
- Added EO creation, selected-college access, response tracking, and notifications.
- Surveys do not block normal PPMP processing.

### Consolidation and APP

- Added persisted fiscal-year/APP-cycle consolidation batches.
- Added source links that prevent a PPMP item from being consolidated twice.
- Added unique fiscal-year/cycle enforcement after conflict checks.
- Required APP creation to reference a non-empty same-year consolidation batch.
- Kept APP and APP-CSE distinguishable through `plan_type`.
- Added sequential approval history and next-actor notifications.
- Added one APP/APP-CSE per office, fiscal year, and plan type.

### Reports and exports

- Scoped summary, PDF, and Excel data to records authorized for the current user.
- Replaced browser-supplied PDF data with server-side database queries.
- Added university/report headers, generation identity/time, totals, table formatting, and PDF page numbering.
- Added export audit events.

### Dashboard and loading

- Dashboard navigation now uses permissions returned by the authenticated-user API.
- Added functional PPMP Request, Wishlist, consolidation, APP, and account-approval panels.
- Added real empty states and removed fake statistics.
- Added the prescribed animated loader to login and dashboard flows.
- Added duplicate-button prevention and a maximum 30-second browser request timeout.

## 2026-08-25 — Role migration preflight and safe migration command

**Status:** Implemented and used.

- Added read-only `scripts/db_preflight.py`.
- Added `python app.py --migrate-only` for additive schema changes without starting the server or resetting data.
- Added conflict reporting for duplicate emails, duplicate roles, legacy roles, and unlinked APP records.
- Corrected documentation that previously recommended destructive reset as deployment migration.

## 2026-08-25 — APP `batch` undefined-variable repair

**Status:** Implemented and verified.

- Root cause: the consolidation-batch lookup was mistakenly placed in the PPMP request route.
- Moved the lookup into APP creation before it is validated or assigned.
- Added safe integer validation for `consolidation_batch_id`.
- Added a regression test confirming a missing batch produces HTTP 400 rather than `NameError`.

## 2026-08-25/26 — Startup DDL and `KeyboardInterrupt` repair

**Status:** Implemented, migrated, and verified.

- Root cause: normal server startup called `db.create_all()`, mixing schema DDL/inspection with application startup. The supplied traceback ended in `KeyboardInterrupt` during SQLAlchemy `DESCRIBE` checks.
- Normal startup now performs read-only schema verification only.
- `db.create_all()` and migrations run only in explicit migration/reset modes.
- Added missing-table and missing-column diagnostics with an actionable migration command.
- Added typed MariaDB connection/read/write timeouts.
- Added missing `consolidation_batches.app_cycle` and `workflow_audit_log.ip_address` migration coverage.
- Added post-migration schema verification.
- Added a regression test asserting normal startup never calls `db.create_all()`.
- Created a recoverable MariaDB backup before the live additive migration.
- Successfully applied the live migration without resetting data.

**Backup:** `backups/ppmp_db_before_startup_fix_20260825.sql`  
**Live startup verification:** approximately 1.1 seconds  
**HTTP smoke test:** login page HTTP 200; unauthenticated protected API HTTP 401  
**Automated suite at this revision:** 6 tests passed.

---

# 3. Database revision inventory

## Current mapped tables

1. `annual_procurement_plans`
2. `app_approvals`
3. `colleges`
4. `consolidation_batches`
5. `consolidation_sources`
6. `ppmp_audit_log`
7. `ppmp_comments`
8. `ppmp_consolidation_log`
9. `ppmp_items`
10. `ppmp_notifications`
11. `ppmp_submission_requests`
12. `survey_recipients`
13. `surveys`
14. `users`
15. `wishlist_items`
16. `wishlist_requests`
17. `workflow_audit_log`

## Significant constraints and fields

- Unique user username.
- Unique user email.
- Unique current user role.
- Account lifecycle check constraint.
- Unique APP per office/fiscal year/type.
- Unique consolidation fiscal year/APP cycle.
- Unique PPMP consolidation source to prevent duplicate consolidation.
- Unique survey/college recipient.
- APP-to-consolidation-batch reference.
- Audit actor, action, details, timestamp, and IP fields.

## Data-protection rules

- No migration may silently delete or reassign historical procurement data.
- Existing accounts with ambiguous roles must be reviewed explicitly.
- Source PPMP rows remain after consolidation and APP generation.
- Run the read-only preflight and create a verified backup before schema migration.
- Use `--migrate-only`; never use `--reset-database` as an upgrade procedure.

---

# 4. Verified test evidence

The current automated tests cover:

- Pending registration reserves a role.
- Duplicate email registration is rejected.
- Database rejects two accounts for one role.
- Office user cannot create PPMP for another college.
- APP creation without a batch returns a controlled validation error.
- Normal application startup never runs schema creation.

Additional checks completed:

- `app.py`, `models.py`, and preflight script compile successfully.
- All mapped tables can be created and verified in a disposable SQLite database.
- Live MariaDB is reachable and schema verification succeeds.
- Live Flask server starts successfully.
- Login page returns HTTP 200.
- Protected unauthenticated API returns HTTP 401.
- Twelve automated regression tests pass.

These checks do not constitute complete acceptance testing for every workflow or role.

---

# 5. New System Quality and Access Revision — 2026-08-26

**Revision status:** Partially implemented and tested. SMTP delivery, CSRF tokens, the legacy-account decision, and broader acceptance testing remain.

## 5.1 Problems found

1. Forgot Password now has visible request/reset views and a working administrator-assisted recovery backend.
2. No verified SMTP/email-delivery configuration exists; administrators currently verify identity and deliver one-time codes offline.
3. No security-question model exists; it remains optional and is not used as a weak substitute for identity verification.
4. Reset-code persistence, hashing, expiry, single-use enforcement, attempt limits, request throttling, and session revocation are implemented.
5. PPMP and APP now have separate permission-resolved dashboards; dual-module users currently enter the PPMP dashboard by default and may select APP Dashboard from navigation.
6. The legacy `COLLEGE_ENCODER`/Franz account remains active with no office or college assignment.
7. Authorization exists on major endpoints, but a complete endpoint-by-endpoint security audit has not yet been recorded.
8. Same-origin checks and SameSite cookies exist, but full CSRF-token coverage is not implemented.
9. General authentication/reset/action rate limiting is not implemented.
10. Automated coverage contains 12 focused tests, not the complete quality-revision matrix.

## 5.2 Root causes

- Earlier revisions prioritized core authentication, PPMP/APP workflows, and safe database migration before introducing outbound email infrastructure.
- Workspace access is currently presented in one dashboard shell with permission-based sections rather than distinct PPMP/APP workspace state.
- The Franz account predates the operational role architecture and lacks enough office/college information for safe automatic reassignment.
- Security controls were added incrementally; no dedicated limiter/CSRF extension or recovery-token service has been integrated.

## 5.3 Recommended fixes

- Replace administrator-assisted delivery with configured institutional SMTP while retaining the implemented random, hashed, expiring, single-use code model.
- Replace the single-process request throttle with a shared production limiter when deploying multiple application workers.
- Add optional hashed security-question answers only as an additional factor, never the primary recovery mechanism.
- Add a server-resolved workspace list based on permissions and a session-bound current workspace.
- Redirect single-module users directly; show a chooser only to dual-module users.
- Enforce the same permissions on every workspace API regardless of selected frontend workspace.
- Archive/deactivate Franz after inspecting foreign-key references; retain historical author/actor links.
- Add CSRF tokens for session-authenticated mutations in addition to existing origin/SameSite checks.
- Expand HTTP-level allow/deny and workflow transition tests.

## 5.4 PPMP/APP login access plan

```text
One Login
  → Authenticate active account
  → Load one operational role
  → Resolve server-side permissions
  → Resolve allowed workspaces
      → PPMP only: PPMP dashboard
      → APP only: APP dashboard
      → Both: secure workspace chooser
```

The selected workspace is UI/session context only. It must never add permissions. Procurement, EO, and Budget retain one account and one role.

## 5.5 Forgot Password flow

```text
Request registered email
  → Return generic response
  → Apply IP/email rate limit
  → Generate random one-time token
  → Store token hash, expiry, attempt count, and unused state
  → Current: administrator verifies identity and privately delivers the one-time code
  → Later: send HTTPS reset link/code through configured institutional mail provider
  → Optional hashed security-question verification
  → Validate token, expiry, account status, and additional factor
  → Validate and confirm new password
  → Replace password hash
  → Mark token used and invalidate other reset tokens/sessions
  → Audit success/failure without secrets
  → Return to login
```

## 5.6 Franz account removal impact

**Current inspected state:**

- User ID: `2`
- Username: `franz`
- Legacy role: `COLLEGE_ENCODER`
- Office: `NULL`
- College: `NULL`
- Active: yes at last preflight

Before archival, inspect references in PPMP creation/approval, comments, wishlist requests, APP approvals, notifications, and audit tables. Do not delete the user row if any history references it. Recommended target:

- `is_active = false`
- `account_status = ARCHIVED`
- current `role = NULL`
- `released_role = COLLEGE_ENCODER`
- historical foreign-key references preserved
- active sessions invalidated by the normal active/status checks

**Status:** Requested; not yet executed because this new revision has only been recorded in this task.

## 5.7 Security risks to address

- Account recovery enumeration and token brute force.
- Reset-email interception or misconfiguration.
- Weak/predictable security-question answers.
- Missing global rate limits.
- Partial CSRF defense.
- Session versioning/revocation is implemented for password resets; retain it when SMTP is added.
- Static code-based permission mapping can drift without permission-matrix tests.
- Legacy accounts without current operational roles.
- Incomplete negative-path/object-access testing.
- Default development administrator password if deployment secrets are not configured.

## 5.8 Expected affected files/modules

- `app.py`: recovery routes/services, limiter, CSRF, workspace resolution, session invalidation, account archival controls.
- `models.py`: reset tokens, optional recovery questions, session/password version, supporting constraints.
- `templates/login.html`: Forgot Password and reset views.
- `templates/index.html`: workspace chooser/switcher and module-specific initialization.
- Database migration code: additive recovery/security fields and tables.
- `requirements.txt`: selected mail/rate-limit/CSRF dependencies if required.
- `tests/`: recovery, authorization, workspace, archival, expiry, replay, rate-limit, and regression tests.
- This master revision record: implementation and evidence updates.

## 5.9 Implementation plan

1. Inventory every route, template action, model, relationship, and current database constraint.
2. Inspect Franz’s historical references and archive safely.
3. Add recovery-token/session-revocation schema through an additive migration.
4. Implement generic-response, rate-limited reset requests and configured email delivery.
5. Implement expiring, hashed, single-use verification and password replacement.
6. Add optional additional verification without storing plaintext answers.
7. Add server-resolved workspaces and permission-safe switching.
8. Audit every sensitive endpoint for authentication, permission, record access, and state validation.
9. Add CSRF and rate-limit coverage without weakening existing authorization.
10. Run full automated and browser regression checks against a backed-up staging database.

## 5.10 Testing plan

- Valid and invalid login.
- Inactive, suspended, archived, and rejected account login denial.
- Generic reset request for existing and unknown emails.
- Email send failure without token disclosure.
- Valid, invalid, expired, replayed, and consumed reset token.
- Optional security-question success/failure and attempt limits.
- Password strength, confirmation, hashing, and old-password rejection.
- Session invalidation after reset.
- PPMP-only, APP-only, and dual-module account resolution.
- Workspace switching and direct API bypass attempts.
- Franz login denial and preserved historical relationships.
- PPMP/Wishlist/consolidation/APP allow and deny transitions.
- Office/college object isolation.
- Duplicate request/double-click and concurrent registration behavior.
- PDF/Excel authorization and duplicate-free totals.
- Notification and audit accuracy.
- CSRF, XSS, SQL injection, session expiry, and logout behavior.
- Dashboard loader success, failure, empty state, and 30-second timeout.

---

# 6. Current known limitations and decisions required

1. Assign final operational roles for each college/institute/school account and define how those values relate to `colleges` rows.
2. Confirm exact APP-CSE reviewer sequence if it differs from the current APP sequence.
3. Decide whether rejected wishlist items immediately become available or require explicit reopening.
4. Decide whether wishlist quantities are reserved and whether partial fulfillment is allowed.
5. Select/configure an institutional email provider and sender identity for recovery.
6. Decide whether security questions are institutionally required; email-first recovery is recommended.
7. Choose production WSGI hosting and HTTPS termination; Flask’s development server is not a production server.
8. Replace default development secrets and administrator password before deployment.
9. Archive the legacy Franz account after reference inspection.

---

# 7. Operational commands

Read-only database readiness check:

```powershell
python scripts\db_preflight.py
```

Additive migration after backup/conflict resolution:

```powershell
python app.py --migrate-only
```

Automated tests:

```powershell
python -m unittest discover -s tests -v
```

Development startup:

```powershell
python app.py
```

Never use `--reset-database` on an existing or production database.

---

# 8. Record maintenance policy

For every future revision, add:

1. Date and revision title.
2. User objective/acceptance criteria.
3. Problems and root causes found through inspection.
4. Exact files, routes, models, tables, and templates changed.
5. Database migration and rollback/backup details.
6. Security and authorization impact.
7. Tests executed and their results.
8. Data changes, including account lifecycle changes.
9. Known limitations, risks, and required decisions.
10. Status: Requested, Partial, Implemented, Verified, Blocked, or Superseded.

Never record a feature as verified merely because code exists; include the verification evidence.

---

# 9. 2026-09-06 — Registration Approval and Real 12-Column APP Major Revision

## 9.1 Request and source references

The revision implemented the supplied Registration + Account Approval + Role Flow document and the APP Digital Table document. The four supplied APP photographs were used only to reproduce the official column order, grouped headings, section rows, totals, and approval identity concepts. Their project names and monetary values were not imported.

## 9.2 Current implementation analysis and decision

- The old Registration form called its single role selector `Available role`; backend/database role uniqueness was valid, but the UX, confirmation, post-registration status, and pending-login explanation were incomplete.
- The old Admin APP component was the only UI caller for `/api/apps`. It created a real `annual_procurement_plans` row linked to `consolidation_batches`, prevented duplicate office/year/type plans, and used `app_approvals` for review state.
- It was **PARTIALLY IMPLEMENTED**: no `app_sections`, `app_items`, or `app_comments`; no real 12-column APP table; no APP-specific PDF/Excel; no source-row materialization; and the Administrator wildcard could perform an operational Procurement task.
- Safe result: **MOVED AND REDESIGNED**. Procurement exclusively creates APP drafts from consolidation. Admin retains same-record visibility, final approval, and finalization. The PPMP → Consolidation → APP dependency remains intact.

## 9.3 Registration and approval changes

- Registration now has Office plus one `Role` selector, password confirmation, and password visibility controls.
- Office remains because it drives PPMP data isolation, organizational ownership, implementing-unit identity, and reporting.
- The backend validates password confirmation, role/office values, duplicates, role availability, and reserves the role through the existing unique database index.
- Successful registration creates only a PENDING inactive account, returns a signed time-limited registration-status reference, shows a success popup, and returns to Login with a Pending Approval notice.
- Correct credentials for Pending, Rejected, Suspended, Archived, or inactive users produce appropriate blocked-status feedback without creating a session. Unknown users/wrong passwords remain generic.
- `/api/auth/registration-status` uses the signed reference, minimal output, expiry, fingerprint verification, and rate limiting. It exposes no account list, password material, or private database ID.
- Admin pending-account cards now show full name, email, username, office, role, registration date, and status, with View, Approve, and Reject.
- Approval reuses `ppmp_notifications`; no approval SMS/email system was added.
- Dual PPMP/APP roles receive a workspace chooser after login.

## 9.4 APP implementation

- Added relational `APPSection`, `APPItem`, and `APPComment` models/tables while reusing `AnnualProcurementPlan`, `ConsolidationBatch`, `ConsolidationSource`, `APPApproval`, `PPMPItem`, and existing controlled PPMP values.
- APP Item stores all 12 required columns. Monetary values use `DECIMAL(18,2)` and Yes/No uses a normalized Boolean.
- APP draft creation filters the selected batch to legitimate approved PPMP sources for the chosen office and same fiscal year, then stores source IDs and truthfully mapped values. Unmapped APP-only fields stay blank until completed.
- Added multiple items, separate section headers, Draft/Returned editing, submission completeness validation, start/end validation, append-only comments, item-specific notes, history, automatic section/mode/EPA/CSE/Capital Outlay/overall totals, and same-record Admin visibility.
- Workflow remains Procurement → BAC Chairman → EO → Budget → Administrator → Finalized. Return/reject reasons are retained in both history and comments.
- Added APP-specific 12-column landscape PDF and grouped-header Excel output with preparation/recommendation/approval identities from authenticated actions.
- Admin cannot call APP draft creation even through its wildcard permission. Every item/section/comment/transition API validates authentication, permissions, plan ownership, workflow state, and child membership.

## 9.5 Database migration and data protection

- Backup: `backups/ppmp_db_before_app_registration_revision_20260906.sql` (44,546 bytes).
- Command: `python app.py --migrate-only`.
- Result: successful additive migration; no reset.
- Pre/post live counts: users 4, colleges 1, PPMP items 0, PPMP records 0, PPMP record items 0, PPMP orders 1, PPMP order items 1, consolidation batches 0, consolidation sources 0, APP records 0, APP approvals 0.
- New APP tables began empty: APP sections 0, APP items 0, APP comments 0.
- `verify_database_schema()` passed after migration.

## 9.6 Affected files

- `ppmp/models.py`
- `ppmp/app.py`
- `ppmp/templates/login.html`
- `ppmp/templates/index.html`
- `ppmp/app.py`
- `ppmp/tests/test_revision.py`
- `ppmp/tests/check_template_scripts.js`
- `ppmp/scripts/generate_documentation.py`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.pdf`
- `SYSTEM_REVISION_RECORD.md`

## 9.7 Verification evidence

- `python -m py_compile app.py models.py`: passed.
- `python -m unittest discover -s tests -v`: 22 tests passed.
- `node tests\check_template_scripts.js`: dashboard and Login inline scripts parsed successfully.
- APP regression covers source materialization, sections, multiple rows, every workflow actor, totals, edit lock after submit, Admin creation denial, comments, PDF, Excel, and source preservation.
- Registration regression covers exact form labels, confirmation, signed Pending/Active checks, pending login denial, Admin details/approval, system notification, and approved login.
- MariaDB migration and post-migration schema validation: passed.
- Live Playwright verification passed at 1440x1000 and 390x844: Registration labels and controls rendered correctly; the Admin APP creation card was hidden; direct Admin APP creation returned HTTP 403; all 12 APP columns and grouped headers rendered; the 2,600-pixel table scrolled inside its 1,398-pixel wrapper; the mobile document stayed within the viewport; and no page errors or failed requests occurred.

## 9.8 Documentation policy

The living source and generated PDF are now:

- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.pdf`

They contain current architecture, registration/user guidance, APP dependency analysis, the exact 12-column map, database/security impact, user and university benefits, manual-vs-digital comparison, feature-benefit matrix, UX study, verification, and revision history. Run `python scripts\generate_documentation.py` from `ppmp` after every verified future revision.

**Status: IMPLEMENTED AND VERIFIED; automated regression, template parsing, MariaDB schema/data-integrity, and live desktop/mobile browser verification passed.**

---

# 10. 2026-09-06 - Fresh Account Baseline and Complete Documentation PDF

## 10.1 Request

- Remove all accounts except the permanent Administrator so new users begin from registration and approval.
- Preserve real procurement records and database integrity.
- Confirm that Procurement and other authorized APP reviewers see the real shared APP records, consolidation sources, twelve columns, totals, comments, workflow, and exports.
- Complete the documentation PDF so every implemented feature explains what it does and how it works.
- Require the living documentation and PDF to be updated for every later revision.

## 10.2 Account and foreign-key inspection

- Pre-cleanup accounts: Admin (Active), one office account (Active), one archived account, and one rejected account.
- MariaDB exposed exactly one `ADMIN` row. Cleanup was cancelled automatically unless exactly one active Admin existed.
- Account-owned `password_reset_requests` and `ppmp_notifications` use `ON DELETE CASCADE`.
- Procurement author/reviewer/approver fields use `ON DELETE SET NULL`; deleting an account therefore preserves PPMP, Wishlist, Consolidation, APP, comment, survey, and audit rows.
- No Office, PPMP, Wishlist, Consolidation, APP, Survey, or business reference table was included in the deletion target.

## 10.3 Backup and cleanup

- Backup created before deletion: `backups/ppmp_db_before_fresh_account_reset_20260906.sql` (51,536 bytes).
- MariaDB 12.2 dump used a single transaction, triggers, routines, events, and UTF-8 encoding. Local TLS negotiation was explicitly skipped after the first dump attempt reported a Windows credential error; the successful dump completed with exit code 0.
- Three non-Administrator accounts were deleted in one committed ORM transaction.
- A permanent `ACCOUNT_FRESH_START_RESET` audit event records the Admin actor, removed count, time, and business-data preservation result without recording passwords or hashes.
- Final account state: exactly one `ADMIN`, status `ACTIVE`, `is_active=true`.
- Deleted accounts cannot reuse existing browser sessions because session lookup no longer resolves those user IDs.

## 10.4 Data-integrity result

Business-table counts were compared in the cleanup transaction and were identical before and after:

- Colleges 1
- PPMP Items 0; PPMP Records 0; PPMP Record Items 0; PPMP Comments 0
- Master Wishlist Items 1; Wishlist Requests 1; PPMP Orders 1; PPMP Order Items 1
- Consolidation Batches 0; Consolidation Sources 0
- APP headers 0; APP Sections 0; APP Items 0; APP Approvals 0; APP Comments 0
- Surveys 0; Survey Recipients 0

No APP rows were invented to make the dashboard appear populated. When legitimate approved PPMP sources are consolidated by a newly approved Procurement user, the APP dashboard will display those real records through the existing shared APIs.

## 10.5 APP visibility verification

- `app.view` exposes the APP Dashboard and APP Plans navigation for authorized roles.
- Procurement has `ppmp.consolidate`, `app.view`, `app.create`, `app.edit`, and `app.submit` and therefore sees Consolidation, APP Dashboard, APP Records, all twelve columns, and draft controls.
- BAC Chairman, EO/AA, Budget, and Admin use `app.view` to inspect the same `annual_procurement_plans`, `app_sections`, `app_items`, comments, approval history, source links, and totals.
- Admin remains prohibited from operational APP creation even though Admin has global inspection authority.
- The regression suite now explicitly verifies that the Procurement creator retrieves the created APP through `/api/apps`, `/api/dashboard/app`, `/api/apps/metadata`, and the detail/export workflow.

## 10.6 Complete living manual

`SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` now documents how all current features work: Login/session control, Registration/status, Forgot Password readiness, Admin approval, role navigation, Admin/PPMP/APP dashboards, EO submission requests, PPMP records/items/workflows, master Wishlist, Wishlist requests/orders, comments, Consolidation, APP creation/sections/twelve columns/validation/totals/workflow/exports, notifications, surveys, reports, schema viewer, audit, errors/loading, role permissions, data separation, end-to-end operation, migration, backup/restore, and the mandatory future documentation process.

The PDF is generated only from that reviewed Markdown source using `ppmp/scripts/generate_documentation.py` and must be regenerated after every future implementation revision.

## 10.7 Affected files and data

- Live MariaDB `users` rows and their cascade-owned notification/reset rows
- `ppmp/tests/test_revision.py`
- `SYSTEM_REVISION_RECORD.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.pdf`
- `ppmp/CHANGELOG.md`

## 10.8 Verification evidence

- Backup command completed successfully and produced a 51,536-byte SQL file.
- Transactional cleanup invariant: one active Admin remains.
- Transactional business-count invariant: passed for all listed business tables.
- Python compilation passed for application, models, regression test, and PDF generator.
- Full automated regression suite: 22 tests passed, including strengthened Procurement APP list/dashboard/metadata visibility checks.
- Template JavaScript parsing passed for both dashboard scripts and Login.
- Live MariaDB schema verification passed; current accounts contain exactly one Active Admin; APP and Consolidation tables remain truthfully empty until real sources exist.
- Post-reset Playwright verification passed at 1440x1000 and 390x844 with no page errors or failed requests; the APP table retained twelve columns and contained horizontal scrolling; direct Admin APP creation remained HTTP 403.
- Generated PDF validation passed: 44,119 bytes, 12 pages, newer than its Markdown source, correct title metadata, extractable text, and all required complete-manual/revision markers present.

**Status: IMPLEMENTED AND VERIFIED; the account baseline, procurement-data preservation, authorized APP visibility, complete living manual, generated PDF, schema, regression, JavaScript, and desktop/mobile browser checks all passed.**

---

# 11. 2026-09-10 - Real FY 2026 APP Source Reconciliation and Import

## 11.1 Request and source authority

The user supplied four APP photographs and later supplied the clear final GAA PDF, the populated mPhilGEPS all-funds workbook, and the APP-CSE workbook. The requested outcome was to confirm and expose all real APP data without inventing values. Instructions printed inside the source forms were treated as document content, not as software-change instructions.

## 11.2 Source decisions

- The final GAA PDF is the authoritative version of the photographed twelve-column APP because it represents the same document and is marked Final.
- The all-funds mPhilGEPS workbook is a distinct 105-row source and is stored as `APP_NON_CSE`; it is not merged into or allowed to overwrite the final GAA APP.
- The APP-CSE workbook is a blank official template: all 318 catalog rows have zero monthly quantities, totals are zero, and agency/signature fields are blank. No APP-CSE requirements were created.
- Printed names and signatures were not converted into authenticated users or system approval events.
- No PPMP item, consolidation batch, or consolidation source was fabricated for externally supplied source documents.

## 11.3 Corrected final GAA APP

MariaDB APP `id=1` contains 40 rows in four sections and is Finalized because the PDF is marked Final. The clear PDF corrected Internet Subscription from PHP 287,000.00 to PHP 297,000.00 and School Buildings repair from PHP 360,000.00 to PHP 380,000.00. It also confirmed `Expenses` in two Furniture/Fixtures/Books titles. The resulting row total equals the printed PHP 93,459,200.00 total exactly.

The PDF's printed EPA total is PHP 92,959,200.00, but only Janitorial Services and Security Services are marked `Yes`, totaling PHP 2,978,000.00. The system preserves both the row-level values and the printed source metadata instead of changing either.

## 11.4 Imported APP Non-CSE all-funds record

MariaDB APP `id=2`, type `APP_NON_CSE`, status `Imported`, contains:

- GAA FUND: 41 rows, PHP 93,409,200.00
- FUND 164: 43 rows, PHP 84,147,871.30
- FUND 161: 21 rows, PHP 8,462,750.00
- Overall: 105 rows, PHP 186,019,821.30

The source workbook has no General Description, Early Procurement Activity, Bid Evaluation Criteria, or Procurement Strategy/Tools columns. Those APP fields are NULL. The interactive APP API continues to require the normal complete controlled values before a workflow submission; only explicit read-only reference imports may retain source-format blanks.

## 11.5 Database and UI behavior

- Added `source_type` and JSON `source_details` provenance to APP headers.
- Relaxed the APP consolidation link only for explicit external-source imports; normal Procurement creation still requires a legitimate, non-empty same-year consolidation batch.
- Added the read-only `APP_NON_CSE` type and `Imported` status.
- Relaxed `app_items.general_description` storage to nullable for official source formats that do not contain that field; normal entry/submission validation remains mandatory.
- The APP list/dashboard displays both real source records. Details identify the source document and show source totals/variance without displaying a fake batch number.
- APP PDF and Excel exports reload the same authorized MariaDB rows.

## 11.6 Preservation, backup, and audit

- Initial pre-import backup: `backups/ppmp_db_before_app_image_import_20260909_141350.sql` (50,193 bytes).
- Clear-source reconciliation backup: `backups/ppmp_db_before_clear_app_source_reconciliation_20260910_085839.sql` (63,626 bytes).
- The additive/constraint-relaxing migration completed without reset.
- Users, Offices, PPMP, Wishlist, Consolidation, approvals, and permissions were not deleted, reassigned, or fabricated.
- `REFERENCE_IMAGES_IMPORTED`, `CLEAR_SOURCE_RECONCILED`, and `CLEAR_SOURCE_IMPORTED` events preserve the import history and corrections.
- Controlled source copies live under `ppmp/reference_data/app_2026/`.
- Full row-level and conflict evidence is recorded in `APP_SOURCE_DATA_AUDIT_2026.md`.

## 11.7 Affected files and modules

- `ppmp/models.py`
- `ppmp/app.py`
- `ppmp/templates/index.html`
- `ppmp/scripts/import_app_reference_images.py`
- `ppmp/scripts/import_app_clear_source_files.py`
- `ppmp/scripts/db_preflight.py`
- `ppmp/tests/test_revision.py`
- `ppmp/reference_data/app_2026/*`
- `APP_SOURCE_DATA_AUDIT_2026.md`
- `SYSTEM_REVISION_RECORD.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` and generated PDF
- `ppmp/CHANGELOG.md`
- MariaDB `annual_procurement_plans`, `app_sections`, `app_items`, and `workflow_audit_log`

## 11.8 Verification evidence

- Source checks: final GAA 40 rows/PHP 93,459,200.00; all-funds 105 rows/PHP 186,019,821.30; CSE 318 catalog rows/zero active requirements.
- Python compilation passed for the application, models, and both import scripts.
- Full automated regression suite: 24 tests passed.
- Live MariaDB: two APP headers, seven sections, 145 items, zero false PPMP/consolidation links, and zero fabricated APP approvals.
- Administrator APP list/dashboard/detail endpoints returned HTTP 200 and the two correct records/totals.
- PDF and Excel export endpoints for both APP records returned HTTP 200 with valid PDF/ZIP signatures.
- Existing live users and offices remained unchanged during reconciliation.
- The regenerated living documentation PDF is 13 pages, is newer than its Markdown source, has extractable text/correct metadata, and contains the current real-source revision markers.

**Status: IMPLEMENTED AND VERIFIED; both populated source sets are separately traceable, the blank CSE template was not misrepresented, totals reconcile to their authoritative files, and no fake workflow or source data was created.**

# 12. 2026-09-10 - InfinityLoop Authentication Transitions

## 12.1 Request

Replace the Login and Logout loading animation with the requested InfinityLoop design and keep the loading transition visible for a strict 30-second duration during successful sign-in and sign-out.

## 12.2 Root cause and implementation decision

The supplied `import { InfinityLoop } from "@/components/loading-ui/infinity";` statement targets a React/Vite component pipeline. This system renders Flask/Jinja templates and has no `@/` JavaScript alias or React component runtime, so inserting that import would cause a browser/module-resolution failure. The same InfinityLoop visual was implemented as dependency-free inline SVG, CSS, and JavaScript in the existing templates, preserving the current architecture and UI routes.

## 12.3 Timing and error behavior

- `AUTH_LOADING_DURATION_MS` is explicitly set to `30_000` on Login and Dashboard pages.
- A monotonic `performance.now()` timer measures the transition from the user's successful Login/Logout action and waits for any remaining time before navigation.
- A visible seconds-remaining message makes the 30-second hold clear to the user.
- Failed credentials, blocked accounts, network errors, and failed logout requests are not artificially delayed; the overlay closes and the existing error UI is restored immediately.
- Logout clears the server session first, disconnects the live socket, then completes the remaining visual hold before returning to Login.
- The Logout request bypasses the ordinary request-loader counter so it cannot hide the timed overlay early.

## 12.4 Data, security, and permission impact

No database table, migration, account, permission, session policy, procurement record, or real APP/PPMP data was changed. Server-side authentication, account-state checks, CSRF/same-origin behavior, session clearing, and role authorization remain unchanged. The revision changes only authentication transition presentation and client-side navigation timing.

## 12.5 Affected files

- `ppmp/templates/login.html`
- `ppmp/templates/index.html`
- `ppmp/tests/test_revision.py`
- `SYSTEM_REVISION_RECORD.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` and generated PDF
- `ppmp/CHANGELOG.md`

## 12.6 Verification evidence

- Python compilation passed for `app.py`, `models.py`, and `tests/test_revision.py`.
- Both Login and Dashboard inline JavaScript programs parsed successfully with Node.js.
- All 24 automated regression tests passed, including new checks for the InfinityLoop markup, explicit 30-second constants, successful Login/Logout wait ordering, immediate error cancellation, and protected logout overlay behavior.
- No database migration or data-writing verification step was required because this is a template-only behavior revision.
- The living documentation PDF was regenerated atomically and validated as a current 14-page document with extractable InfinityLoop/30-second revision markers and correct metadata.

## 12.7 Live-delivery correction

The first source revision was not visible because two older Python processes were still listening on port 5000 and serving a cached copy of `login.html`. Direct HTTP inspection proved that the running response still contained the old `.container`, `.track`, and `.car` loader even though the edited template contained InfinityLoop.

- Added automatic Jinja template reloading.
- Added `no-store`, `no-cache`, and immediate-expiration headers to HTML responses so Login and authenticated Dashboard HTML cannot remain stale in the browser cache.
- Added a visible `infinity-auth-v2-20260910` UI revision marker to both templates.
- Stopped only the two verified stale Python listeners on port 5000 and started one refreshed PPMP server from the correct `ppmp` directory. No database reset or migration was run.
- The refreshed live response returned HTTP 200, the new revision marker, InfinityLoop markup, countdown, and `30_000` duration; the old animation was absent.
- A real Chromium test confirmed `animationName=infinityTravel`, `aria-busy=true`, a visible `30s remaining` message, zero browser errors, and a measured successful Login transition of 30,486 ms. The Login API response was intercepted for this visual/timing test, so no account or database row was created or modified.

**Status: IMPLEMENTED AND VERIFIED; successful Login and Logout transitions retain the InfinityLoop overlay for a measured minimum of 30 seconds, while errors remain immediate and existing data and authorization are untouched.**

# 13. 2026-09-11 - PPMP Dashboard, APP Consolidation Routing, and Supply Office Source Data

## 13.1 Request and root cause

The PPMP Dashboard needed a searchable list of real items, direct pending-order selection, an unlisted-item path, APP-user consolidation before Administrator approval, requester approval notifications, restored Administrator item management, and the supplied PPMP image rows. The authentication timer also needed to be hidden without shortening the 30-second Login/Logout transition.

Inspection found that the master item/add-item implementation was still present but unreachable: no sidebar item pointed to `panel-ppmp-wishlist`. The Jinja and JavaScript navigation also explicitly hid the PPMP and APP Dashboard entries from Administrator sessions. New master/custom orders bypassed Procurement because they were created directly in `Pending Admin Approval`.

## 13.2 Implemented UI and workflow

- Restored distinct PPMP and APP Dashboard navigation for Administrator oversight.
- Added the reachable `PPMP Items & Orders` navigation entry. Administrator sessions can again open `Add Master Wishlist Item`.
- Added a searchable Available-items table directly to the PPMP Dashboard. Search covers description, category, unit, and source office.
- Office users can add a selected master item and quantity directly to the current client-side pending order, open the unlisted-item form, review all pending lines, and submit.
- Unlisted/custom items remain children of that order only and do not pollute the master catalog.
- New/resubmitted orders now follow `Submitted -> APP / Procurement Consolidation -> Pending Admin Approval -> Approved/Returned/Rejected`.
- Procurement-role users receive these Submitted orders in the APP Dashboard's consolidation queue and perform the APP/consolidation decision there. Administrator review follows in PPMP Requests. Approval retains the existing in-system requester notification and audit/materialization behavior.
- Legacy `EO Review` and `Procurement Review` orders remain processable; existing statuses were not rewritten.
- The InfinityLoop and measured `30_000` millisecond successful authentication hold remain, but all seconds-remaining nodes/text were removed.

## 13.3 Real PPMP source import and data protection

- Copied the two supplied Supply Office PPMP images into `ppmp/reference_data/ppmp_2026/` and locked validation to their SHA-256 hashes.
- Created `scripts/import_ppmp_wishlist_images.py` with `--check-only` and conflict-blocking, idempotent `--apply` modes.
- Created the 95,758-byte MariaDB backup `ppmp/backups/pre_ppmp_wishlist_import_20260910_234816.sql` before import.
- Imported 29 clearly quantified rows as Available master Wishlist items with page/row provenance, source schedule, fund, mode, supporting documents, printed row budget, and derived unit-cost explanation.
- Preserved the prior master item, users, offices, two APP records/145 APP rows, PPMP document, and existing order.
- Did not fabricate the blank quantity/unit for `Repair and Maintenance / Emergency` (PHP 23,000.00). The source row remains documented in `PPMP_SOURCE_DATA_AUDIT_2026.md`.
- Preserved the PHP 1,100.00 difference between the readable row-budget sum (PHP 248,778.00) and the form's printed total (PHP 249,878.00).

## 13.4 Affected files/modules

- `ppmp/app.py`
- `ppmp/models.py`
- `ppmp/templates/index.html`
- `ppmp/templates/login.html`
- `ppmp/tests/test_revision.py`
- `ppmp/scripts/import_ppmp_wishlist_images.py`
- `ppmp/reference_data/ppmp_2026/*`
- `PPMP_SOURCE_DATA_AUDIT_2026.md`
- `SYSTEM_REVISION_RECORD.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` and generated PDF
- `ppmp/CHANGELOG.md`
- MariaDB `wishlist_items` and `workflow_audit_log`

## 13.5 Verification

- Python compilation passed for application, models, and importer.
- Import `--check-only` passed; first apply added 29 rows; second apply made no changes.
- Full automated suite: 25 tests passed, including the new direct Procurement order sequence, requester notification, import totals, hash validation, and idempotence.
- Live MariaDB contains 30 master Wishlist rows (29 source-image rows plus the preserved existing row), two APP records, one PPMP document, and one pre-existing order.
- Desktop Chromium verified the Login InfinityLoop with no timer node/text; Administrator PPMP/APP/item navigation; 29 Available dashboard rows; search; reachable Add Master form; two real APP dashboard records; and zero browser errors.
- PPMP-user Chromium verified 29 visible rows, Add to Pending Order, pending count update, reachable unlisted-item form/current order, and zero browser errors without submitting test data.

## 13.6 Remaining source risk

One source row cannot safely become orderable until an authoritative quantity and unit are supplied. The images' PHP 1,100.00 arithmetic variance also remains unresolved. These are source-document limitations, not hidden system values; neither was guessed.

**Status: IMPLEMENTED AND VERIFIED WITH DOCUMENTED SOURCE LIMITATIONS.**

# 14. Admin Master Wishlist Management and 15-Second Authentication

## 14.1 Request and root cause

The requested revision reduces the successful Login/Logout loading transition to 15 seconds, moves Master Wishlist creation to the Admin Dashboard, adds Administrator-only Edit/Delete actions inside Master Wishlist, and replaces the browser-native Administrator-comment prompt.

Inspection confirmed that two different concepts were both presented as “Wishlist”: the reusable `wishlist_items` catalog and the twelve-column `PPMPRecordItem` planning document. The catalog add form was in the PPMP Wishlist workspace, while the office planning-row form was labelled “Add Wishlist Item.” That naming and placement made the office PPMP editor appear to be an Administrator catalog tool. The API already restricted catalog creation, update, and deletion to Administrator sessions, but the UI lacked edit/delete actions and safe linked-record feedback.

## 14.2 Implemented interface and flow

- Changed the successful Login and Logout InfinityLoop duration from `30_000` to `15_000` milliseconds in both templates.
- Kept the countdown hidden. Authentication or Logout failures remain immediate and cancel the timed transition.
- Moved **Add Item to Master Wishlist** into the server-rendered Administrator Dashboard. Non-Administrator sessions do not receive this form in the HTML.
- Removed Administrator catalog-creation controls from the PPMP Dashboard. The dashboard still provides the searchable catalog because office users need it to build their pending orders.
- Renamed the twelve-column office form and its save/edit states to **PPMP Planning Row**. Its fields and PPMP document behavior were preserved.
- Added Edit and Delete action buttons for manageable Master Wishlist entries only when the current user is the Administrator.
- Office users receive no Edit/Delete controls and retain only **Add to Order** for Available entries.
- Replaced the browser-native order-comment prompt with an Administrator-only in-system modal. Cancel closes it without creating a comment.

## 14.3 Security and data protection

- `POST`, `PUT`, and `DELETE` Master Wishlist routes retain `@admin_required`; hiding controls is not treated as authorization.
- Delete checks current and legacy order/request references before attempting removal and returns HTTP 409 when history exists.
- Database foreign-key errors are still caught as a second protection layer.
- The comment endpoint remains Administrator-only at the server.
- No schema migration, seed operation, reset, fake data, or live record mutation was required.

## 14.4 Affected files/modules

- `ppmp/templates/login.html`
- `ppmp/templates/index.html`
- `ppmp/app.py`
- `ppmp/tests/test_revision.py`
- `SYSTEM_REVISION_RECORD.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` and generated PDF
- `ppmp/CHANGELOG.md`

## 14.5 Verification

- Full automated suite: 25 tests passed.
- Tests cover the 15-second constants, hidden timer, Admin-only form rendering, office-user API denial, Admin update, linked-delete conflict, PPMP planning labels, and custom comment modal.
- Live Chromium verified InfinityLoop presence, no old 30-second constant, no visible countdown, Administrator add/edit/delete controls, edit population/cancel, the in-system comment modal, office-user Add to Order only, and zero page errors. The Login and Dashboard timing helpers measured 15,002 ms and 15,009 ms.
- Read-only live MariaDB verification found 31 Master Wishlist rows (30 Available and one linked/locked), two APP plans with 145 APP rows, one PPMP record, and two existing Wishlist orders. These records were not changed by this revision.

## 14.6 Remaining risk

Older Return/Reject workflow actions still use browser confirmation/reason prompts. They are separate from the Administrator **Comment** action shown in the supplied screenshot and were not changed to avoid expanding the requested scope. Existing `datetime.utcnow()` deprecation warnings remain technical debt but do not fail the current test suite.

**Status: IMPLEMENTED AND VERIFIED.**

# 15. 2026-09-16 - CSE Master List, PPMP Order Controls, and Authorized Reports

## 15.1 Request and root cause

The revision required exact CSE Master List terminology, removal of catalog stock behavior, controlled PPMP order choices, PPMP-user Reports access, Administrator-published office reports, same-scope PDF/Excel exports, and no unrelated APP changes. Inspection found that the template/model work was partly present while `app.py` still exposed the previous metadata, quantity validation, Administrator-only report route, and old catalog messages. The UI was therefore calling backend behavior that had not persisted.

## 15.2 Implemented behavior

- Replaced active PPMP UI wording with **CSE Master List** and the exact description: **Official Wishlist catalog for PPMP. Only the Administrator can edit or delete these entries.**
- Renamed **Current PPMP Order** to **Current PPMP Items** and the unlisted action to **Add other items not included in the CSE Master list**.
- Removed Available Quantity from catalog forms/tables and removed catalog-capacity rejection. The legacy database quantity is retained for history and compatibility.
- Restricted unlisted-item Category to Goods, Infrastructure, or Consulting Services.
- Restricted PPMP order Source of Funds to GAA/101, SB 164, 161, or 601; restricted Procurement Type to Goods/Services, Infrastructure, or Consulting Services. Procurement Method was not changed.
- Added Reports navigation for PPMP users with Available Reports, Updated Reports from Administrator, Generate Report, Export PDF, and Export Excel.
- Added Administrator create/update controls for an office/fiscal-year report definition. Report rows remain live database queries rather than copied or fake data.
- Applied the same server-side office/role filters to the screen, PDF, and Excel. An office account cannot obtain another office's rows by changing query parameters.
- Preserved Administrator-only catalog create/edit/delete authorization and linked-history deletion protection.
- Made no APP workflow, APP source-data, APP table, or APP permission changes.

## 15.3 Database and data protection

- Created `ppmp_reports` through the existing explicit additive migration path.
- Created and verified `ppmp/backups/pre_cse_reports_revision_20260916_183732.sql` before migration: 129,076 bytes; SHA-256 `8496DD943CA1BFBC50D9F9A854A9C8905B62354A4D11850F4FAA628D1F2026BA`.
- Ran `python app.py --migrate-only` twice successfully, confirming idempotence.
- Counts remained unchanged before/after: 3 users, 2 offices, 31 CSE entries, 1 PPMP record, 7 PPMP orders, 2 APP plans, and 145 APP items.
- `ppmp_reports` starts with zero rows. No demonstration publication or other fake business data was inserted.

## 15.4 Affected files/modules

- `ppmp/app.py`
- `ppmp/models.py`
- `ppmp/templates/index.html`
- `ppmp/tests/test_revision.py`
- `SYSTEM_REVISION_RECORD.md`
- `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` and generated PDF
- `ppmp/CHANGELOG.md`
- MariaDB `ppmp_reports` (additive table only)

## 15.5 Verification

- `python -m py_compile app.py models.py`: passed.
- Full regression suite: 26 tests passed.
- Tests cover exact metadata lists, invalid category/fund/type rejection, Administrator report publication/update, office-scoped listing/generation, cross-office denial, and authorized PDF/Excel output.
- Live APIs returned the exact configured dropdown values. CBAO received 6 own-office report rows and HTTP 403 for an ACCOUNTING report query; Administrator and EO retained their authorized broader views.
- Visible Chromium checks passed for Administrator and CBAO dashboards with zero browser-console errors. They verified catalog controls, removed quantity UI, exact dropdowns, office read-only actions, report publication controls, report generation, and export controls.
- During final validation, the real CBAO account submitted `PPMPR-20260916-DDEEFC4218` with GAA/101 and Goods/Services, increasing the live order count from the verified migration snapshot of 7 to 8. This was normal concurrent user activity, not test data, and it was preserved without modification.

## 15.6 Remaining risk

The existing `datetime.utcnow()` deprecation warnings remain technical debt; they do not fail compilation, the 26 regressions, the live API checks, or the browser verification. Historical revision text may retain the former Master Wishlist name because it describes past UI; the active UI and current operating manual use CSE Master List.

**Status: IMPLEMENTED AND VERIFIED.**

# 16. 2026-09-21 - PPMP Reports User Selected-Request Implementation

## 16.1 Request and root cause

The user Reports flow required a Pending PPMP Request Record row to open only that request's requested items, display Fiscal Year and End-User or Implementing Unit, provide exactly twelve prescribed report columns, allow input only in Columns 4 through 8, and export the same selected request to PDF or Excel. Inspection found that the existing page summarized multiple requests and its exports contained a seven-column request list. It did not provide a selected-request 12-column report.

The required item-level fields already existed in `ppmp_order_items`; no duplicate report-row entity was needed. The exact procurement-method list contains values longer than the existing 120-character `procurement_method` column, so that one column required a safe widening to 255 characters.

## 16.2 Implemented flow

- Pending rows in **Reports -> PPMP Request Records** are keyboard- and mouse-selectable.
- Selecting a row reloads that single authorized request from the server and displays only its requested items.
- The opened report displays the actual Fiscal Year and actual requesting Office before the table.
- The report table contains exactly the prescribed Columns 1 through 12, with no ID, Action, or thirteenth column.
- Columns 1, 2, 3, 9, 10, 11, and 12 use the selected request's stored item/order data.
- Columns 4 through 8 are the only editable report fields. Changes auto-save to the selected `PPMPOrderItem`; no Action column or unrelated editable field was added.
- Column 4 contains exactly the 26 required procurement methods. Column 5 contains only Yes and No. Columns 6, 7, and 8 use month inputs and print as abbreviated month/year values.
- The bottom control is **Export to PDF or Excel** and offers only PDF and Excel.
- Export is blocked until every requested item has complete Columns 4 through 8.

## 16.3 Export and authorization

- PDF uses the existing ISU seal, the exact title **PROJECT PROCUREMENT MANAGEMENT PLAN (PPMP) NO. 1**, actual Fiscal Year, actual End-User or Implementing Unit, and the same selected request's exact twelve-column rows on print-ready landscape A3.
- Excel contains actual Fiscal Year, actual End-User or Implementing Unit, and exactly the same twelve report columns and selected requested items.
- Both formats reload the selected request server-side. Office users cannot open, update, or export another Office's record by changing an identifier.
- Only the requesting PPMP user can update Columns 4 through 8. Existing report/view permissions continue to control read access and `ppmp.export` controls both exports.

## 16.4 Data protection and migration

- Created `ppmp/backups/pre_user_ppmp_reports_20260921_184102.sql` before migration: 137,672 bytes; SHA-256 `6D0B012FF7E76162D4B2F7A2E1DB135508E7262DA0BBDC3E68FD365BACC12781`.
- Widened only `ppmp_order_items.procurement_method` from `VARCHAR(120)` to `VARCHAR(255)`.
- Ran `python app.py --migrate-only` twice successfully, confirming idempotence.
- Counts remained unchanged: 3 users, 2 offices, 31 CSE entries, 1 PPMP record, 9 PPMP orders, 32 PPMP order items, 2 APP plans, 145 APP items, and 0 report-publication rows.
- No fake procurement, request, APP, or report record was created.

## 16.5 Verification

- Python compilation passed.
- Full regression suite: 27 tests passed.
- The new regression verifies two requested items remain isolated from another Office, exact method validation, forbidden-field rejection, incomplete-export blocking, ISU image presence and required PDF text, and a twelve-column-only Excel workbook.
- The stale server on port 5000 was identified because the new detail route returned 404. Only that verified Python process was restarted; the refreshed server returned HTTP 200 and the new route returned the real CBAO request.
- Live read-only checks returned 8 authorized CBAO records and opened request `PPMPR-20260917-C37F4FB93A` with exactly its 6 requested items, Fiscal Year 2026, CBAO office, and 26 procurement-method values.
- Visible Chromium verified row selection, exact twelve headers, six displayed items, enabled Columns 4 through 8, only PDF/Excel choices, and zero browser errors without modifying live request data.

## 16.6 Remaining reference limitation

No separate PPMP sample PDF/image was attached with this revision. The export follows the exact textual layout requirements and uses the existing ISU seal, but pixel-level comparison against an external sample file was not possible.

**Status: IMPLEMENTED AND VERIFIED AGAINST THE PROVIDED TEXTUAL REQUIREMENTS.**

# 17. 2026-09-22 - Non-Blocking Search and Loading Recovery

## 17.1 Root cause

The authenticated dashboard rendered the WebSocket value with an invalid Jinja expression, producing `const WS = ;`. The resulting JavaScript syntax error stopped dashboard initialization before permissions and navigation were populated. The initial loading element was also rendered visible, so a script failure could leave it blocking the system indefinitely.

Both visible CSE Master List search fields also called their server loaders on every keystroke with the global loading overlay enabled. Rapid typing created overlapping requests and kept the overlay visible until the slowest request completed or reached the request timeout.

## 17.2 Fix applied

- Corrected the WebSocket template expression to render valid JSON even when no WebSocket URL is configured.
- Made the application loader start hidden and become visible only through an active operation.
- Added a central reset used after initialization, after each tracked request, when a page is restored from browser history, and as a 31-second defensive failsafe beyond the normal 30-second request timeout.
- Changed the PPMP Dashboard and CSE Master List searches to a 250 ms debounce with `showLoading: false`.
- Added request-version checks so an older search response cannot overwrite newer search results.
- Kept the requested 15-second Login and Logout InfinityLoop transitions unchanged.
- Corrected the selected PPMP report Excel export from unsupported `max_column` to OpenPyXL's `max_col`, discovered during the full regression run.

## 17.3 Data and security impact

No database migration, data insertion, deletion, account change, permission change, or workflow-state change was required. Search continues to use the existing authorized `/api/wishlist` endpoint, and all existing server-side permissions remain active.

## 17.4 Verification

- Dashboard and Login inline JavaScript parsing passed.
- Python compilation passed.
- The focused loader regression passed and verifies valid WebSocket output, hidden initial state, silent search hooks, debounce, request timeout, and failsafe reset.
- The focused selected-request Excel export regression passed after the one-word OpenPyXL correction.
- Visible Chromium verified both CSE searches with deliberately delayed responses: the global loader remained hidden, results rendered, the defensive reset worked, and no browser error was recorded.
- Full regression suite: 27 tests passed.

**Status: IMPLEMENTED AND VERIFIED.**

## 2026-09-25 - Startup connection diagnostics

- Confirmed MariaDB Windows service is stopped, with automatic startup already configured; service query reports exit code 1067. Administrative start attempts were not successful from this session.
- Unified startup connectivity checking with the application's SQLAlchemy engine. DATABASE_URL takes precedence; DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD are used when no URL is supplied, with proper credential escaping.
- Added a five-second connector timeout, visible startup stages, actionable connection errors, and scripts/repair_mariadb_service.ps1 for an Administrator PowerShell.
- Updated connection guidance and removed the README recommendation to reset production data before deployment. No live database migrations, resets, or data writes were performed.
- Verification: four startup regression tests passed. Full suite: 30 of 31 passed; existing test_global_loading_overlay_and_duplicate_action_guards_are_present fails because the login template lacks its expected capTimer expression. Actual app launch prints all expected startup diagnostics and exits cleanly with the database unavailable. Successful live startup remains blocked on the Windows service.

## 2026-09-25 - Resolved MariaDB startup failure

- Root cause confirmed: MariaDB 12.2 data/my.ini contained unrelated prose instead of INI settings. mysqld --print-defaults failed with "Found option without preceding group" at line 1; the Windows service reported error 1067.
- Preserved the invalid file in backups/mariadb-my.ini-before-repair-20260925.txt. Restored minimal server/client settings for the existing C:/Program Files/MariaDB 12.2/data directory and port 3306; configuration parsing passed. Saved the working configuration in backups/mariadb-my.ini-working-20260925.ini.
- Started the existing service with Windows administrator elevation. Verified Running / Automatic and MariaDB's ready-for-connections log.
- Started ppmp/app.py using Python 3.13: database connection and schema verification passed, and Flask started on port 5000. No database reset or migration was performed.

## 2026-10-07 - SQLite default and MariaDB retained for recovery

- Changed the application default SQLAlchemy URL to the project-local `ppmp.sqlite` file. `DATABASE_URL` still explicitly selects a deployment SQLite path or the MariaDB connector, and `DB_BACKEND=mariadb` reuses the retained `DB_*` settings.
- Kept existing MariaDB `DB_*` settings, connector dependency, SQL backups, and recovery instructions. SQLite database files are ignored by Git.
- Updated setup guidance for persistent writable SQLite storage and dialect-specific startup errors.
- No MariaDB-to-SQLite data copy was performed. The existing MariaDB data and backups remain untouched; transferring the current records is a separate required step before treating SQLite as a populated replacement.
- Verification: `python app.py --migrate-only` completed successfully against the new SQLite file and created its schema and initial Administrator. MariaDB was not connected or modified; no automated tests were run.
