# SYSTEM TECHNICAL DOCUMENTATION AND RESEARCH REVIEWER

**System:** Web-Based Procurement Management System  
**Institution:** Isabela State University – Cauayan City  
**Current revision date:** 2026-10-15  
**Document version:** 2026.10.15-1  
**Status basis:** Implemented source with verification evidence recorded per revision. The new Department PPMP workflow is locally verified through isolated backend, additive-schema, and Edge browser checks, subject to three confirmed pre-existing legacy UI test failures. Production PostgreSQL deployment has not been observed.  
**Current account baseline:** One permanent active Administrator is preserved; later approved operational accounts may exist and remain role-scoped.  
**Detailed historical record:** `SYSTEM_REVISION_RECORD.md`

SQLite remains the application's local default; MariaDB and PostgreSQL can be selected through deployment configuration. Historical migration and live-data checks below describe their stated dates and do not establish the contents of a later deployment. This is the living operating, technical, database, security, role, workflow, testing, and research reviewer for the current system. It explains what every implemented feature does, who can use it, how records move through the system, and how future revisions must be documented. The Markdown file is the editable source; the PDF is the generated controlled copy.

## 1. Current System Scope

The current system separates procurement planning documents, procurement requests, and annual plans instead of treating them as one record:

```text
PPMP submission request
  -> office PPMP record
  -> PPMP Wishlist rows (12-column PPMP form)
  -> review and approval
  -> approved materialized PPMP items
  -> consolidation batch
  -> APP record
  -> APP sections
  -> APP items (12-column APP form)
  -> BAC Chairman review
  -> EO review
  -> Budget review
  -> Administrator approval
  -> final APP
  -> PDF / Excel
```

Wishlist requests/orders remain separate from PPMP planning records. A submitted Wishlist order is reviewed by the APP/Procurement role for consolidation, then by the Administrator; approved requesters receive an in-system notification. APP and APP (CSE) are also distinct plan types, but use the same controlled APP workflow and table structure.

The Department PPMP workflow added on 2026-10-15 provides a separate annual intake path. The seven designated college departments submit CSE-based requests directly to AA. AA keeps the original submission and edits a separate review copy per department; its Department Wishlist collection shows Ready to Submit after all seven departments have responded and all submitted copies are Reviewed. This readiness state does not perform a downstream PPMP, consolidation, or APP submission.

## 2. Registration, Role, and Approval

### Current registration flow [IMPLEMENTED]

1. The user enters full name, email, username, Office, one Role, password, and password confirmation.
2. Office is retained because it controls organizational ownership, PPMP isolation, implementing-unit identity, and office reporting.
3. The backend validates the office, role, email, username, password, and role/office compatibility.
4. The database's unique `users.role` constraint arbitrates simultaneous attempts to reserve the same role.
5. The account is created as `PENDING` and inactive. It cannot create an authenticated session.
6. The browser receives a signed, time-limited registration-status reference. No password is stored in the browser.
7. The interface shows a Registration Successful popup and returns to Login with a Pending Approval notice.
8. The Administrator reviews Full Name, Email, Username, Office, Role, Registration Date, and Status, then approves, rejects, or views the registration.
9. Approval changes the existing row to `ACTIVE`, creates an in-system notification, and preserves the audit trail.
10. The signed status reference can show `PENDING`, `ACTIVE`, or `REJECTED` without exposing account lists, password data, internal IDs, or role internals.

### One-account/one-role rule [IMPLEMENTED]

`users.role` is singular and unique. Pending, active, and suspended accounts retain the role reservation. Rejected or archived accounts release the active role into `released_role` while preserving the historical user row. This allows role transfer without deleting procurement authorship or approval history.

The designated department roles are CED, CBM, CAS, CCSICT, CCJE, IAT, and PS. Their office and role codes must match, so one account represents each department. Administrator approval links or creates its structural Office row as needed; registration does not bypass approval or create sample procurement data.

### Login behavior [IMPLEMENTED]

- Unknown username or incorrect password returns a generic invalid-credentials response.
- A correct password for a pending account returns a specific Pending Approval response but creates no session.
- Rejected, suspended, archived, and inactive accounts remain blocked.
- Active accounts receive permissions from their one operational role.
- Accounts with both PPMP and APP access receive a workspace chooser; a UI choice never adds permissions.
- A successful Login shows the InfinityLoop transition for a measured minimum of 15 seconds before opening the authorized dashboard. The countdown text is intentionally hidden; authentication failures remain immediate.

### System-only approval notification [IMPLEMENTED]

Approval status is provided by the signed Login-page status checker and the existing `ppmp_notifications` history. No SMS or approval email is sent. Forgot Password remains a separate feature; institutional SMTP delivery is intentionally marked for later configuration.

## 3. APP Component Dependency Analysis

### Why the original Admin APP component existed

The original component was introduced for the previously required approved-PPMP-to-APP lifecycle. Its form selected an office, fiscal year, APP/APP(CSE), and a consolidation batch, then posted to `/api/apps`. The route wrote an `annual_procurement_plans` row linked by `consolidation_batch_id`. `APPApproval` rows recorded later state transitions.

### Pre-revision quality finding

**Assessment: [PARTIALLY IMPLEMENTED].** The record launcher, duplicate prevention, batch linkage, and review sequence were real. However, the APP record had no relational sections or 12-column APP item rows, did not materialize eligible source rows, offered no APP-specific PDF/Excel output, and allowed the Administrator wildcard permission to perform the operational creation action. Removing it would have broken the only bridge from consolidation into APP.

### Safe decision [MOVED AND REDESIGNED]

- Operational `Create APP Draft from Consolidation` is restricted to the authenticated Procurement account.
- Administrator and authorized APP roles still inspect the same APP records and all 12 columns.
- Administrator retains For Admin Approval and Finalize actions.
- No APP record, consolidation source, PPMP record, approval, comment, or report data was deleted.
- The Admin and APP dashboards do not maintain disconnected copies.

### Dependency map

| Component | Current dependency |
| --- | --- |
| `annual_procurement_plans` | One office/fiscal-year/type APP record and its required consolidation batch |
| `consolidation_batches` | Groups approved PPMP sources for an annual APP cycle |
| `consolidation_sources` | Links only approved `ppmp_items` into a batch |
| `app_sections` | Stores printed group headers separately from project rows |
| `app_items` | Stores the real 12 APP columns and an optional legitimate source PPMP link |
| `app_approvals` | Append-only submission/review/approval/finalization identity and notes |
| `app_comments` | Append-only general or item-specific review notes and return reasons |
| `workflow_audit_log` | Records sensitive registration, role, APP, workflow, and export actions |
| `ppmp_notifications` | Stores account approval and workflow notification history |

## 4. Digital APP Table [IMPLEMENTED]

The web table and APP-specific PDF/Excel outputs preserve these grouped headings and exact column order:

| Group | Column | Stored APP field | Input rule |
| --- | ---: | --- | --- |
| Procurement Project Details | 1 | Project Title | Text; required |
| Procurement Project Details | 2 | End-User / Implementing Unit | Office/unit text; required |
| Procurement Project Details | 3 | General Description of Project | Existing project-type controlled list |
| Procurement Project Details | 4 | Mode of Procurement | Controlled dropdown using existing modes plus legitimate reference modes |
| Procurement Project Details | 5 | Early Procurement Activity | Controlled Yes/No mapped to nullable Boolean in Draft |
| Procurement Project Details | 6 | Criteria for Bid Evaluation | Text; required before Submit |
| Projected Timeline (MM/YYYY) | 7 | Start of Procurement Activity | Month; required before Submit |
| Projected Timeline (MM/YYYY) | 8 | End of Procurement Activity | Month; cannot precede Start |
| Funding Details | 9 | Source of Fund | Existing controlled fund-source list |
| Funding Details | 10 | Estimated/Approved Budget | MariaDB `DECIMAL(18,2)`; non-negative; peso display |
| Independent | 11 | Procurement Strategy or Tools | Text |
| Independent | 12 | Remarks | Text |

### Sections and totals [IMPLEMENTED]

Sections such as General Requirements, Miscellaneous Items, Common Use Supplies and Equipment (CSE), and Capital Outlay are relational `app_sections`, not fake procurement projects. Users may add legitimate sections. The application calculates section totals, totals by procurement mode, EPA total, CSE/PS-DBM total, Capital Outlay total, and overall estimated budget from stored Decimal values. No reference-photo amounts are hard-coded.

