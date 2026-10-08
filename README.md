# SHG Management & Financial Tracking System

React + Django REST Framework + SQLite (MySQL-ready). Replaces the per-group monthly Google Sheets.

## Quick start (Windows)

1. Unzip `shg-system.zip` to a normal folder such as `E:\shg-system` (not OneDrive, not Desktop).
2. Double-click **`setup.bat`**. It installs everything, creates the database, asks you to choose
   passwords for `admin` and `leader_amahoro`, and runs the tests. It must end with **SETUP COMPLETE**.
3. Double-click **`run.bat`**. The browser opens http://127.0.0.1:8000/admin/. Keep the black window open;
   close it (or press Ctrl+C) to stop the system.
4. Double-click **`frontend.bat`** for the leader screen at http://localhost:5173/ (needs `run.bat` open).
5. Double-click **`backup.bat`** any time to make a backup in the `backups` folder.

Running `setup.bat` again later is safe: it keeps `.env`, your accounts and your data,
backs up the database first, then applies updates.

Install first: Python (`winget install Python.Python.3.12`) and, for the leader screen,
Node.js (`winget install OpenJS.NodeJS.LTS`).

### Using it on a phone (same wifi)

1. Find your computer's IP: `ipconfig` -> IPv4 Address, e.g. `192.168.1.20`.
2. Add it to `backend\.env`: `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20`
3. Restart `run.bat`, then open `http://192.168.1.20:5173/` on the phone.

## Build steps

| Step | What | Status |
|---|---|---|
| 1 | Project setup, login (JWT), roles, groups, cycles, leaders, members, audit log | **Done** |
| 2 | Money API: weekly meeting sheet, shares, ingoboka, Mutuelle, loans, returns, interest, fines, reversals, month closing | **Done — tests pass on SQLite and MariaDB** |
| 3 | Dashboards and reports: member, group, all-groups; overdue loans; Excel/PDF export | Next |
| 4 | React frontend: login, meetings, leader weekly sheet (phone-first, Kinyarwanda + English) | **Done — browser-tested end to end** |
| 5 | Import the existing Google Sheets (Amahoro first) | |
| 6 | Year-end share-out screen, deployment | |

## Backend setup on Windows (PowerShell)

Requirements: Python 3.11–3.13. Database: **SQLite** (built into Python, nothing to install).

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env        # set DJANGO_SECRET_KEY

python manage.py migrate
python manage.py seed_demo --admin-password "Your-Admin-Pass-1" --leader-password "Your-Leader-Pass-1"
python manage.py test
python manage.py runserver
```

If `Activate.ps1` is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Generate a secret key:
```powershell
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

- Django admin: http://127.0.0.1:8000/admin/ (user `admin`)
- API: http://127.0.0.1:8000/api/

### Where the data lives

```
shg-system/
├── backend/     ← code (safe to replace or re-clone)
├── data/        ← shg_system.sqlite3  (THE RECORDS — never delete)
└── backups/     ← daily verified copies
```

On a server, set `SQLITE_PATH` and `BACKUP_DIR` in `.env` to a folder outside the code,
e.g. `C:\shg-data\shg_system.sqlite3`. Never copy the `.sqlite3` file by hand while the
server is running; use `backup_db`.

### SQLite settings already applied

- **WAL mode**: people can read while someone saves.
- **busy_timeout 20 s** + **IMMEDIATE transactions**: when two leaders save at the same moment,
  one waits instead of failing. Tested: 13 simultaneous writers, 260 saves, 0 errors.
- **foreign_keys ON**.

### Backups

```powershell
python manage.py backup_db
```

Makes a live-safe copy, checks it with `PRAGMA integrity_check`, keeps the newest 30.

Schedule it daily (run PowerShell as the user who runs the system; adjust the path):

```powershell
$py  = "C:\path\to\shg-system\backend\.venv\Scripts\python.exe"
$dir = "C:\path\to\shg-system\backend"
$action  = New-ScheduledTaskAction -Execute $py -Argument "manage.py backup_db" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 9pm
Register-ScheduledTask -TaskName "SHG daily backup" -Action $action -Trigger $trigger
```

