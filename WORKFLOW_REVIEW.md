# Revised PPMP and APP workflow

Implemented and reviewed locally. The user authorized publishing this workflow and outstanding minor revisions to GitHub on October 19, 2026.

## Official PPMP

- Offices and Colleges select catalog or unlisted items and create their official draft.
- Each office has one official PPMP per fiscal year, beginning in 2026.
- The creator completes the twelve report columns, saves, and submits to Procurement.
- Procurement reviews, then Admin approves. Approved PPMP data is locked.
- A return requires a comment. The creator corrects the document and resubmits to the reviewer who returned it.
- Admin can return incomplete legacy requests directly from the PPMP report, including historical Requested or Returned records. The creator can edit, save, and resubmit a Returned legacy record without first designating it official. Admin must still explicitly designate the correct office/year PPMP before final approval; legacy correction does not replace another official source.
- Returned reports display the review comment, creator instructions, and missing required fields. Resubmit is enabled after the complete report is saved. Historical returns recover their reviewer from the audit history, defaulting to Admin for the former Wishlist request flow.
- Incomplete reports cannot be approved. A valid Admin approval attempt on an incomplete report returns it to the creator with a generated correction comment and a notification. Approved source documents remain locked.
- The Start/End of Procurement Activity and Expected Delivery report fields accept typed month/year values (for example January 2027, Jan 2027, 01/2027, or 2027-01) as well as the calendar picker. Saved values remain YYYY-MM for the existing API, report exports, indicative copies, and timeline validation. Both input controls remain locked outside report edit mode.
- Previously saved records are retained. Admin explicitly designates which existing request is official when historical records overlap in a year.

## Indicative copies

- An approved official PPMP can generate an independent editable indicative copy.
- Editing or deleting that copy never modifies the official PPMP or consolidated sources.
- Copies retain the PPMP report layout and have separate saves, print preview, PDF, and Excel exports.

## Consolidation

- Only Admin creates batches and prepares APP drafts.
- Batches draw from approved official PPMPs across Offices and Colleges in the same fiscal year.
- Sources can enter consolidation once; later batches cannot duplicate them.
- Items merge only when item/specifications, unit, fund source, procurement mode, full schedule, and fiscal year match.
- Merged rows preserve each source, office, original quantity/budget, and revised APP contribution.
- APP quantities and budgets must equal the sum of office contributions. Official source documents remain unchanged.

## APP review

Admin prepares and submits → BAC Chairman → Budget Office → EO → Final Admin approval.

- Final Admin approval finalizes the APP.
- A return requires a comment. Admin edits using office feedback and resubmits to the returning reviewer.
- An additional batch joins an existing APP while it is being reviewed. Completed reviews are retained; new items proceed from the current review stage.
- Missing APP-only fields on newly added rows must be completed before the current reviewer can approve.
- Batches received after final approval create a supplemental APP linked to the annual APP.
- History records batch additions, corrections, comments, review roles, and the exact item snapshot at each approval.
- Final APPs support PDF, Excel, and print preview, including contribution details.

## Local review

### Live notifications

- Notifications load for the signed-in recipient and refresh every five seconds while the page is visible.
- Clicking opens the specific PPMP report, APP, office feedback section, or pending account registration.
- Opening a review marks it read. Its notification stays until the required approval, return, rejection, or resubmission succeeds, then clears for all assigned recipients.
- Informational notifications clear after they are opened. Existing notification messages are linked during the explicit database migration where their source can be identified.
- Apply `python app.py --migrate-only` after backing up an existing database when installing the notification links update. It adds destination and completion fields without deleting messages or procurement records.

Use the project virtual environment from `PPMP_System/ppmp`:

```powershell
..\.venv\Scripts\python.exe app.py --migrate-only
..\.venv\Scripts\python.exe app.py
```

The migration is additive. Back up the configured database before applying it. Automated workflow checks use isolated test databases, separate from office records.