### Draft materialization [IMPLEMENTED]

When Procurement creates a draft, the server selects only consolidated PPMP items belonging to the chosen office and fiscal year. It copies mapped values and source IDs. APP-only values that cannot be truthfully inferred—especially Early Procurement Activity, bid-evaluation criteria, and procurement strategy—remain empty and must be completed before submission. This avoids fabricated data while retaining traceability.

### APP workflow and record security [IMPLEMENTED]

- Procurement creator: create, add/edit/remove Draft or Returned items, manage sections, comment, submit, export.
- BAC Chairman: review, comment, approve/return/reject, export.
- EO/Academic Affairs: review, comment, approve/return, export according to configured permissions.
- Budget: review, comment, approve/return/reject, export.
- Administrator: inspect all source/history/details, comment, final approval, finalize, export; cannot create the operational draft.
- All mutations re-check authentication, active status, permission, workflow status, plan ownership, and child-record membership on the server.

## 5. Database Integrity and Migration

The 2026-09-06 migration was additive. It created `app_sections`, `app_items`, and `app_comments`; existing APP tables were reused. The migration did not reset or delete live data. A pre-migration backup is stored as:

`backups/ppmp_db_before_app_registration_revision_20260906.sql`

Pre/post verified live row counts remained: users 4, colleges 1, PPMP items 0, PPMP records 0, PPMP record items 0, PPMP orders 1, PPMP order items 1, consolidation batches 0, consolidation sources 0, APP records 0, and APP approvals 0. New APP section/item/comment tables correctly began empty. Reference-image project names and amounts were not inserted.

## 6. Security Controls

Implemented controls include Werkzeug password hashing, database uniqueness for username/email/role, inactive pending accounts, server-side permissions, workflow-state validation, object/child membership checks, same-origin mutation rejection, HttpOnly and SameSite session cookies, session invalidation through `auth_version`, minimal signed registration-status responses, rate limits on public status/recovery checks, Decimal monetary storage, SQLAlchemy parameterization, output escaping in dynamic UI rows, append-only comments/history, and audit logs without passwords.

Deployment must replace the development Flask secret and initial Administrator password, use HTTPS, provide writable persistent storage for the default SQLite database, and run through a production WSGI server. MariaDB remains available through `DB_BACKEND=mariadb` using retained `DB_*` settings, or through `DATABASE_URL`. The single-process in-memory public rate limiter should be replaced by a shared store before multiple workers are deployed.

## 7. How the Procurement Management System Helps Its Users

### PPMP users

The digital PPMP form standardizes planning data, preserves drafts, prevents submission of incomplete controlled fields, shows workflow status, supports comments/return reasons, and retains Wishlist records separately from actual requests. These features reduce ambiguous forms and repeated manual encoding while preserving accountability.

### EO / Academic Affairs

EO can send and monitor office PPMP requests, see submission states, review records, return incomplete work with a retained reason, and participate in APP review. This centralizes follow-up and makes responsibility and timing visible.

AA also receives the seven designated departments' annual PPMP responses in Department Wishlist. It can create a reviewed working copy for each department while preserving the submitted original, and see which response or review still prevents the annual collection from being ready.

### Procurement

Procurement sees approved PPMP material, creates traceable consolidation batches, prepares APP/APP(CSE) in the real 12-column format, calculates totals automatically, submits through controlled review, and exports the same data to PDF/Excel. The source links reduce duplicate encoding without inventing unmapped APP information.

### Budget

Budget can inspect planned amounts, fund sources, APP sections, timelines, and total calculations before its workflow decision. This improves visibility of planned expenditure while leaving final budget/legal determinations to authorized users.

### BAC Chairman

The BAC Chairman receives the same APP data and history, reviews procurement modes and criteria, records a traceable recommendation, and can return/reject with a permanent reason.

### Administrator

The Administrator controls account activation, sees pending registration facts, protects one-account/one-role assignments, inspects audit/notification history, and performs only the configured final APP approval responsibilities. Operational draft preparation remains with Procurement.

### University-wide value

The system centralizes procurement information, enforces consistent formats, separates planning from requesting, improves traceability, preserves history, organizes approvals, reduces avoidable duplicate encoding, supports searchable status visibility, and produces repeatable reports. No unmeasured percentage, time, or cost improvement is claimed.

## 8. Manual Process vs Digital System

| Activity | Manual / paper-based risk | Implemented digital support |
| --- | --- | --- |
| Data entry | Different layouts and repeated encoding | Controlled PPMP/APP fields and source-linked APP drafts |
| Tracking | Physical follow-up and unclear status | Database-backed status and role dashboard |
| Approval | Signatures/reasons may be separated from document | Authenticated action identity, comments, and history |
| Searching | Manual file review | Central records and dashboard lists |
| Reporting | Recalculation/transcription | Calculated totals and PDF/Excel exports |
| Record preservation | Paper loss or fragmented copies | Relational records and non-destructive lifecycle states |
| Accountability | Actor/time can be unclear | User, role, timestamp, source link, and audit records |
| User convenience | Must complete and route paper physically | Draft saving, controlled submission, status feedback, and return comments |

## 9. Feature Benefit Matrix

| Feature | Primary user | Problem addressed | Supported benefit |
| --- | --- | --- | --- |
| PPMP Draft | Office PPMP user | Work may span sessions | Flexible preparation with saved rows |
| PPMP Request | EO | Manual follow-up | Central request/status monitoring |
| PPMP Workflow | Office, EO, Procurement, Admin | Uncontrolled document routing | Validated state transitions and retained reasons |
| Department PPMP collection | Seven designated departments, AA | Scattered annual requests and edits to originals | Department-scoped submission, separate AA copies, and explicit seven-department readiness |
| Wishlist/Order separation | Office, Admin, Procurement | Planning rows mistaken for actual requests | Clear business entities and preserved source links |
| Consolidation | Procurement | Re-encoding approved plans | One-time approved-source selection and traceability |
| APP Digital Table | Procurement and reviewers | Generic/incomplete APP representation | Official 12-column structure, sections, and totals |
| APP Review History | BAC, EO, Budget, Admin | Detached decisions | Authenticated recommendation/approval trail |
| Account Approval | Administrator | Unauthorized self-activation | Controlled access activation |
| Signed Status Check | Registrant | Pending users cannot enter dashboard | Minimal system-only approval notification |
| Notifications | All active roles | Important actions are easy to miss | Persistent in-system history |
| PDF/Excel exports | Authorized reviewers | Manual report transcription | Repeatable reports from the same records |

## 10. User Experience Study

### Implemented UX

- Role-specific navigation and a dual-access workspace chooser.
- Horizontal scrolling for the full 12-column APP instead of hiding required data.
- Grouped APP headers, separate section rows, peso formatting, and visible calculated totals.
- Clear field validation, workflow errors, loading overlay, empty states, comments, and statuses.
- Registration success/pending/approved messages and password visibility controls.
- Responsive layouts while retaining every APP column through horizontal scrolling.

### Recommended future improvements

- Add accessible non-blocking confirmation dialogs in place of browser `confirm`/`prompt`.
- Replace the single-process rate limiter with Redis or another shared deployment service.
- Configure institutional SMTP only for password recovery/email verification, not approval notifications.
- Add measured usability testing with representative ISU roles; no quantitative UX conclusions are currently available.

## 11. Complete Feature Operating Manual

### 11.1 Login and session control

The Login page accepts a username and password. The server verifies the password hash, account status, active flag, and authentication version before creating a session. After a successful response, the dependency-free InfinityLoop overlay remains visible until 15 seconds have elapsed from submission, then opens the authorized dashboard. Logout clears the server session and disconnects the live socket before its own remaining 15-second visual hold completes. The timer remains internal and no seconds-remaining text is displayed. Invalid credentials, blocked accounts, network errors, and failed Logout requests are returned immediately instead of being hidden behind the artificial delay. A suspended, archived, rejected, inactive, or pending account cannot enter a dashboard. Changing a password or an account status increments `auth_version`, which invalidates older sessions.

### 11.2 Registration and account-status checking

Registration collects Full Name, Email, Username, Office, Role, Password, and Confirm Password. The Role dropdown reports availability because only one account may reserve an operational role. Registration never activates the user. It creates a Pending account and returns a signed, expiring reference stored by the browser. The registrant can use Check Account Status to read only Pending, Active, or Rejected state. The reference contains no password and the endpoint does not expose the user directory.

