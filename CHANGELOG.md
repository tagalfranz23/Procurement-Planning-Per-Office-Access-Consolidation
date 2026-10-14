# PPMP System Revision Record (Legacy)

> This file is retained as a historical source. The authoritative consolidated record is `..\SYSTEM_REVISION_RECORD.md`.

## 2026-10-15 - Department PPMP intake and Academic Affairs review

- Added one annual CSE-based request or No PPMP response for each of CED, CBM, CAS, CCSICT, CCJE, IAT, and PS, using one account per department role.
- Added department-scoped PPMP workspaces and an AA-only Department Wishlist collection. Department submissions route directly to AA.
- Added immutable submitted snapshots and separate AA editable review copies. AA can save Draft, add/edit/remove copied rows, and mark Reviewed without changing the original or CSE catalog.
- The annual collection becomes Ready to Submit after all seven departments respond and all submitted requests have Reviewed copies. A later AA edit resets its copy to Draft; no downstream submission target is introduced.
- Added four department workflow tables. Render PostgreSQL startup creates only these tables if missing through a transaction/advisory-lock bootstrap, then runs normal read-only schema verification; other installations retain `python app.py --migrate-only`. Existing tables/data are not changed by the Render bootstrap. This implementation did not migrate or change local/production data.
- Implemented and locally verified: focused workflow regression, Python compilation, Jinja validation, repeated additive-schema checks, and 32 headless Edge workflow/UI assertions passed with zero uncaught JavaScript errors; layout screenshots were inspected. The regression run executed 35 tests: 32 passed; the same three legacy UI assertion failures were reproduced on pre-revision GitHub baseline `da3e895`. The PDF-dependent test ran after PyPDF2 was installed. Production PostgreSQL deployment and startup bootstrap have not been observed.

## 2026-10-07 - SQLite default with MariaDB retained

- Changed the default SQLAlchemy connection to a project-local SQLite file; `DATABASE_URL` and `DB_BACKEND=mariadb` remain available for MariaDB recovery.
- Preserved MariaDB driver dependencies and existing MariaDB environment values. Added SQLite database files to `.gitignore`.
- Initialized the SQLite schema using `python app.py --migrate-only`; no existing SQLite data was reset. Updated database setup, startup errors, and the schema panel for the active dialect.
- Documented persistent writable storage for deployment.
- MariaDB data has not been copied into SQLite; existing MariaDB databases and backups remain untouched. A separate verified data migration is still needed to carry existing records into SQLite.

## 2026-09-22 - Non-blocking search and loader recovery

- Fixed the malformed WebSocket template expression that rendered `const WS = ;`, stopped dashboard JavaScript initialization, and could leave the application unusable behind its loading state.
- Changed both CSE Master List searches to a 250 ms debounce with no full-screen loading overlay and stale-response protection.
- Made the dashboard loader start hidden, reset after every request, recover from browser back/forward restoration, and use a 31-second defensive failsafe beyond the normal 30-second request timeout.
- Preserved the separate 15-second Login and Logout transition behavior.
- Corrected the selected PPMP report Excel export to use OpenPyXL's supported `max_col` argument after the full regression suite exposed the typo.
- Passed template parsing, Python compilation, all 27 regressions, focused export validation, and visible Chromium search checks with zero browser errors.

## 2026-09-21 - User-selected 12-column PPMP Request Report

- Made Pending rows in Reports -> PPMP Request Records open their own server-scoped requested items.
- Added actual Fiscal Year and End-User or Implementing Unit plus exactly the required twelve PPMP columns.
- Limited report editing to Columns 4 through 8 and only to the requesting office user; exact procurement methods and Yes/No are validated server-side.
- Added the bottom Export to PDF or Excel selector with only those two formats and completeness validation.
- Added an ISU-logo, print-ready A3 PDF and a twelve-column Excel export for the same selected request.
- Safely widened only `ppmp_order_items.procurement_method` to 255 characters after a verified backup; all live counts were preserved.
- Passed compilation, all 27 regressions, live API checks, and visible CBAO Chromium verification with zero browser errors.

## 2026-09-16 - CSE Master List and authorized PPMP reports

- Renamed active Master Wishlist UI to CSE Master List, renamed Current PPMP Items, and applied the exact catalog/unlisted-item wording.
- Removed Available Quantity UI/stock validation while preserving its legacy database field and historical values.
- Restricted custom PPMP categories, order fund sources, and order procurement types in both UI metadata and backend validation; Procurement Method remains unchanged.
- Added PPMP-user Reports access, Administrator office/year report publication updates, and office-scoped on-screen/PDF/Excel output.
- Added the `ppmp_reports` table through an idempotent additive migration after a verified MariaDB backup; no existing count changed and no fake report was inserted.
- Passed Python compilation, all 26 regressions, live role/API checks, and visible Administrator/CBAO Chromium verification with zero console errors.

## 2026-09-11 - Admin Master Wishlist controls and 15-second loading

