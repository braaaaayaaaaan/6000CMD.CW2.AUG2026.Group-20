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

Open http://127.0.0.1:3000. The Django API remains http://127.0.0.1:8000.
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
Email verification leads to password confirmation, followed by QR enrolment in a
TOTP-compatible app. A QR code or setup key is never disclosed using email proof
alone. Pending setup keys are invalidated when the sign-in challenge changes.
The user confirms the app's current six-digit code before receiving authenticated
cookies. Returning users enter their password and
current authenticator code. Legacy `MFA_REQUIRED_ROLES` values cannot relax this policy.
No recovery-code lists are generated or displayed. Authenticator security cannot
be disabled. Losing access to the authenticator requires trusted operator assistance;
password-reset email never bypasses MFA. Previously issued recovery codes remain
accepted by the API for compatibility until the authenticator is replaced.
For five minutes after a completed MFA sign-in, password reauthentication can start
replacement without another old code. The new authenticator still requires its
own code confirmation.

### Administrator-assisted authenticator recovery

An application Admin must verify the requester's identity outside the application
before approving recovery. For this university deployment, use a live check of the
requester's university identity against an independently held group/module roster,
with the responsible group supervisor resolving any uncertainty. Confirm the exact
account using existing trusted records. Email access, knowledge of a username, or
a password-reset email alone is insufficient. Do not approve unverifiable requests
or retain copies of identity documents in application logs.

After this check, a separate Admin signs in with their own password and MFA and,
within five minutes, submits the following authenticated, CSRF-protected request
using the application's existing API client:

```text
POST /users/<verified-account-uuid>/recover-mfa/
{"identity_verified": true, "current_password": "<operator password entered privately>"}
```

`identity_verified` records the operator's approval; it is not automated identity
proof. Do not put passwords in URLs, shell history, tickets or logs. The action
does not support self-recovery. Staff/superuser accounts require a separate
superuser operator. If no eligible operator can authenticate, escalate to the
trusted deployment owner; there is no public MFA bypass or recovery backdoor.

Approval clears active/pending authenticator secrets and legacy recovery hashes,
invalidates outstanding challenges and all login sessions, and emits the existing
`mfa_recovery_approved` audit event with actor and target IDs. It preserves the
password, email verification and application role. The requester then signs in
with their password and must enrol and confirm a new authenticator before access.
Previously issued recovery codes can also be entered through the login recovery
code option or the authenticator replacement field; no new codes are generated.

Login usernames are immutable through the profile API. Password/email changes
require the current password and share account failure tracking and lockouts;
successful password verification clears failures. Profile/recovery operations
also have a scoped rate limit. Password fields preserve surrounding whitespace
consistently across registration, login, reset and profile changes.

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

## Manual security testing kit

See [security_tests/README.md](security_tests/README.md) for reproducible image,
MP4 and GLB fixture generators, local verification scripts, and the combined manual
file validation checklist. The scripts prepare inputs; application checks are
performed manually using the README instructions.

## Private asset storage and recovery

New asset files live on the Django host under `DJANGO_ASSET_PRIVATE_ROOT` (default:
`backend/private_assets`), in private `quarantine` and `approved` directories.
`DJANGO_MEDIA_ROOT` retains the legacy uploads location for explicit recovery.
Asset/version/tag metadata lives in PostgreSQL, including
Supabase when configured. This is local private storage, not Supabase Storage.
There is no configured file backup service in this repository.

Only `/media/assets/<uuid>/?token=...` serves files. Both issuing and redeeming a
link require a currently authenticated, verified, MFA-complete account. A link is
bound to its issuing user, original live login session, asset/version and stored
file digest; another login belonging to the same user may redeem it only while that
original session remains valid. Expiry, logout, deactivation, credential/role
revocation, deletion and changes to the bound file invalidate access. GET, HEAD, downloads
and Range requests use the same checks. Viewer/Editor/Admin retain shared-library
read access; only Editor/Admin can upload or replace files. Uploads start in
quarantine and receive links only after successful processing and approval.
Pending/error uploads remain visible to their uploader and application admins;
the shared library contains approved versions. Replacements create a new immutable
version, preserving approved historical versions and their valid links.