### 11.3 Forgot Password and reset-code readiness

Forgot Password is visible on Login and validates the email format, applies throttling, and returns the same response whether or not an account exists. SMTP delivery is intentionally not configured, so the public request does not create an Administrator recovery queue or send a code. The reset endpoint is ready to accept a hashed, unexpired one-time code after an authorized future SMTP/code-issuance service is configured. Successful reset replaces the password hash, expires other codes, increments `auth_version`, records an audit event, and clears the session.

### 11.4 Administrator account approval

The Accounts and Recovery workspace lists Pending registrations with Full Name, Email, Username, Office, Role, Registration Date, and Status. View displays the same registration facts. Approve changes the existing account to Active and sends an in-system notification. Reject releases the role while retaining the historical row unless a later explicitly authorized cleanup removes it. The Administrator can also suspend or archive accounts; those states block login and release or retain roles according to the lifecycle rules.

### 11.5 Role-based navigation and workspace chooser

The server returns the authenticated user's permission list. The browser uses it to hide unrelated navigation, but every API route repeats authorization on the server. Office accounts see their PPMP workspaces. EO, AA, Procurement, and Budget can receive both PPMP and APP access from one role; these users receive a PPMP/APP workspace chooser. The chooser changes navigation only and cannot grant access.

### 11.6 Admin Dashboard

The Admin Dashboard links to the separate PPMP and APP dashboards, summarizes records requiring attention, and contains the Administrator-only **Add Item to CSE Master List** maintenance form. PPMP and APP measurements remain separated so APP counts and CSE indicators are not mixed into PPMP planning totals. Administrator-only Account Approval, report-publication controls, audit visibility, and final workflow actions remain available through their own panels.

### 11.7 PPMP Dashboard

The PPMP Dashboard summarizes PPMP planning activity, office submissions, approved items eligible for consolidation, Wishlist request states, and recent PPMP work. It directly displays the searchable **CSE Master List** so office users can choose a request quantity, send a catalog row to **Current PPMP Items**, use **Add other items not included in the CSE Master list** when necessary, review the pending lines, and submit. It does not render Administrator catalog-creation controls. Administrator users receive a **Manage in CSE Master List** action while creating new catalog entries from the Admin Dashboard. The PPMP and APP dashboards remain separate and are visible to the Administrator as oversight workspaces.

### 11.8 APP Dashboard

The APP Dashboard is visible to roles with `app.view`, including Procurement, BAC Chairman, EO/AA, Budget, and Administrator. It reads the same `annual_procurement_plans` rows for every authorized reviewer and reports total plans, APP/APP(CSE)/APP Non-CSE types, status counts, pending actions for the current role, source-batch counts, and recent plans. It does not maintain a second Admin copy. Procurement also sees a `PPMP Orders Awaiting APP Consolidation` queue, Consolidation, and the APP draft-creation controls because it alone has both `ppmp.consolidate` and `app.create`. The queue displays only Submitted orders and supplies the approve/consolidate, return, and reject actions. Explicit external-source records show their document provenance instead of a fake consolidation-batch number.

### 11.9 EO/AA PPMP submission requests

EO or AA selects an active Office, fiscal year, optional due date, and notes to request a PPMP submission. The office sees the request and prepares its record. Request statuses track Requested, In Progress, Draft, Submitted, Returned, Approved, or Closed. The request is linked to the PPMP record rather than duplicating its item rows.

### 11.10 PPMP planning document

An authorized office creates one PPMP draft for its office and fiscal year. The record receives a unique reference number. The office can save the draft, add multiple PPMP planning rows, edit or remove Draft rows, read comments, and submit only after validation. Other offices cannot read or mutate it. Reviewers can view the record according to role permissions. The twelve-field editor is labelled **Add PPMP Planning Row** and **Save PPMP Planning Row** so it cannot be mistaken for the Administrator's CSE Master List catalog form.

The PPMP digital table preserves these twelve displayed columns: 1 General Description/Objective; 2 Project Type; 3 Quantity/Size, stored as numeric quantity plus unit/size; 4 Procurement Method; 5 Pre-Procurement Conference; 6 Start; 7 End; 8 Delivery/Implementation; 9 Source of Funds; 10 Estimated Budget; 11 Supporting Documents; and 12 Remarks. Quantity must be positive, estimated budget cannot be negative, controlled selections are validated, and a fiscal-year/office uniqueness rule prevents duplicate records.

### 11.11 PPMP document review and materialization

The official record workflow is Office Draft/Returned to Submitted, EO/AA to Under Review, Procurement to Pending Admin Approval, and Administrator to Approved. Return or Reject requires a reason. On final approval, the system materializes approved planning rows into `ppmp_items` for downstream consolidation while retaining the original `ppmp_records` and `ppmp_record_items`. This source/result separation prevents later consolidation from changing the approved document.

### 11.12 PPMP item-level workflow

The system retains a compatible item-level PPMP API for preserved workflows. Its path is Draft/Returned to Submitted, EO Review, Procurement Review, then Approved by Administrator. Comments and reasons are stored separately. This model is not the same as a PPMP document, CSE Master List item, or Wishlist request.

### 11.13 CSE Master List

The CSE Master List is the official reusable Wishlist catalog for PPMP. Its displayed description is: **Official Wishlist catalog for PPMP. Only the Administrator can edit or delete these entries.** Authorized users search item descriptions, categories, units, and source offices, and office users can select Available rows when creating a Wishlist request. Only the Administrator can create catalog entries from the Admin Dashboard or use Edit and Delete in the CSE Master List panel. These rules are enforced in both rendered controls and protected API routes. Delete returns a conflict response rather than removing an entry referenced by an order or legacy request. Available Quantity is no longer displayed or treated as stock: a user enters the quantity needed for the current request, while the legacy database quantity remains preserved for history and compatibility. Adding a custom/unlisted line sends it only to Current PPMP Items and never creates a catalog entry. For such lines, Category accepts only Goods, Infrastructure, or Consulting Services. The 2026 Supply Office source images contribute 29 imported catalog rows with provenance; one blank-quantity source row remains documented but unimported.

### 11.14 Wishlist requests and orders

An office builds **Current PPMP Items** from approved PPMP/CSE catalog entries and may add a custom line for that request only. The order Source of Funds accepts only GAA/101, SB 164, 161, or 601. Procurement Type accepts only Goods/Services, Infrastructure, or Consulting Services. Procurement Method keeps the existing controlled list. Both browser choices and server-side validation enforce these rules. Submission creates one `ppmp_orders` header and one or more `ppmp_order_items` lines with source references, quantity, unit cost, and totals. Office isolation prevents reading another office's request.

New and resubmitted requests move from Submitted to APP / Procurement Consolidation. A Procurement-role user can approve/consolidate the request to Pending Admin Approval or return/reject it with a reason. The Administrator then approves, returns, or rejects it. Approval notifies the requester and may materialize legitimate PPMP items while preserving the original order and line records. Preserved legacy EO Review and Procurement Review records remain processable so existing history is not rewritten.

### 11.15 Comments, return reasons, and workflow history

PPMP and APP comments are append-only records. They may apply to the whole document or a specific row. The Administrator adds a Wishlist-order comment through the system's accessible modal instead of a browser-native address prompt; the server still repeats the Administrator authorization check. Return/reject notes are copied into the permanent review history so the creator can correct the exact issue. History stores actor, action, date, status movement, and note; it is not overwritten by later resubmission.

### 11.16 Consolidation

Only Procurement has `ppmp.consolidate`. The Consolidation workspace groups approved `ppmp_items` by Office and shows totals by fund source and procurement mode. Procurement selects approved, not-yet-consolidated items for one fiscal year and APP cycle. The server rejects missing items, unapproved items, repeated sources, and a duplicate fiscal-year/cycle batch. `consolidation_sources` permanently connects each selected PPMP item to its batch.

### 11.17 APP and APP(CSE) draft creation

Procurement selects an Office, fiscal year, plan type, and non-empty consolidation batch. The server confirms that the batch contains approved PPMP sources belonging to the selected Office and year and prevents another APP of the same Office/year/type. It then creates the APP header, a structural section, and APP item rows copied only from truthfully mappable PPMP data. Source PPMP IDs remain visible for traceability. APP-only fields remain empty rather than being guessed.

