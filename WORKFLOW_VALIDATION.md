# Local workflow validation

The revised workflow is implemented. The user authorized publishing the workflow and outstanding minor revisions to GitHub on October 19, 2026.

## Passed checks

- 34 automated checks: 17 official PPMP/copy tests, 13 APP/consolidation tests, and 4 startup tests.
- 17 Edge browser checks, including rendered JavaScript parsing, designation of historical requests, official draft creation and submission, approved-record locking, independent copy editing, Admin-only consolidation, merged office contributions, late batches retaining the Budget reviewer, new-row completion during review, and browser PDF print output for both PPMP and APP.
- The migration was first applied to a copy of the local SQLite database. It preserved existing data across all 31 existing tables and added five workflow tables.
- A timestamped SQLite backup was created before applying the migration locally. The local migration and schema verification completed successfully.
- Workflow fixtures and browser samples used only isolated in-memory SQLite databases. Sample offices, requests, and APPs were not inserted into the user's database.

Run the automated checks from `PPMP_System/ppmp`:

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_workflow_ppmp tests.test_workflow_app tests.test_startup -q
```

## Review artifacts

Local artifacts are in `backups/revised-workflow-review/`, which is excluded from Git:

- `admin-consolidated-app.png`
- `admin-consolidation.png`
- `office-contributions.png`
- `official-draft-ready-to-submit.png`
- `approved-official-ppmp.png`
- `editable-indicative-copy.png`
- `budget-review.png`
- `app-print-preview.pdf` and `ppmp-print-preview.pdf`
- `browser-results.json` and `migration-results.json`
- `ppmp_before_revised_workflow_20261018_230911.sqlite`

## Separate account test findings

The broader, existing `tests/test_admin_account_security.py` suite does not pass against the checkout's authentication code. Its anonymous/non-Admin administration restrictions and password-recovery expectations differ from the current authentication implementation. The isolated anonymous-access test reproduces the mismatch by itself; this is not caused by running the workflow tests together.

Authentication functions were not changed as part of this workflow implementation. Account test output is retained in `backups/revised-workflow-review/account-check.txt`. These failures remain outside the workflow changes and should be resolved before declaring the entire system ready for release.

## Existing requests

Historical requests remain saved. If multiple historical requests cover the same office and year, Admin explicitly chooses **Set Official PPMP** for the correct existing record before it enters the new approval/consolidation workflow. This preserves the historical requests while enforcing one official PPMP for subsequent processing.