New uploads and replacement versions automatically queue validation after their
database transaction commits. Each backend process runs up to two checks in the
background. Run `python backend/manage.py cleanup_asset_files --process-uploads`
to recover pending uploads after a backend restart. Image checks run in an
isolated Pillow process; video checks
require FFprobe and GLB checks require Node and the frontend's `gltf-validator`
package. Failed validation rejects the file; operational failures leave an error
that an operator can retry with `--process-uploads --retry-errors`.
For legacy files, inspect `cleanup_asset_files --quarantine-existing` first and
use `--quarantine-existing --apply` to relocate them for processing.

Image/video elements and model-viewer send credentials. Use matching hostnames,
exact credentialed CORS origins, and HTTPS/Secure cookies in production. Native
downloads use authenticated browser navigation. Cross-site deployments additionally
depend on SameSite settings and browser third-party-cookie policy. URLs can be
refreshed through the authenticated `media-url` endpoint when expired.

Never add a web-server `/media/` alias or Django debug static-media route. Keep
both storage roots outside Next.js `public`, static roots and any web-server document root;
the application rejects overlap with its known static/public directories. Restrict
filesystem access to the service account. Private storage rejects traversal,
out-of-root symlinks and public `.url()` access. Uploads receive random filenames.
Configure reverse-proxy/process-manager access logs to record paths **without
query strings** (for example Nginx `$uri`, not `$request_uri`). Django's configured
request/server logs redact signed `token` parameters; audit events contain IDs,
not tokens or filesystem paths. Run production with DEBUG disabled.

Uploads/replacements share extension/content, byte-size and multipart checks.
Pillow verifies and decodes JPG/PNG with a pixel limit. MP4 checks bounded container
structure and self-contained data references, not full codec decodability. GLB
checks container lengths, JSON/buffer bounds and rejects URI/URL references,
including data URIs: export self-contained binary GLBs with embedded buffer-view
textures. Legacy GLB/MP4 containers receive resource checks at redemption too. These controls
are not antivirus scanning or complete MP4/glTF semantic validation.

`asset.0012_asset_sha256` adds one optional 64-character digest field.
`asset.0012_upload_processing` adds processing metadata and private storage;
`asset.0013_merge_sha256_upload_processing` joins both migration histories.
Review and apply the migrations before running against an existing database.
The digest migration does not rewrite existing records/files; legacy digests remain blank. New uploads
are hashed with SHA-256 and the stored copy is checked before committing metadata.
Promotion checks the approved copy against the same trusted digest.
Replacement uploads receive their own digest; historical versions retain their own.
Downloads do not repeatedly hash large files. Run `python backend/manage.py
verify_asset_files` after a restore or suspected storage incident. This read-only
command exits unsuccessfully for missing files, mismatches or absent legacy
baselines; it does not silently backfill a potentially compromised file. On a
mismatch, pause asset serving, investigate, and restore a trusted copy or upload a
validated replacement before reopening access. Hashing detects changes against a
trusted baseline; it does not prove safety or protect a compromised database.

For stale file references, run `python backend/manage.py repair_asset_paths` to
preview recovery matches in private storage and legacy `uploads/`. Run it with
`--apply` to repair references, then run `verify_asset_files`. Recovery requires an
exact match to each asset's recorded SHA-256. Recovered quarantine or legacy files
must pass `cleanup_asset_files --process-uploads` before preview or download;
already approved private files retain their approval. Refresh the library page
afterward to obtain new signed URLs.

Back up PostgreSQL metadata **and** the private asset and legacy media directories as a
coordinated set. Pause writes while taking the database snapshot/export and file
snapshot (or use coordinated storage snapshots). Record the application/migration
version, encrypt backups and keep a separate copy with restricted access. Back up
required configuration/encryption secrets separately. Supabase database backups do
not include this host's local uploads. Restore into an isolated environment first,
using matching metadata and files; run integrity verification and check image,
video, GLB and historical-version access before reopening writes. Database-only
restoration produces missing-file references; file-only restoration leaves orphaned
or missing metadata. Do not run orphan deletion until the restore is reconciled.

## Security monitoring and auditing

Administrators have **Security Dashboard** alongside Assets and Tag Management at
`/editor/security`. Overview shows the last 24 hours by default, with 7 and 30 day
options. Open Security Alerts counts all unresolved alerts, regardless of age.
Security Alerts and Audit Logs have server filters, 40 row pagination and detail
dialogs. Resolving an alert records the operator and time and creates one audit
event. This never changes user access. Existing account lockouts remain independent
of monitoring rules.