Externally supplied official APP documents follow a separate controlled import path. The source file is validated, copied into `ppmp/reference_data`, identified through `source_type`/`source_details`, imported without PPMP or consolidation links, and locked as Finalized or Imported according to the status actually present in the source. This exception does not weaken normal Procurement creation: the public API still rejects APP creation without a legitimate consolidation batch.

### 11.18 APP sections and twelve-column table

Procurement can add section headers and add, edit, or delete item rows while the plan is Draft or Returned and owned by that Procurement creator. A section cannot be deleted while it contains items. The dashboard, PDF, and Excel use the same stored rows and exact twelve-column order documented in Section 4. All authorized APP reviewers see the same real rows, source links, values, comments, totals, and history. Horizontal scrolling preserves every column on narrow screens instead of hiding data.

The FY 2026 source-data baseline contains two separately traceable records. The Final GAA APP contains 40 complete PDF rows in four sections and totals PHP 93,459,200.00. The mPhilGEPS APP Non-CSE record contains 105 Excel rows in GAA Fund, Fund 164, and Fund 161 sections and totals PHP 186,019,821.30. Its source format omits General Description, Early Procurement Activity, Bid Evaluation Criteria, and Procurement Strategy/Tools, so those cells remain blank. The APP-CSE workbook is a zero-quantity template and therefore creates no procurement rows.

### 11.19 APP validation and calculated totals

Before Submit, every required APP field is validated, Start cannot be later than End, controlled values must be recognized, and Estimated Budget must be a non-negative Decimal. Source-imported records cannot bypass this validator into the live workflow; they are read-only. Totals are calculated from database values: per section, per procurement mode, Early Procurement Activity, CSE/PS-DBM, Capital Outlay, and overall budget. Source-reported totals are retained separately in provenance metadata so contradictions can be disclosed without changing row data.

### 11.20 APP review and finalization

Procurement submits a complete Draft. Review proceeds BAC Chairman, EO, Budget, then Administrator. The expected reviewer is derived from approval history after the latest submission. A reviewer cannot skip another role. Return sends the plan back to Procurement for correction; Reject ends that review path; both require a reason. Administrator approves the For Admin Approval record and can Finalize the Approved record. After submission, items and sections are locked except when properly Returned.

### 11.21 APP PDF and Excel exports

Authorized roles use the APP record's PDF or Excel action. The server reloads the authorized record; the browser does not supply report rows. The PDF is landscape A3 with grouped headers, twelve columns, section rows, totals, and authenticated preparation/recommendation/approval identities. Excel uses grouped headers and the same sections, values, totals, and identities. Exporting never changes plan data.

### 11.22 Notifications

Notifications are database records assigned to a user. Account approval and important PPMP/APP transitions create notifications for the next responsible role or original creator. The dashboard loads the current user's notifications and can mark one as read. Notifications do not replace workflow state; they are alerts pointing to the authoritative record.

### 11.23 Surveys

An authorized survey manager can create a survey, select recipients, and monitor responses. A recipient response is tied to its survey-recipient row and response identity. Surveys are an auxiliary feedback function and do not alter PPMP, Wishlist, Consolidation, or APP approval state.

### 11.24 Reports and analytics

The Reports workspace is available to PPMP users with report permission and contains **Available Reports**, **Updated Reports from Administrator**, and **Generate Report**, plus **Export PDF** and **Export Excel** for roles with export permission. The Administrator can make or update a report definition for one active office and optional fiscal year. Office users can view/review only publications for their own office, and direct generation is restricted to their own PPMP order rows. The server reloads the same authorized rows for on-screen results and exports; changing URL parameters cannot expose another office. PPMP report definitions are metadata only and never copy or fabricate procurement rows. APP reporting remains record-specific through APP export actions and separate from PPMP order reporting.

In **PPMP Request Records**, only a Pending request row opens the item-level user report. The server reloads that one selected request, so its actual Fiscal Year, actual End-User or Implementing Unit, and requested items cannot be mixed with another request. The table has exactly twelve columns: General Description and Objective; Type of Project; Quantity and Size; Recommended Mode of Procurement; Pre-Procurement Conference; Start; End; Expected Delivery or Implementation; Source of Funds; total quantity times unit price; attached supporting documents; and remarks. Only Columns 4 through 8 are editable, and only by the original requesting PPMP user while the request remains pending. The procurement-method selector contains the prescribed 26 methods, Pre-Procurement Conference is Yes/No, and the three schedule values are month fields. All other values come from the stored request and its items.

The bottom **Export to PDF or Excel** control contains only PDF and Excel and stays subject to `ppmp.export`. Export is rejected until Columns 4 through 8 are complete for every item. Both formats reload the same authorized selected request: the landscape A3 PDF uses the ISU seal, the title **PROJECT PROCUREMENT MANAGEMENT PLAN (PPMP) NO. 1**, actual year and office, and exactly twelve columns; Excel carries the same year, office, columns, and rows. No separate visual sample accompanied this revision, so the generated layout was verified against the complete textual specification but could not be pixel-compared with an external reference.

### 11.25 Database Schema viewer

The dashboard's schema panel is a technical reference for entity relationships. It does not execute schema changes from the browser. Actual additive migrations are run explicitly with `python app.py --migrate-only` after backup and preflight checks.

### 11.26 Audit log

`workflow_audit_log` and PPMP audit records capture sensitive actions such as registration, role reservation/release, status changes, PPMP submission/review, consolidation, APP workflow, comments, exports, password-reset events, and controlled maintenance. Passwords, password hashes, and reset codes are not written to audit details. Administrator audit viewing is read-only.

### 11.27 Loading, validation, and error behavior

Mutating buttons are temporarily disabled while requests run to reduce duplicate submissions. A global loading indicator explains long actions. Login and Logout use an InfinityLoop SVG/CSS animation and an explicit `15_000` millisecond minimum measured with `performance.now()`; the timer text is hidden as requested. This native implementation is used because the application is Flask/Jinja rather than React/Vite and therefore cannot resolve `@/components/loading-ui/infinity`. Ordinary operations keep their request-length loader and do not inherit the 15-second hold. The loader starts hidden, closes in each request's `finally` path, resets after initialization and browser-history restoration, and has a 31-second defensive failsafe beyond the normal 30-second request timeout. The PPMP Dashboard and CSE Master List searches are deliberately different: they debounce input for 250 milliseconds, never display the blocking overlay, and ignore stale results from an older query. Jinja template auto-reload and no-store/no-cache HTML response headers prevent an older Login or authenticated Dashboard template from remaining active after a revision and server restart. The optional WebSocket URL is JSON-rendered so an empty configuration remains valid JavaScript and cannot stop initialization. Network calls have error handling and relevant export calls use server-generated files. Empty states show that no records exist; they do not create demonstration rows. Validation errors preserve the current UI and explain what must be corrected.

### 11.28 Department PPMP and AA Department Wishlist [IMPLEMENTED]

The new annual intake covers these seven units:

| Code | Department |
| --- | --- |
| CED | College of Education |
| CBM | College of Business and Management |
| CAS | College of Arts and Sciences |
| CCSICT | College of Computing Studies, Information and Communication Technology |
| CCJE | College of Criminal Justice Education |
| IAT | Institute of Agricultural Technology |
| PS | Polytechnic School |

Each approved department account opens **Department PPMP**, selects a fiscal year, searches the shared CSE Master List, enters positive quantities and optional item/request notes, then chooses **Submit PPMP to Academic Affairs**. The server copies the catalog name, category, unit and estimated unit cost into that department's submitted snapshot. A department may instead choose **Mark No PPMP this year**. The database enforces one response for each department and year; No PPMP can later be replaced by the year's request, while an already submitted PPMP cannot be replaced or edited. Department accounts can read only their own original request and cannot use the existing order workflow to bypass this route.

AA alone sees the **Department Wishlist** sidebar. For the selected fiscal year it shows all seven departments, their Submitted/No PPMP/Awaiting response, submitted lines and totals, and AA review state. A department submission or No PPMP response creates an in-system notification for AA. Administrator and other roles cannot enter this workflow through its API.

AA uses **Create Review Copy** on a submitted PPMP. Only one copy exists for that original. AA can edit copied item names, categories, units, quantities, estimated unit costs and remarks, edit review notes, add/remove copied lines, save as Draft, and mark the copy Reviewed. The original department identity and fiscal year remain the collection's source identity. AA edits never update the original snapshot or shared CSE Master List. A later edit resets Reviewed to Draft until AA explicitly marks the updated copy Reviewed again. Review completion notifies the submitting department and records the reviewer and time.