Also copy the `backups` folder somewhere off the machine (Google Drive, USB) at least weekly.
A backup on the same disk does not survive a dead or stolen laptop.

**Restore:** stop the server → delete `shg_system.sqlite3`, `shg_system.sqlite3-wal` and
`shg_system.sqlite3-shm` in `data/` → copy the chosen backup to `data/shg_system.sqlite3` → start the server.

### Moving to MySQL later

```powershell
pip install -r requirements-mysql.txt
```
Set `DB_ENGINE=mysql` and the `DB_*` values in `.env`, then `python manage.py migrate`.
No code changes. Run the tests on MySQL before any release; MySQL catches type
errors SQLite silently accepts (two real bugs were found this way in step 1).

### Try the API from PowerShell

```powershell
$login = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/auth/login/ `
  -ContentType "application/json" `
  -Body '{"username":"leader_amahoro","password":"Your-Leader-Pass-1"}'
$h = @{ Authorization = "Bearer $($login.access)" }

Invoke-RestMethod http://127.0.0.1:8000/api/members/ -Headers $h

Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/members/ -Headers $h `
  -ContentType "application/json" `
  -Body '{"shg":1,"first_name":"Christine","last_name":"Kabeho","gender":"F"}'
```

## API (step 1)

| Method | URL | Who |
|---|---|---|
| POST | `/api/auth/login/` | anyone → `access`, `refresh`, `user` (role, groups led) |
| POST | `/api/auth/refresh/` | logged in |
| GET | `/api/auth/me/` | logged in |
| POST | `/api/auth/change-password/` | logged in |
| GET/POST/PATCH | `/api/users/` | admin |
| GET | `/api/shgs/` | all (leaders: own group only) |
| POST/PATCH | `/api/shgs/` | admin |
| GET | `/api/cycles/` · POST/PATCH admin | |
| GET | `/api/leader-assignments/?active=true` · POST/PATCH admin | |
| POST | `/api/leader-assignments/{id}/end/` | admin — end before assigning a new leader |
| GET/POST/PATCH | `/api/members/?search=&shg=&status=` | admin, leader (own group); viewer read-only |
| GET | `/api/audit-logs/` | admin |

There is no DELETE anywhere: archive a group or change a member's status instead.


## API (step 2 — money)

| Method | URL | Who |
|---|---|---|
| GET/POST | `/api/meetings/?shg=` | leader (own group), admin. Cycle is set automatically from the date |
| GET | `/api/meetings/{id}/sheet/` | every active member (plus anyone with an open loan): recorded this meeting, totals to date, open loans, unpaid fines |
| POST | `/api/meetings/{id}/sheet/` | save the whole sheet at once — all rows or nothing |
| GET | `/api/loans/?status=open\|overdue\|paid\|cancelled&member=` | balances and status are calculated |
| GET | `/api/loans/?late_fine_missing=true` | overdue loans with no late-loan fine recorded |
| POST | `/api/loans/` | give a loan `{member, principal, meeting?, purpose?}`; admin adds `over_limit_reason` to approve above the limit |
| POST | `/api/loans/{id}/cancel/` | admin, only if nothing was paid |
| GET/POST | `/api/fines/?unpaid=true` · POST `/api/fines/{id}/cancel/` | |
| GET | `/api/transactions/?member=&type=&date_from=&date_to=` | the ledger |
| POST | `/api/transactions/` | only `EXPENSE` or `INGOBOKA_OUT` |
| POST | `/api/transactions/{id}/reverse/` `{reason}` | correct a mistake (leader own group, admin) |
| GET | `/api/members/{id}/summary/` | member dashboard + how much they can borrow |
| GET/POST | `/api/period-closings/` | admin closes a month |

### Weekly sheet body