- Reduced the successful Login and Logout InfinityLoop hold from 30 seconds to 15 seconds while keeping the countdown hidden and failures immediate.
- Moved **Add Item to Master Wishlist** into the Administrator Dashboard and removed catalog-creation controls from the PPMP Dashboard/workspace.
- Added Administrator-only Edit/Delete actions to Master Wishlist; backend authorization remains mandatory and referenced entries return a safe conflict instead of being deleted.
- Renamed the twelve-column office form to **Add PPMP Planning Row** so it is no longer confused with Master Wishlist maintenance.
- Replaced the browser-native Administrator comment prompt with an in-system, Administrator-only modal.
- Passed 25 automated tests and live Chromium checks for both Administrator and office-user permissions without mutating live records.

## 2026-09-10 - PPMP dashboard catalog, APP consolidation flow, and real image data

- Restored Admin access to the separate PPMP and APP dashboards and added a reachable `PPMP Items & Orders` workspace without restoring removed Office Management UI.
- Added the searchable master item list and pending-order actions to the PPMP Dashboard; office users can add master rows, open the unlisted-item form, review the pending order, and submit it.
- Routed every new/resubmitted Wishlist order through the Procurement user's APP Dashboard consolidation queue before Administrator review; legacy EO/Procurement Review orders remain processable.
- Kept custom/unlisted rows inside their specific order and retained requester notifications on Administrator approval.
- Hid the seconds-remaining text while retaining the measured 30-second successful Login/Logout hold and InfinityLoop animation.
- Backed up MariaDB and imported 29 clearly quantified Supply Office PPMP image rows idempotently into the master Wishlist with row-level provenance. The blank-quantity maintenance row and PHP 1,100.00 source-total variance were preserved without fabrication.

## 2026-09-10 - InfinityLoop Login and Logout transitions

- Replaced the former path loader on Login and Dashboard with a dependency-free InfinityLoop SVG/CSS animation compatible with the existing Flask/Jinja frontend.
- Enforced a measured 30-second minimum loading transition after successful Login and Logout, with a visible seconds-remaining indicator.
- Kept invalid credentials, blocked accounts, and failed requests immediate; preserved server authentication, session clearing, permissions, UI routes, and all database data.
- Added regression checks for the loader markup, timing constants, navigation ordering, cancellation behavior, and protected Logout overlay.
- Corrected live delivery after direct HTTP inspection found stale Python listeners serving the old cached template; enabled Jinja reload and no-cache HTML headers, restarted one verified server on port 5000, and confirmed the new animation in Chromium for 30.486 seconds without database changes.

## 2026-09-10 - Real FY 2026 APP source reconciliation

- Reconciled the photographed GAA APP against the clear final PDF, corrected two ambiguous budgets, and verified 40 rows totaling PHP 93,459,200.00.
- Imported the distinct all-funds mPhilGEPS workbook as a read-only `APP_NON_CSE` record with 105 rows totaling PHP 186,019,821.30; unavailable twelve-column fields remain NULL.
- Audited the APP-CSE workbook as an unfilled 318-row, zero-quantity template and did not create fake APP-CSE requirements.
- Added explicit external-source provenance, safe nullable source fields, idempotent validation/import scripts, source-aware database preflight, source copies, audit events, backups, and 24-test regression coverage.
- Recorded the complete evidence and file conflicts in `..\APP_SOURCE_DATA_AUDIT_2026.md` and regenerated the living technical PDF.

## 2026-09-06 - Fresh account baseline and complete living documentation

- Created `backups/ppmp_db_before_fresh_account_reset_20260906.sql` before account deletion.
- Removed all three non-Administrator accounts and retained exactly one active permanent Admin.
- Preserved every PPMP, Wishlist, Consolidation, APP, Survey, Office, comment, and business row; user-linked author fields followed `SET NULL`, while private reset/notification rows followed `CASCADE`.
- Strengthened APP regression coverage so the authorized Procurement creator reads the same real record through APP Records, APP Dashboard, metadata, detail, workflow, and exports.
- Expanded `SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md` into a complete feature operating manual and required its PDF to be regenerated and validated after every future revision.

## 2026-09-06 - Registration approval and real twelve-column APP

- Implemented one-role Registration, confirmation, signed account-status checks, explicit Pending login feedback, complete Admin approval facts, and system-only approval notifications.
- Restricted APP creation to Procurement and retained shared APP visibility for authorized reviewers and Administrator.
- Added relational APP sections, twelve-column items, comments, totals, source traceability, sequential review, and APP-specific PDF/Excel exports.
- Applied the additive MariaDB migration after backup and passed compilation, 22 regressions, JavaScript parsing, schema verification, and desktop/mobile browser checks.

## 2026-08-24 - Revision 111 follow-up: Approval navigation label

- Replaced the oversized Approval text used as a sidebar icon with a compact checkmark, restoring the Account Approval label and count badge alignment.

## 2026-08-24 - Revision 111 follow-up: Admin sidebar visibility

- Rendered the Account Approval sidebar item directly for signed-in administrator sessions instead of waiting for a post-load JavaScript request before revealing it.
- Kept database-backed administrator authorization on all approval APIs unchanged.

## 2026-08-24 - Revision 111: Admin Approval