The annual collection becomes **Ready to Submit** only when every department has submitted or reported No PPMP and every submitted PPMP has a Reviewed AA copy. No PPMP responses need no copy. The collection retains separate department PPMPs, rather than combining their lines into one document. Ready to Submit is computed from the stored responses and copies; this revision does not select a downstream recipient, create an APP, or execute a final submission action.

The isolated workflow test has verified submission routing, annual uniqueness, original/catalog preservation, AA review and collection readiness. Edge browser checks verified the main department and AA interactions with zero uncaught JavaScript errors. Local verification evidence and production deployment limits are recorded in Section 17.

## 12. Role and Permission Guide

| Role group | PPMP responsibilities | Consolidation responsibilities | APP responsibilities | Administration |
| --- | --- | --- | --- | --- |
| Administrator | Global inspection and final PPMP decisions | Inspect resulting records; no operational batch creation | Global inspection, final approval/finalization, export; no draft creation | Account approval/status, audit, notifications, reports |
| Office roles | Own-office PPMP draft, items, submit, Wishlist request, own-office reports/export | None | None unless a future permission is explicitly assigned | Own account only |
| CED, CBM, CAS, CCSICT, CCJE, IAT, PS | Own annual department CSE-based PPMP request or No PPMP response; read own original | None | None | One account per department role; normal Administrator approval |
| EO / AA | Request/monitor PPMP, review, comment, report/export | None | View, review/return at assigned stage, report/export | Survey management |
| AA department intake | Exclusive Department Wishlist collection; create/edit/complete department review copies | Readiness only; no batch creation through this workflow | No APP creation through this workflow | Original submission and CSE values are preserved |
| Procurement | View/review PPMP, approve for final PPMP stage, report/export | Create batch from eligible approved PPMP sources | View, create/edit/submit APP, review tools, comment, report/export | No account approval |
| BAC Chairman | No general PPMP operational permissions | None | View, first APP review, return/reject, APP(CSE) review/approval permission, export | None |
| Budget | PPMP view/review/comment/report | None | View, assigned APP review, return/reject, APP(CSE) review, export | None |

Every role is singular per account. A role carrying both PPMP and APP permissions uses one login and one audit identity.

Department roles receive only `ppmp.department_wishlist.view` and `ppmp.department_wishlist.submit`. AA receives view/review permissions in addition to its existing permissions. The AA-only checks apply even to the Administrator's general wildcard permissions.

## 13. Data Model and Record-Separation Guide

| Table/model | Purpose | Important relationship or protection |
| --- | --- | --- |
| `colleges` | Active Office directory | Referenced by users and PPMP records; office management UI is intentionally removed |
| `users` | Identity, role, office, status, password hash | Unique username, email, and active role reservation |
| `password_reset_requests` | Hashed one-time recovery state | Deleted with its user; code attempts and expiry retained while active |
| `ppmp_submission_requests` | EO/AA request for an office/year PPMP | Links to an office and optional PPMP record |
| `ppmp_records` | Official office/year PPMP document | Unique office/year; retains preparer/reviewer/approver references |
| `ppmp_record_items` | Twelve-column planning rows in one PPMP document | Deleted only with its parent record |
| `department_ppmp_submissions` | Department/year Submitted or No PPMP response | Unique department/year; submitted original is read-only through the workflow API |
| `department_ppmp_submission_items` | Original CSE item snapshot and requested quantity | Stored name/category/unit/cost survive later catalog edits; unique selected catalog item within a submission |
| `department_ppmp_review_copies` | AA working copy and Draft/Reviewed completion | Unique original submission; retains creator, reviewer and timestamps |
| `department_ppmp_review_items` | AA editable copied or added rows | Separate storage preserves source submission and CSE catalog; positive quantity/non-negative unit cost |
| `ppmp_items` | Approved/materialized items for consolidation | Not the same as record rows or Wishlist requests |
| `wishlist_items` | Reusable CSE Master List catalog | Custom order lines do not enter this table; legacy quantity remains stored but is not stock-limited in the current UI/workflow |
| `wishlist_requests` | Preserved legacy single-item request link | Kept for migration/history compatibility |
| `ppmp_orders` | Wishlist request/order header | Contains reference, office, requester, status, totals, and decision |
| `ppmp_order_items` | Master-linked or custom request lines | Preserves origin and prevents catalog pollution; stores the selected-request report inputs for Columns 4 through 8, with procurement method safely widened to 255 characters |
| `ppmp_reports` | Administrator-published PPMP report definitions | References one office and optional fiscal year; report rows are queried live with authorization |
| `ppmp_comments` | PPMP/item/order comments and reasons | Append-only, optionally linked to a specific entity |
| `consolidation_batches` | Fiscal-year and APP-cycle grouping | Created only by Procurement |
| `consolidation_sources` | Batch-to-approved-PPMP source mapping | Unique source use prevents duplicate consolidation |
| `annual_procurement_plans` | APP, APP(CSE), or APP Non-CSE header | Unique Office/year/type; normal drafts require a batch, controlled external imports use explicit provenance |
| `app_sections` | Printed APP group/section headings | Separate from procurement item rows |
| `app_items` | Official twelve-column APP project rows | Optional legitimate PPMP source link; Decimal budget; source-format omissions remain NULL only on locked imports |
| `app_approvals` | APP submit/review/approval/finalization history | Append-only actor, role, action, note, time |
| `app_comments` | General or item-specific APP notes | Child membership validated server-side |
| `ppmp_notifications` | Per-user in-system alerts | Removed when its user is intentionally deleted |
| `workflow_audit_log` | Cross-module security and workflow evidence | Actor becomes null if an account is removed; event remains |
| `surveys`, `survey_recipients` | Auxiliary feedback and recipient response | Independent of procurement workflow states |

## 14. Normal End-to-End Operating Procedure

1. Administrator starts with the permanent Admin account and confirms the Office directory and fiscal-year requirements.
2. Each user registers one operational Role and correct Office.
3. Administrator verifies the registration and approves the account.
4. EO/AA requests PPMP submissions from Offices when that request-driven process is used.
5. Office user creates the PPMP draft, completes its rows, saves, and submits.
6. EO/AA reviews; Procurement reviews; Administrator approves. Returned records are corrected and resubmitted with history intact.
7. Approval materializes legitimate `ppmp_items` without deleting the PPMP document.
8. When an Office uses the master/unlisted ordering workspace, its submitted order goes to APP/Procurement consolidation, then Administrator review; approval sends an in-system notification to the requester.
9. Procurement selects eligible approved items and creates one Consolidation batch for the year/cycle.
10. Procurement creates the Office APP/APP(CSE) from that batch. Source-mapped values appear automatically; unmapped APP fields are completed manually.
11. Procurement checks sections, all twelve fields, timelines, and totals, then submits.
12. BAC Chairman, EO, Budget, and Administrator review in order. Any Return includes a correction reason.
13. Administrator approves and finalizes. Authorized users export the APP PDF/Excel generated from the same database rows.

### Department annual collection procedure

1. Each designated department registers its matching Office/Role and receives normal Administrator account approval.
2. Select the fiscal year in Department PPMP and submit CSE quantities to AA, or report No PPMP.
3. AA opens Department Wishlist for the same year and checks all seven response states.
4. For each Submitted request, AA creates a review copy, edits the copy as needed, saves Draft and marks Reviewed when complete.
5. Confirm Ready to Submit after all seven departments have responded and each submitted request is Reviewed. Any later AA edit requires the affected copy to be reviewed again.

The existing office PPMP, order, consolidation and APP procedures above continue independently. The department collection currently ends at readiness; further routing requires an explicit next-stage business rule.

## 15. Installation, Startup, Migration, and Recovery

### Normal startup

Use the project virtual environment, install the pinned Python requirements, and run `python app.py`. SQLite is the default database (`ppmp.sqlite` beside `app.py`); set `DATABASE_URL` for another persistent SQLite path or set `DB_BACKEND=mariadb` to select the retained MariaDB `DB_*` values. For a new SQLite file, run `python app.py --migrate-only` to create its schema and initial Administrator. This does not copy records from MariaDB. Normal startup verifies the schema but does not create, reset, or migrate production tables. The development URL is normally `http://127.0.0.1:5000`.