```json
{
  "submission_id": "5b2c9a0e-8f1d-4a57-9b1e-2f3d4c5e6a7b",
  "rows": [
    {"member": 1, "present": true, "shares": 10, "ingoboka": 100, "mutuelle": 500,
     "loan_payments": [{"loan": 4, "returned": 20000, "interest": 1400}],
     "fine_payments": [{"fine": 2, "amount": 100}],
     "new_fines": [{"reason": "LATE_TO_MEETING", "amount": 100, "paid_now": true}]}
  ]
}
```

- Send share **count**; the server calculates `count × 500`.
- Amounts are **added** to what is already recorded for that meeting.
- `submission_id` is created once by the app per Save. Sending the same id again (double tap, slow network) returns the first result and records nothing twice.
- If any row is wrong, nothing is saved and the response lists errors by row number: `{"rows": {"1": {"loan_payments": ["amount: Only 10,000 RWF is still owed on this loan."]}}}`


## Leader screen (step 4)

Phone-first React app in `frontend/`. Every label is Kinyarwanda with English beside it:
**Imigabane (Shares)**, **Ingoboka (Social fund)**, **Mituweli (Mutuelle)**, **Inguzanyo (Loan)**,
**Ayishyuwe (Returned)**, **Inyungu (Interest)**, **Ibihano (Fine)**.

| Screen | What it does |
|---|---|
| Injira (Log in) | Username and password; the leader's group is remembered |
| Inteko (Meetings) | List of meetings, and one field to start today's meeting |
| Weekly sheet | Every active member in one list; tap a member to fill in their week |

On the sheet the leader can:

- fill Ingoboka 100 and Mituweli 500 for everyone with one tap, then change the exceptions
- type the **number of shares**; the screen shows `10 x 500 = 5,000 RWF` and the server calculates the amount
- record money returned and interest against each open loan, with the amount still owed and the due date shown
- pay an unpaid fine, or add a new fine and mark it paid on the spot
- give a loan without leaving the screen
- mark Yaje (Present) / Ntiyaje (Absent)
- see the running totals at the bottom and press **Bika (Save)** once for the whole meeting

If a row is wrong, nothing is saved: that member turns red with the reason under their name
(for example "Only 20,000 RWF is still owed on this loan").

Development: `frontend.bat` runs Vite on port 5173 and passes `/api` calls to Django on port 8000.


### Livelihood menu and group pages (step 4b)

- Left menu **LIVELIHOOD** lists the groups. Admin sees every group and can add one with
  **+ Itsinda rishya (New group)**: the code (SHG002, SHG003...) and this year's savings cycle are created automatically.
  Leaders see only their own group.
- Each group has two tabs: **Inteko (Meetings)** and **Abanyamuryango (Members)**.
- **Members tab:** paste or type many members at once, one per line: `KABEHO Christine, 0788123456`.
  A first word in CAPITALS is the surname; otherwise the last word is. Check the preview, then **Bika (Save)**.
- **Weekly sheet** is a table like the Google Sheet: one row per member, columns
  Yaje | Imigabane | Ingoboka | Mituweli | Ibihano | Ayishyuwe | Inyungu | Asigaye | Inguzanyo nshya, with totals at the bottom.
  A green `+500` under a box is what is already saved for that meeting; what you type is added to it.
  Fine money first pays any old unpaid fine, then the rest is today's fine.
  New loans are given after the contributions are saved.
- API: `POST /api/members/bulk/ {shg, members:[{first_name, last_name, phone}]}` (all or nothing);
  `POST /api/shgs/ {name}` (admin); lists accept `?page_size=` up to 500.

## Rules enforced on the server

- A leader only ever receives rows from groups with an active leader assignment. Other groups' records return **404**, and writing to them returns **403**.
- Only an admin can move a member to another group.
- Every create and update is written to the audit log with old and new values.
- Money entries can never be edited or deleted; corrections are reversal entries.
- Loan limit = member's shares × 500 × the cycle's multiplier, and never more than the group's lendable cash.

## Still to confirm with the groups (defaults in `Cycle`)

| Setting | Default |
|---|---|
| `loan_multiplier` | 1× |
| `fines_in_profit` | yes |
| Ingoboka / Mutuelle money can be lent | no (`Cycle.lendable_cash`) |