- Added an administrator-only Account Approval sidebar view for registered, inactive user accounts.
- Added protected APIs to list pending accounts and approve a specific pending account. Each request verifies the current active user is an administrator at the database level.
- Registration now creates a persistent in-app notification for every active administrator. Approving an account creates a notification for that user and activates the existing account record.
- Reused the existing `users.is_active` and `ppmp_notifications` tables; no schema migration, fake data, or unrelated account changes were made.

## 2026-08-24 - Same-origin dashboard authentication repair

- Fixed dashboard API calls that incorrectly used `http://localhost:5000/api` while the application was served at `127.0.0.1:5000`. Browsers treat these as different origins and did not attach the authenticated session cookie.
- Changed dashboard API requests to the same-origin `/api` path and explicitly retained same-origin credentials.
- Allowed CORS `OPTIONS` preflight requests to pass through without granting access to protected API data; authentication remains enforced for all non-OPTIONS protected requests.
- Changed the initial live-update status from `Connecting` to `Offline`, preventing a stale connecting indicator if dashboard initialization fails before the optional notification client starts.

## 2026-08-20 - Dashboard connection and navigation refinement

- Prevented the optional live-notification client from reconnecting indefinitely when its local Node.js service is unavailable; it now fails cleanly after a five-second connection attempt and shows the existing Offline status.
- Set the dashboard sidebar to start collapsed after login. The hamburger button remains the sole control for opening or closing it.
- Renamed the visible dashboard and login product name to `Project Procurement Management Plan`.
- Replaced the login and registration password control with an accessible eye icon and improved the Back control with an animated, keyboard-accessible button.
- Preserved authentication, session handling, permissions, API behavior, and all database records.

## 2026-08-20 - Dashboard logout repair

- Restored the missing `toggleLogout()` client handler used by the dashboard Log out button.
- The handler now displays the existing application loading overlay, posts to the existing session-clearing logout endpoint, closes the live-notification socket, and replaces the dashboard history entry with the login screen.
- If the request fails, the loading overlay is dismissed, the button is re-enabled, and the user receives an error toast. No database records are changed.

## 2026-08-17 - Role-selector login and registration

- Rebuilt the entry screen into three supplied options: `Administrator`, `PPMP Users`, and `APP Users`.
- Selecting an option animates to the matching username/password login form.
- Rebuilt registration for PPMP Users and APP Users; submitted accounts are inactive until an administrator activates them.
- Added account-category validation to prevent users from signing in through the wrong option.

## 2026-08-17 - Collapsible navigation menu

- Added a Menu Toggle button in the top bar.
- The button collapses or expands the desktop sidebar and opens or closes the mobile sidebar.
- Preserved all existing navigation and college filter items inside the sidebar.

## 2026-08-17 - Username login interface

- Added a session-based login screen styled from the supplied Isabela State University reference.
- Added the supplied ISU seal as the login-page visual asset.
- Replaced the User ID label with `Username` and authenticate using the existing unique username field.
- Added secure password-hash verification, show/hide password, optional remembered session, and a post-login loading overlay.
- Protected PPMP API routes from unauthenticated access and added sign-in, sign-out, and current-user endpoints.
- Verified rejected credentials return `401` and the existing `admin` / `admin1234` account signs in successfully.

## 2026-08-17 - MariaDB authentication hardening

- Switched the MariaDB driver to `mysql.connector` and added the `get_db()` connection helper in `app.py`.
- Replaced environment-variable database settings with the direct `mysql.connector.connect(...)` style requested for the application connection.
- Added a startup connection check before schema initialization or administrator creation.
- Detects the unsupported `auth_gssapi_client` authentication plugin and exits with an actionable message instead of a long SQLAlchemy traceback.
- Added `DATABASE_CONNECTION.md` with the compatible, least-privilege MariaDB service-account configuration.
- Preserved the clean-reset command, empty-state dashboard behavior, and the single `admin` account bootstrap.

## 2026-08-17 - Production data reset and MariaDB migration

### Changes

- Replaced the Flask in-memory data store and all automatic PPMP sample records with MariaDB-backed ORM queries.
- Added a MariaDB connection in `app.py`, using `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, and `DB_NAME` environment variables.
- Added the only allowed initial account: username `admin`, password `admin1234`, role `admin`.
- Stored the administrator password as a secure Werkzeug password hash, not as plaintext.
- Added `python app.py --reset-database`, which deletes users, colleges, PPMP items, audits, notifications, and consolidation logs, then recreates only the required administrator account.
- Removed the standalone `schema.sql` file, database-schema navigation, and Node.js schema/bootstrap endpoint.
- Changed dashboard and table empty states to show genuine zero values and “No procurement records available.” when there is no data.
- Removed the Node.js demo-mode database fallback and database schema payload.

### Deployment requirement

Run the reset command once against the intended MariaDB database before starting production. It permanently deletes existing operational records in that configured database.

```powershell
python app.py --reset-database
python app.py
```

### Initial administrator

- Username: `admin`
- Password: `admin1234`

Change this password immediately after the application gains a login/password-management screen.

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