### Additive migration

Before a schema revision, stop conflicting writers, back up the active SQLite file or create a MariaDB dump as applicable, and execute `python app.py --migrate-only`. Read the output and run schema verification before normal startup. Never use the reset option on live data.

For the 2026-10-15 Department PPMP revision, the same command creates four new `department_ppmp_*` tables. Render PostgreSQL has a narrow startup exception: when the platform's built-in `RENDER=true` variable is present, WSGI creates only these four tables if missing using a transaction and PostgreSQL advisory lock, then performs normal read-only schema verification. It does not apply existing-table migrations or reset/seed/update existing records. This allows the current free service's Gunicorn command to start the revision without a paid pre-deploy step. Other installations use the existing additive migration command. Render describes its built-in flag in [Environment Variables and Secrets](https://render.com/docs/environment-variables). Implementation and isolated tests did not migrate or alter local/production databases, create department accounts, or insert real department requests.

### Backup and restore

A valid backup is a non-empty MariaDB SQL dump produced before destructive or schema-changing work. Restore into a separate verification database first, inspect row counts and constraints, then schedule a controlled production restore if required. Never overwrite the only backup.

### Fresh account baseline performed on 2026-09-06

Before the requested account cleanup, the system created `backups/ppmp_db_before_fresh_account_reset_20260906.sql` (51,536 bytes). Three non-Administrator accounts were removed. The one permanent Admin remains Active. Account-owned notifications and reset requests followed their foreign-key cascade; procurement authorship fields used `SET NULL`; no procurement/business row was deleted.

Preserved live counts after cleanup were: Colleges 1; PPMP Items 0; PPMP Records 0; PPMP Record Items 0; Master Wishlist Items 1; Wishlist Requests 1; PPMP Orders 1; PPMP Order Items 1; PPMP Comments 0; Consolidation Batches/Sources 0; APP headers/sections/items/approvals/comments 0; Surveys/Recipients 0. This is a fresh account start, not a procurement-data reset.

## 16. Mandatory Living-Documentation Procedure

Every future feature, revision, removal, bug fix, workflow change, role/permission change, database migration, security change, or report/UI change must update both the historical and living documentation in the same work item.

1. Inspect the current code, schema, and `SYSTEM_REVISION_RECORD.md` before changing behavior.
2. Record the request, root cause/decision, affected files, data impact, permissions, migration/backup, verification, remaining risks, and final status in `SYSTEM_REVISION_RECORD.md`.
3. Update the relevant current-state explanations, role guide, workflow, data model, operations, and verification sections in this Markdown source.
4. Update `ppmp/CHANGELOG.md` with a concise implementation entry.
5. Run `python scripts/generate_documentation.py` from the `ppmp` directory.
6. Verify that the PDF exists, has pages and extractable text, includes the latest revision marker, and was generated after the Markdown source.
7. Do not mark the revision Verified until code tests, database checks, and applicable browser tests pass.

The Markdown source is authoritative for editing. The PDF is a generated controlled deliverable and must never be edited manually.

This local archive keeps the master revision record, living Markdown and generated PDF beside the `ppmp` directory. The GitHub deployment repository publishes the same filenames under `docs/`; the application source remains at the repository root.

## 17. Verification Record

### 2026-10-15 Department PPMP revision

- **Implementation status:** Implemented and locally verified, subject to three confirmed pre-existing legacy UI test failures. Production PostgreSQL deployment has not been observed.
- Focused isolated test `test_department_wishlist_routes_to_aa_and_review_copy_preserves_original` passed. It exercises department registration/approval, own-department intake, one-request-per-year enforcement, denial of legacy order bypass, AA review-copy editing, original/catalog preservation, all-seven response readiness, and Administrator denial.
- Python compilation of `app.py` and `models.py` and validation of both Jinja templates passed.
- The regression run executed 35 tests: 32 passed and three legacy UI assertions failed in activity-tracker markup, loading-overlay expectations, and primary PPMP navigation expectations. All three failures also occurred on the downloaded pre-revision GitHub baseline `da3e895`. The PDF-dependent test ran after PyPDF2 was installed.
- The four-table additive schema routine was applied twice to an isolated SQLite database and preserved its existing user and CSE catalog records.
- Headless Edge passed 32 workflow/UI assertions with zero uncaught JavaScript errors. Verified all seven department landings and annual responses; AA-only menu visibility with Administrator/Cashier controls hidden; CSE search and year-specific draft persistence; submission of visible and search-hidden selected rows; long catalog names; AA copy creation, editing and Reviewed save with safely handled quoted text; original preservation; and readiness becoming complete, resetting on Draft edits, and restoring after re-review. Dashboard and Login inline scripts parsed successfully. Layout screenshots were visually inspected.
- Production PostgreSQL deployment and its startup bootstrap have not been observed. No live database or production workflow records were changed by these checks.

### Historical verification evidence

- Python compilation: passed for `app.py` and `models.py`.
- Automated regression: 25 tests passed, including registration uniqueness, pending/approved status, system notification, PPMP image-import validation/idempotence, direct Procurement order routing, APP source materialization, clear-source validation, blank-CSE protection, 12-column item validation, multiple rows, sections, totals, role sequence, Admin restrictions, PDF/Excel, and PPMP preservation.
- Template JavaScript parsing: both dashboard and Login scripts passed.
- MariaDB migration: completed with no reset and schema verification passed.
- Live data integrity: two explicit external-source APP headers, seven sections, and 145 APP items are present; no false PPMP/consolidation links or APP approval events were created. Existing users, offices, PPMP, Wishlist, and permission data were preserved.
- Live browser verification: passed at desktop (1440x1000) and mobile (390x844). The Registration controls, Admin restrictions, 12-column grouped APP table, contained horizontal scrolling, Account Approval workspace, responsive layout, and relevant console/network behavior were verified without inserting test data.
- Fresh-start account reset: protected by a 51,536-byte MariaDB backup; three non-Administrator accounts removed; exactly one Active Administrator remains; all procurement/business table counts matched before and after.
- Authorized APP visibility regression: Procurement can create an APP only from a legitimate non-empty batch, then retrieve the same record from APP Records, APP Dashboard, metadata, detail, and exports. Review roles use that same record and do not receive copied dashboard data.
- Post-reset browser verification: passed at desktop and mobile; Login/Registration, empty Account Approval, Admin APP restrictions, grouped twelve-column rendering, and contained horizontal scrolling remained operational with no page or failed-request errors.
- Generated-document validation: PDF generation completed atomically; the resulting PDF contained 12 pages, extractable text, the complete-feature manual, mandatory documentation procedure, APP table explanation, fresh-account revision marker, and correct document metadata.
- FY 2026 source reconciliation: the final GAA PDF produced 40 rows totaling PHP 93,459,200.00; the all-funds workbook produced 105 rows totaling PHP 186,019,821.30; the APP-CSE workbook contained 318 zero-quantity catalog rows and was not imported as requirements. Both populated APP records passed authorized API detail and PDF/Excel export checks.
- Current generated-document validation: the revised PDF is generated from this Markdown source, is newer than it, has extractable text and correct metadata, and contains the real APP source, Admin Master Wishlist controls, 15-second hidden-timer behavior, and PHP 186,019,821.30 verification markers.
- InfinityLoop authentication transition: Login and Dashboard scripts retain the explicit `15_000` millisecond constants, post-success wait ordering, error cancellation, HTML cache prevention, and Logout loader isolation. The refreshed Login has InfinityLoop and no timer node/text. Chromium measured the two timing helpers at 15,002 ms and 15,009 ms with zero countdown nodes.
- PPMP item/order revision: MariaDB backup and controlled source hashes passed; 29 image rows imported once and the second apply was a no-op. Live counts remain two APP records/145 APP items, one PPMP document, one existing order, and 30 master Wishlist rows. Administrator and PPMP-user Chromium checks passed item search, navigation, pending-order selection, unlisted-item access, real APP visibility, hidden timer, and zero browser errors without creating test orders.
- CSE/report revision: Python compilation and all 26 automated regressions passed. The 129,076-byte pre-migration MariaDB backup has SHA-256 `8496DD943CA1BFBC50D9F9A854A9C8905B62354A4D11850F4FAA628D1F2026BA`; two consecutive additive migrations succeeded. The migration snapshot remained 3 users, 2 offices, 31 CSE entries, 1 PPMP record, 7 PPMP orders, 2 APP plans, and 145 APP items; the new `ppmp_reports` table contained zero rows because no fake publication was created. During final validation, the real CBAO user submitted `PPMPR-20260916-DDEEFC4218` using GAA/101 and Goods/Services, increasing the live PPMP order count to 8; this concurrent real record was preserved. Read-only live API checks confirmed the exact restricted category/fund/type lists and HTTP 403 cross-office protection. Visible Chromium checks passed for Administrator and CBAO dashboards with zero console errors.
- User-selected PPMP request report: compilation and all 27 automated regressions passed. The 137,672-byte pre-migration backup has SHA-256 `6D0B012FF7E76162D4B2F7A2E1DB135508E7262DA0BBDC3E68FD365BACC12781`; two additive migrations succeeded and widened only `ppmp_order_items.procurement_method` from 120 to 255 characters. Counts remained 3 users, 2 offices, 31 CSE entries, 1 PPMP record, 9 PPMP orders, 32 order items, 2 APP plans, 145 APP items, and 0 publication rows. Live read-only API and visible Chromium checks opened only request `PPMPR-20260917-C37F4FB93A`, showing its 6 items, Fiscal Year 2026, CBAO, exactly 12 headers, all 26 methods, only PDF/Excel choices, and zero browser errors without changing live data. The isolated regression also verified cross-office denial, forbidden-field rejection, completeness blocking, PDF seal/text, and a 12-column Excel workbook.
- Loading/search repair: the invalid empty WebSocket expression was reproduced in rendered JavaScript and corrected. Template parsing, Python compilation, the focused loading regression, the selected-request Excel regression, and all 27 automated regressions passed. Visible Chromium exercised both CSE searches with a deliberately delayed response: neither search displayed the global loader, the latest results rendered, the defensive reset succeeded, and browser errors remained empty. No database or permission change occurred.

## 18. System Revision History

### Revision: Department PPMP Intake and Academic Affairs Review Collection

- **Date:** 2026-10-15.
- **Status:** Implemented and locally verified, subject to three confirmed pre-existing legacy UI test failures; production PostgreSQL deployment has not been observed.
- **Request:** Give CED, CBM, CAS, CCSICT, CCJE, IAT and PS one account each and one annual CSE-based PPMP response directed only to AA. AA reviews a separate editable copy per department and prepares a collection when all seven have responded.
- **Affected modules:** Department registration/permissions, four new relational tables, authenticated intake/review APIs, Render PostgreSQL WSGI bootstrap, department/AA dashboard panels, notifications/audit, isolated regression, revision records and operating documentation.
- **Behavior:** Submitted originals remain immutable through workflow routes; AA edits only its copy. Submitted or No PPMP is required for each department, and every submitted copy must be Reviewed before Ready to Submit. A later AA edit requires renewed review. The collection does not merge separate department PPMPs or perform an unspecified downstream submission.
- **Data/deployment:** Render PostgreSQL WSGI startup creates only missing department tables under a transaction/advisory lock, then verifies the schema; other installations use additive `python app.py --migrate-only`. No local/production database migration, reset, seed or live-data update was performed during implementation.
- **Evidence and limits:** Focused workflow regression, Python compilation, Jinja parsing, repeated additive-schema checks and 32 Edge workflow/UI assertions passed with zero uncaught JavaScript errors; layout screenshots were inspected. Of 35 regression tests, 32 passed and three legacy UI failures also reproduced on baseline `da3e895`. Production PostgreSQL deployment and startup bootstrap have not been observed.

### Revision: Non-Blocking Search and Loading Recovery

- **Date:** 2026-09-22
- **Request:** Prevent loading from remaining on screen and remove the loading overlay from search operations.
- **Root cause:** An invalid WebSocket Jinja expression rendered `const WS = ;` and stopped dashboard initialization; both CSE searches also enabled the blocking global loader for every keystroke.
- **Affected modules:** Authenticated dashboard template, loader/search regression assertions, selected PPMP Excel exporter, revision records, living documentation, and generated PDF.
- **New behavior:** Dashboard JavaScript initializes with or without a WebSocket URL; the loader starts hidden and has centralized cleanup/failsafe behavior; both searches are silently debounced and stale-safe; Login and Logout retain their separate 15-second transition.
- **Database impact:** None. No data or schema was changed.
- **Security impact:** None. Existing authentication, office scope, roles, and protected search endpoint remain unchanged.
- **Evidence:** Template parsing and Python compilation passed; all 27 tests passed; visible Chromium confirmed two loader-free searches, successful defensive reset, rendered results, and zero browser errors.
- **Final result:** [IMPLEMENTED AND VERIFIED]

### Revision: User-Selected Twelve-Column PPMP Request Report

- **Date:** 2026-09-21
- **Request:** Make each Pending PPMP Request Record open only its own requested items, display the real Fiscal Year and End-User or Implementing Unit, provide exactly twelve prescribed report columns with input only in Columns 4 through 8, and export the same record to PDF or Excel.
- **Affected modules:** PPMP report constants and authorization, selected-order detail/update/export APIs, request-record UI, PPMP order-item schema, migrations, regression tests, revision records, living documentation, and generated PDF.
- **Old behavior:** The page summarized multiple requests and exported a seven-column request list; it did not provide a selected-request item report or the required controlled inputs.
- **New behavior:** A selectable Pending row opens only that authorized request; displays its actual year, office, and items; permits the requesting user to fill only Columns 4 through 8; validates all 26 procurement methods and Yes/No; and exports the same exact twelve-column data to PDF or Excel after completeness validation.
- **Database impact:** Only `ppmp_order_items.procurement_method` widened from `VARCHAR(120)` to `VARCHAR(255)` after a verified backup. No business row was created, deleted, or rewritten by the migration.
- **Security impact:** Selected requests are reloaded and office-scoped server-side; cross-office identifiers are denied; only the original requesting user can change Columns 4 through 8; exports require the existing export permission.
- **Evidence:** 27 automated tests passed; migration was idempotent with unchanged counts; live read-only API checks returned the real CBAO request and its 6 items; visible Chromium confirmed 12 columns, 26 methods, PDF/Excel only, and zero browser errors.
- **Reference limitation:** No separate sample PDF/image accompanied the revision, so textual and functional conformance was verified but a pixel-level external comparison was unavailable.
- **Final result:** [IMPLEMENTED AND VERIFIED AGAINST THE PROVIDED TEXTUAL REQUIREMENTS]

### Revision: CSE Master List, PPMP Order Controls, and Authorized Reports

- **Date:** 2026-09-16
- **Request:** Rename the visible Master Wishlist to CSE Master List; remove Available Quantity stock behavior; rename Current PPMP Order; constrain unlisted categories and PPMP order fund/type choices; and provide office-scoped reports that the Administrator can publish/update.
- **Affected modules:** PPMP permissions and metadata, CSE catalog APIs and UI, PPMP order validation, report model/routes/exports, dashboard JavaScript, tests, MariaDB schema, revision records, living documentation, and generated PDF.
- **Old behavior:** Catalog terminology and quantity appeared as inventory, order dropdowns reused broader APP/PPMP lists, office users lacked the revised Reports workflow, and only the Administrator could open the PPMP order analytics endpoint.
- **New behavior:** CSE terminology is consistent in the active UI; request quantity is independent of stored catalog history; custom Category is Goods/Infrastructure/Consulting Services; order funds are GAA/101, SB 164, 161, and 601; order types are Goods/Services, Infrastructure, and Consulting Services; PPMP users can generate/export authorized records; and Administrator publications are visible only to their selected office.
- **Database impact:** One additive `ppmp_reports` table; no existing row deletion, rewrite, fake report, or APP change. The legacy `wishlist_items.quantity` column is preserved.
- **Security impact:** Server-side permission and office filters protect report listing, generation, and exports. Administrator-only CSE create/edit/delete and publication/update routes remain enforced independently of the UI.
- **Evidence:** 26 automated tests passed; migration was idempotent; all protected business counts matched before/after; live CBAO cross-office access returned 403; visible Chromium passed both role views with zero console errors.
- **Final result:** [IMPLEMENTED AND VERIFIED]

### Revision: Registration, Approval Status, and Real APP Digital Table

- **Date:** 2026-09-06
- **Request:** Replace Available Role registration UX, add safe system-only approval status, analyze/move the Admin APP launcher, and implement the real 12-column APP.
- **Affected modules:** Authentication, registration, Admin account approval, APP dashboard, APP workflow, reports, database, tests, documentation.
- **Old behavior:** Registration exposed “Available role,” had no confirmation field/status popup; pending login was generic; APP contained only a record launcher/list with no APP rows or APP-specific export.
- **New behavior:** One Role selector; signed status reference and popups; specific secure account-state feedback; Procurement-owned APP creation; relational sections/items/comments; full APP table, totals, workflow, source visibility, and PDF/Excel.
- **Database impact:** Additive three-table migration; no data deletion or reference-data import.
- **Security impact:** Stronger status handling, object validation, and operational-role separation.
- **Reason:** Match the approved account architecture and supplied real APP form while preserving the PPMP-to-APP dependency.
- **Final result:** [IMPLEMENTED AND VERIFIED]

### Revision: Admin Master Wishlist Management and 15-Second Authentication

- **Date:** 2026-09-11
- **Request:** Reduce the successful Login/Logout transition to 15 seconds; move Master Wishlist creation to the Admin Dashboard; give only the Administrator Edit/Delete actions in Master Wishlist; distinguish the twelve-column PPMP planning-row form; replace the native Administrator-comment prompt.
- **Affected modules:** Login and Dashboard templates, Master Wishlist API safeguards, UI and API regressions, revision records, living documentation, and generated PDF.
- **Old behavior:** The Master Wishlist add form was located in the PPMP Wishlist workspace, the twelve-column office planning-row editor was labelled Add Wishlist Item, catalog rows had no Admin Edit/Delete controls, and adding an order comment opened a browser-native address prompt.
- **New behavior:** The Admin Dashboard owns catalog creation; Master Wishlist exposes Admin-only Edit/Delete controls; referenced entries cannot be deleted; office users retain search and Add to Order only; the planning editor is clearly labelled Add PPMP Planning Row; comments use an in-system Admin-only modal; the hidden InfinityLoop transition lasts 15 seconds after successful Login/Logout.
- **Database impact:** None. No migration, seed, reset, or live-data mutation was required.
- **Security impact:** Create, update, delete, and comment APIs remain protected on the server; UI visibility does not grant authority. Referential checks preserve order/request history.
- **Evidence:** 25 automated tests passed. Chromium verified Admin and office-user controls, edit-form population/cancellation, custom comment modal, zero page errors, and measured the two hidden-countdown timing helpers at 15,002 ms and 15,009 ms without submitting or mutating data.
- **Final result:** [IMPLEMENTED AND VERIFIED]

### Revision: PPMP Dashboard Catalog, APP Consolidation Route, and Source Images

- **Date:** 2026-09-11
- **Request:** Restore visible item management; show searchable PPMP items and pending-order actions on the PPMP Dashboard; route submitted orders through APP users before Administrator approval; notify the requester; import the supplied PPMP image data; hide the timer text while preserving 30 seconds.
- **Affected modules:** PPMP Dashboard/navigation, master Wishlist, order workflow, notifications, authentication loader, MariaDB import/audit, tests, and living documentation.
- **Old behavior:** Administrator dashboard links were hidden, the master Add Item form was unreachable, dashboard users could not search/add items there, and new master/custom orders went directly to Administrator review.
- **New behavior at that revision:** Both Admin dashboards became reachable; PPMP Dashboard exposed the real searchable Supply Office rows and direct pending-order selection; unlisted items stayed order-only; Procurement received Submitted orders in the APP Dashboard consolidation queue before Administrator review; approval notified the requester; timer text was removed while the then-current 30-second hold remained. The later Admin Master Wishlist revision shortened that hold to 15 seconds.
- **Database impact:** Additive import of 29 Available `wishlist_items` and one audit event after a verified SQL backup. No schema reset and no existing record overwrite.
- **Source limitations:** The PHP 23,000.00 maintenance row lacks quantity/unit and was not fabricated; the source's printed total exceeds readable row totals by PHP 1,100.00.
- **Evidence:** 25 tests, two successful Chromium role checks, live MariaDB counts, idempotent second import, source hashes, and `PPMP_SOURCE_DATA_AUDIT_2026.md`.
- **Final result:** [IMPLEMENTED AND VERIFIED WITH DOCUMENTED SOURCE LIMITATIONS]

### Revision: Fresh Account Baseline and Complete Living Manual

- **Date:** 2026-09-06
- **Request:** Remove every non-Administrator account for a fresh start, retain the permanent Admin, confirm real APP/consolidation access for authorized users, and complete a PDF that explains every feature.
- **Affected modules:** Live MariaDB account data, APP access regression, tests, revision record, changelog, living Markdown, and generated PDF.
- **Old behavior:** Four accounts existed and the PDF focused mainly on the registration/APP revision rather than serving as the complete operating manual.
- **New behavior:** One active permanent Administrator remains; procurement records are preserved; future users register and await approval; authorized APP roles read one shared set of APP rows; the manual now covers authentication, dashboards, PPMP, Wishlist, Consolidation, APP, notifications, surveys, reports, schema, audit, deployment, recovery, and future documentation procedure.
- **Database impact:** Three non-Administrator users deleted after a verified SQL backup. Foreign keys preserved business rows and removed only user-owned reset/notification records.
- **Security impact:** Old non-Administrator sessions can no longer resolve to accounts; the Admin remains active; role slots are available for new approved registrations.
- **Final result:** [IMPLEMENTED AND VERIFIED]

### Revision: Real FY 2026 APP Source Reconciliation

- **Date:** 2026-09-10
- **Request:** Continue the APP data import and confirm all real data using the clear PDF and Excel source set.
- **Affected modules:** APP models, migration, dashboard source display, import scripts, MariaDB APP rows, tests, revision records, and generated documentation.
- **Old behavior:** The first image transcription contained two ambiguous budgets and represented only the photographed GAA document; the clear all-funds and APP-CSE workbooks had not been audited.
- **New behavior:** The final GAA record matches the 40-row PDF and PHP 93,459,200.00 total; a separate read-only 105-row APP Non-CSE record preserves the PHP 186,019,821.30 all-funds workbook; the zero-quantity APP-CSE template remains source evidence and does not appear as fake requirements.
- **Database impact:** Source-provenance columns added; `general_description` relaxed only for locked source formats that omit it; two externally sourced APP records now contain 145 real rows and no consolidation/approval fabrication.
- **Security impact:** Normal APP creation still requires Procurement plus a real consolidation batch; all view/export routes retain `app.view`; external imports are conflict-blocking and read-only.
- **Evidence:** `APP_SOURCE_DATA_AUDIT_2026.md`, two verified SQL backups, 24 passing regressions, MariaDB invariants, authorized API checks, and valid APP PDF/Excel exports.
- **Final result:** [IMPLEMENTED AND VERIFIED]

### Revision: InfinityLoop Authentication Transitions

- **Date:** 2026-09-10
- **Request:** Change the Login animation to the supplied InfinityLoop design and strictly retain loading for 30 seconds while logging in and logging out.
- **Affected modules:** Flask template/cache configuration, Login template, Dashboard template, UI regression test, revision records, living documentation, and generated PDF.
- **Old behavior:** Login and Logout reused the former path-runner loader and navigated as soon as the server request completed.
- **New behavior at that revision:** Both authentication transitions used a responsive InfinityLoop SVG/CSS animation and visible countdown. Successful Login and Logout navigation waited until the measured 30-second minimum expired; unsuccessful actions cancelled immediately and retained the existing error UI. Later 2026-09-11 revisions hid the countdown and then shortened the transition to 15 seconds.
- **Architecture decision:** The React/Vite alias import was translated to native template markup because this Flask/Jinja application has no React runtime or `@/` module alias; adding the literal import would break the page.
- **Database impact:** None. No migration or data mutation.
- **Security impact:** Server authentication, account checks, sessions, and role permissions are unchanged; Logout still clears the server session before completing its visual hold.
- **Evidence:** Python compilation, Node.js parsing for both templates, all 24 automated regressions, refreshed live HTTP checks, and a 30,486 ms Chromium animation/timing test passed. The old animation was absent.
- **Final result:** [IMPLEMENTED AND VERIFIED]

Earlier revision details remain in `SYSTEM_REVISION_RECORD.md`; this living reviewer describes the current implemented state and must be regenerated after every future feature, revision, removal, security change, workflow change, or bug fix.
