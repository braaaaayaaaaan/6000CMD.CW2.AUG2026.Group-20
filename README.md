# digital-asset-management
Digital Asset Management System

Group Project 6
- Bryan Tan Zhu Wei
- Soh Angelina

Digital Asset Management System
A full-stack digital asset management (DAM) platform built with Next.js, Chakra UI, Django REST Framework, and PostgreSQL.

https://github.com/user-attachments/assets/47abe49b-b2b4-4367-8bbb-b8620ab0321e

Technology Stack
Frontend
- Next.js
- Chakra UI (see frontend/package.json)

Project Structure
/frontend       → Next.js + Chakra UI app  
/backend        → Django + DRF API

Backend
- Django + Django REST Framework + SimpleJWT
- PostgreSQL (local or Supabase-hosted)

Frontend (in a second PowerShell terminal, from the repository root):

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

Open http://localhost:3000. The Django API remains http://127.0.0.1:8000.
Django authentication and local backend/media uploads are retained.

## Account security setup

Install backend dependencies with `python -m pip install -r backend/requirements.txt`.
Review `backend/.env.example` and set the SMTP, frontend-origin, cookie, and MFA
encryption settings in your local environment. Actual application delivery uses
Django's SMTP backend, and security events omit tokens, seeds, and recovery codes. SMTP credentials and the Fernet
key must stay outside Git. Back up the encryption key: replacing it without
re-encrypting existing seeds makes their authenticators unavailable.

After reviewing the additive migration, run `python backend/manage.py migrate`
against the intended development database. The implementation does not apply this
migration automatically. Existing accounts start **unverified** and old JWT/Django
sessions stop working. Use `/verify-email` to request verification. Legacy accounts
with missing or duplicate addresses need an operator to correct those addresses
before verification; the migration does not delete accounts or rewrite email data.

The shared library remains available to verified accounts. There is no approval
queue. `ACCOUNT_ALLOWED_EMAIL_DOMAINS` optionally restricts registration and access
to exact domains; leaving it empty permits any verified address.

Application roles use Viewer, Editor, and Admin groups. The new Admin group is
created without changing existing memberships. Staff status alone does not grant
application administrative permissions. Superusers remain application admins.
Django Admin still requires staff status and its existing model permissions.
Manage application roles through Django groups or `PATCH /users/<uuid>/role/`
with `{"role":"Viewer|Editor|Admin"}`. Application admins can separately update
activation through `PATCH /users/<uuid>/status/` with `{"is_active":false}`.
Role/security changes invalidate existing credentials and require sign-in again.

All accounts (Viewer, Editor, Admin, staff, and superusers) require TOTP.
Email verification leads directly to QR enrolment in a TOTP-compatible app.
The user confirms their account password and the app's current six-digit code
before receiving authenticated cookies. Returning users enter their password and
current authenticator code. Legacy `MFA_REQUIRED_ROLES` values cannot relax this policy.
No recovery-code lists are generated or displayed. Authenticator security cannot
be disabled. Losing access to the authenticator requires trusted operator assistance;
password-reset email never bypasses MFA. Previously issued recovery codes remain
accepted by the API for compatibility until the authenticator is replaced.
For five minutes after a completed MFA sign-in, password reauthentication can start
replacement without another old code. The new authenticator still requires its
own code confirmation.

JWTs are stored in host-only HttpOnly cookies, with explicit CSRF checks on unsafe
cookie requests, login, refresh, and recovery endpoints. Legacy localStorage
credentials are removed on browser startup. Use matching hostnames for the frontend
and API: `localhost` for both or `127.0.0.1` for both. For another API address set
`NEXT_PUBLIC_API_URL` before building the frontend. Configure exact CORS and CSRF
origins. Production requires HTTPS and Secure cookies; cross-site cookie deployments
additionally need SameSite=None and browser support for those cookies.

Default expiry: access 15 minutes, refresh/login 24 hours absolute, Django Admin
session at most 12 hours, MFA challenge 5 minutes, verification 24 hours, reset
30 minutes. Explicit environment settings override configurable lifetimes; the
existing local 40-minute access setting is retained. Refresh rotation does not
extend the absolute login lifetime. Logout revokes the current login immediately;
Password & Security also offers logout from all devices.

Account login/MFA lockouts use database rows and work across workers. IP and email
request limits use Django's cache. An existing shared cache can be configured with
`AUTH_CACHE_BACKEND` and `AUTH_CACHE_LOCATION`; the default memory cache has
per-process IP counters. Set `AUTH_NUM_PROXIES` only for a trusted proxy that removes
untrusted forwarding headers. No Redis service is required by this implementation.

Email uses a small bounded background queue so public password-recovery responses
do not wait for account-dependent SMTP delivery. It is not a durable delivery queue:
process failure can lose pending messages; users can request another email. Monitor
the token-free delivery-failure events. Use a durable mail worker if production
delivery guarantees are needed. Gmail uses `smtp.gmail.com`, port 587, STARTTLS
(`EMAIL_USE_TLS=true`, `EMAIL_USE_SSL=false`). Set `EMAIL_HOST_USER` to the complete
sending address and `EMAIL_HOST_PASSWORD` to its Google App Password in the ignored
local `.env`. Google requires 2-Step Verification for App Passwords. An empty
`DEFAULT_FROM_EMAIL` uses the authenticated sending address. Keep
`ACCOUNT_EMAIL_ASYNC=true`. Console/file/in-memory delivery is not used for actual
application workflows; the isolated regression tests retain a memory email backend
so they never send real messages. SMTP acceptance alone does not prove inbox receipt.

Run safe regression checks without reading `.env` or connecting to Supabase:

```powershell
python backend/manage.py test user asset backend --settings=backend.test_settings --noinput
python backend/manage.py makemigrations --check --dry-run --settings=backend.test_settings
```

The tests use an in-memory SQLite database and a memory email backend. Production
PostgreSQL concurrency and actual SMTP/browser flows still need deployment testing.