The existing `user.security.event` entry point now writes selected events into
`user.AuditEvent` and emits the existing safe `dam.audit` console entry. The former
generic write-request logger is replaced with request context for meaningful
events. Django Admin's existing LogEntry remains intact and projects selected
account, permission, asset and tag changes into the same audit stream. Bulk admin
deletions are supported. REST actions do not also create Django Admin LogEntry
records, so these hooks do not double-log the same action. Direct SQL and arbitrary
ORM scripts outside these application and admin hooks are not monitored.

Events cover completed login, failed password sign in, logout, MFA verification,
account creation and security changes, roles and admin permissions, asset upload,
replacement, metadata changes, deletion, download and preview, meaningful
authenticated access denials, tag changes and alert resolution. Failed sign in
records retain a validated NFKC username using the existing case-sensitive login
mechanism. Audit records retain the actor's UUID if the account is later deleted.
IP context uses validated `REMOTE_ADDR`, never untrusted forwarding headers. A
proxy deployment can therefore report its proxy address. No request bodies,
cookies, auth headers, credentials, signed URLs or admin change-message text are
copied. Metadata is selected through a typed allowlist.

File events are recorded only after authentication, signed-link/session/file
binding checks, private-file opening and response construction succeed. Each
explicit attachment GET returning 200 or 206 counts as a download, including
repeated downloads of one asset and successful Range requests. HEAD requests,
link issuance, missing files, rejected links and invalid ranges do not count.
Inline preview GETs have a separate informational event and do not trigger bulk
download alerts. A successful server response indicates authorised delivery has
started, not proof that a client saved every byte.

`user/auditing.py` centrally defines the three synchronous rules. Five failed
logins for one attempted username within ten minutes create a Medium alert.
Twenty successful download responses for one user within five minutes create a
High alert. Five relevant access denials for one user within ten minutes create a
Medium alert. Detection counts use rolling windows. Deduplication uses fixed UTC
buckets of the corresponding window length, with a database uniqueness constraint
on rule, hashed subject and bucket start. Further qualifying events update the
rolling count and most recent occurrence on that alert, even if it was resolved
early. A new bucket permits a new alert. PostgreSQL transaction advisory locks
serialize relevant event creation and counting for the same rule and subject.
No worker service or new dependency is needed.

All monitoring endpoints use the application's revocable JWT/cookie and verified
session authentication, application Admin permission and no-store responses:

- `GET /api/security/overview/?hours=24` with 24, 168 or 720 hours
- `GET /api/security/alerts/` and `GET /api/security/alerts/{id}/`
- `POST /api/security/alerts/{id}/resolve/` with existing cookie CSRF protection
- `GET /api/security/audit-events/` and `GET /api/security/audit-events/{id}/`

Lists use existing `count`, `next`, `previous`, `results` pagination. Both accept
`search`, `severity`, `user` UUID, `start` and `end` ISO timestamps. Alerts also
accept `alert_type` and `status`. Audit events also accept `event_type`, `category`,
`outcome`, `resource_type` and `resource`. Audit search includes username, attempted
identifier, event type and resource identifier. Alert date filters use the most
recent detection. Audit dates use the event timestamp. The dashboard uses the
existing Chakra blue and white theme, session/resource hooks and pagination.
The activity bars and accessible counts table use no charting dependency.

**Database migration status.**
`user.0005_security_monitoring` creates AuditEvent and SecurityAlert with indexes
and the deduplication constraint. It depends on `user.0004` and does not rewrite
existing data. It was applied to the configured Supabase database on 13 November
2026 after explicit approval. Other deployments must apply this migration before
using the feature. Existing console history is not imported. Isolated tests apply
migrations only to a disposable SQLite database.
Deployment still needs PostgreSQL concurrency verification and an audit retention
and backup policy. These records are not an external tamper-proof log service.

Run the monitoring and full regression suites without deployment credentials:

```powershell
.\.venv\Scripts\python.exe backend/manage.py test user.test_monitoring --settings=backend.test_settings --noinput
.\.venv\Scripts\python.exe backend/manage.py test user asset backend --settings=backend.test_settings --noinput
.\.venv\Scripts\python.exe backend/manage.py makemigrations --check --dry-run --settings=backend.test_settings
cd frontend
npm.cmd run lint
npm.cmd run build
```
