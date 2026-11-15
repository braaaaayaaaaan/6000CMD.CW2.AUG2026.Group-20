# ManticAI – Digital Asset Management System

ManticAI is a shared digital asset management (DAM) system that allows users to securely upload, organise, search, preview and download digital assets.

Group Project 6: Bryan Tan Zhu Wei and Soh Angelina

[Watch the application demo](https://github.com/user-attachments/assets/47abe49b-b2b4-4367-8bbb-b8620ab0321e)

## 1. Application features

- Shared asset library, search, filtering and tags
- Image, video and 3D model previews
- File version management
- Secure file uploads and validation
- Email verification and multi-factor authentication (MFA)
- Role-based access control
- Security dashboard, alerts and audit logs

| Asset type | Supported formats |
| --- | --- |
| Images | JPG, JPEG, PNG |
| Videos | MP4 |
| 3D models | Self-contained GLB |

| Component | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, Chakra UI |
| Backend | Django 5.2, Django REST Framework |
| Database | PostgreSQL |
| Storage | Private local file storage |
| File validation | Pillow, FFprobe, Khronos glTF Validator |

## 2. First-time installation

Follow these steps if you have never downloaded or configured the project. No existing database, project files or accounts are required. You will create your own local database and administrator account.

### Step 1: Install the required software

| Software | Requirement | Download |
| --- | --- | --- |
| Git | Required | [Download](https://git-scm.com/downloads) |
| Python | 3.12 recommended | [Download](https://www.python.org/downloads/) |
| Node.js | 20.9.0 or newer, with npm | [Download](https://nodejs.org/) |
| PostgreSQL | Server and psql command-line tool | [Download](https://www.postgresql.org/download/) |
| FFmpeg | Including FFprobe | [Download](https://ffmpeg.org/download.html) |
| Authenticator app | Google Authenticator, Microsoft Authenticator or equivalent | Install on your phone |

You also need a working SMTP email account for verification and password reset emails.

Open Terminal (macOS/Linux) or PowerShell (Windows) and check your installations:

```bash
git --version
node --version
npm --version
psql --version
ffmpeg -version
ffprobe -version
```

Check Python on macOS/Linux with `python3.12 --version` or Windows with `py -3.12 --version`. On Windows, ensure PostgreSQL and FFmpeg are added to PATH. Restart the terminal after changing PATH.

### Step 2: Download the project

```bash
git clone https://github.com/braaaaayaaaaan/6000CMD.CW2.AUG2026.Group-20.git
cd 6000CMD.CW2.AUG2026.Group-20
```

Run all remaining commands from this project folder unless stated otherwise.

### Step 3: Install project dependencies

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
cd frontend
npm.cmd ci
cd ..
```

No additional Redis, Celery or separate worker service is required. The frontend dependencies are also needed for GLB validation.

For the remaining backend commands, Windows users should replace `python` with `.\.venv\Scripts\python.exe` unless they have activated the virtual environment.

### Step 4: Create the database

Start your local PostgreSQL server. Connect using the PostgreSQL administrator account:

```bash
psql -U postgres -d postgres
```

If your installation uses your operating system account, try `psql -d postgres` instead.

Inside PostgreSQL, run:

```sql
CREATE ROLE dam_app LOGIN;
\password dam_app
```

Enter a new password when prompted. Keep it for the next step.

Then run:

```sql
CREATE DATABASE dam_dev OWNER dam_app;
\q
```

This creates a fresh local database. Do not use an existing production database for this setup.

### Step 5: Configure the backend

Create a file named `.env` inside the `backend` folder using your text editor. Copy the following into it:

```dotenv
# Django configuration
DJANGO_SECRET_KEY=replace-with-generated-secret
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,[::1]

# Local database
DB_NAME=dam_dev
DB_USER=dam_app
DB_PASSWORD=replace-with-your-database-password
DB_HOST=127.0.0.1
DB_PORT=5432
DB_SSLMODE=disable

# Frontend connection
CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:3000
MEDIA_FRAME_ALLOWED_ORIGINS=http://127.0.0.1:3000
ACCOUNT_FRONTEND_URL=http://127.0.0.1:3000

# Local HTTP settings
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=Lax
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false

# Multi-factor authentication
MFA_ENCRYPTION_KEY=replace-with-generated-key
MFA_ISSUER=ManticAI

# Email configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=replace-with-smtp-host
EMAIL_PORT=587
EMAIL_HOST_USER=replace-with-email-address
EMAIL_HOST_PASSWORD=replace-with-smtp-password
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=
ACCOUNT_EMAIL_ASYNC=true
```

Generate the Django secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Copy the output into `DJANGO_SECRET_KEY`.

Generate the MFA encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output into `MFA_ENCRYPTION_KEY`.

Replace the remaining placeholders:

| Setting | Value |
| --- | --- |
| `DB_PASSWORD` | Password created in Step 4 |
| `EMAIL_HOST` | Your email provider's SMTP server |
| `EMAIL_HOST_USER` | Your sender email address |
| `EMAIL_HOST_PASSWORD` | Your SMTP credential or app password |

The example uses STARTTLS on port 587. If your provider uses implicit TLS, use its required port, set `EMAIL_USE_SSL=true` and `EMAIL_USE_TLS=false`.

Save the file. Never commit `.env` to GitHub. Keep the generated keys for future runs; replacing the MFA key prevents existing authenticator secrets from being decrypted.

### Step 6: Configure the frontend

Create a file named `.env.local` inside the `frontend` folder and paste:

```dotenv
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Your project should now contain these two configuration files:

```text
6000CMD.CW2.AUG2026.Group-20/
├── backend/
│   ├── .env
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   ├── .env.local
│   └── package.json
└── .venv/
```

### Step 7: Initialise the database

```bash
python backend/manage.py check
python backend/manage.py migrate
python backend/manage.py bootstrap_groups
```

These commands create the database tables and the Viewer, Editor and Admin roles.

### Step 8: Create an administrator account

```bash
python backend/manage.py createsuperuser
```

Follow the prompts. Use an email address you can access and a strong password of at least 12 characters.

### Step 9: Start the application

Open two terminals in the project folder. Keep both running.

**Terminal 1 – Backend (macOS/Linux)**

```bash
source .venv/bin/activate
python backend/manage.py runserver 127.0.0.1:8000
```

**Terminal 1 – Backend (Windows)**

```powershell
.\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8000
```

**Terminal 2 – Frontend (macOS/Linux)**

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

**Terminal 2 – Frontend (Windows)**

```powershell
cd frontend
npm.cmd run dev -- --hostname 127.0.0.1 --port 3000
```

### Step 10: Open the application

Open [http://127.0.0.1:3000/login](http://127.0.0.1:3000/login) in your browser.

1. Sign in using the administrator account created in Step 8.
2. Request email verification and follow the link sent to your inbox.
3. Confirm your password when prompted.
4. Scan the displayed QR code using your authenticator app.
5. Enter the six-digit authentication code.
6. Enter the application.

Email verification and MFA are mandatory for all accounts. The fresh database contains no sample assets. Upload a small valid PNG to try the library, then try an MP4 or GLB.

## 3. Using the application

### Application pages

| Page | Address |
| --- | --- |
| Login | [Open](http://127.0.0.1:3000/login) |
| Registration | [Open](http://127.0.0.1:3000/signup) |
| Asset library | [Open](http://127.0.0.1:3000/editor/home) |
| File uploads | [Open](http://127.0.0.1:3000/editor/uploads) |
| Security dashboard | [Open](http://127.0.0.1:3000/editor/security) |
| Django Admin | [Open](http://127.0.0.1:8000/admin/) |

### User roles

| Feature | Viewer | Editor | Admin |
| --- | --- | --- | --- |
| Browse, search, preview and download approved assets | Yes | Yes | Yes |
| Upload, replace, edit and delete assets | No | Yes | Yes |
| Manage tags | No | Yes | Yes |
| Security dashboard | No | No | Yes |
| Manage roles and approve assisted MFA recovery through the API | No | No | Yes |

New users register as Viewers. To change a user's role, sign in to Django Admin as the superuser, open Users and assign the appropriate application group. The user must sign in again.

### Uploading files

Uploaded files are placed in private quarantine before background validation. The possible processing statuses are:

- **Pending:** Waiting for processing.
- **Processing:** File validation is underway.
- **Ready:** File approved and available in the shared library.
- **Rejected:** File failed validation.
- **Error:** A processing problem occurred; this is not a successful rejection.

The maximum file size is 100 MiB. Images have a 25-million-pixel request limit, videos have a 3840 × 2160 edge limit (portrait supported), and GLB files must be self-contained.

## 4. Starting the application again

You do not need to repeat the installation or regenerate your keys.

Start PostgreSQL, open two terminals in the project folder and repeat Step 9. Visit [http://127.0.0.1:3000](http://127.0.0.1:3000).

Press `Ctrl+C` in both terminals to stop the application. After pulling updates, reinstall changed dependencies and review and apply new migrations as needed.

## 5. Security features

| Feature | Purpose |
| --- | --- |
| Email verification and MFA | Verifies email ownership and requires an authenticator code for login. |
| Account lockout | Temporarily restricts repeated failed authentication attempts. |
| Session management | Supports expiry, revocation and logout from all devices. |
| Role-based access | Restricts actions according to user permissions. |
| File validation and quarantine | Checks uploads before they enter the shared library. |
| Private storage and signed URLs | Restricts access to approved files. |
| SHA-256 hashing | Supports file integrity verification. |
| Audit logs and alerts | Records security events and detects suspicious activity. |

### Security monitoring

| Event | Threshold (per relevant username or user) | Severity |
| --- | --- | --- |
| Failed logins | 5 within 10 minutes | Medium |
| Successful download responses | 20 within 5 minutes | High |
| Relevant access denials | 5 within 10 minutes | Medium |

File validation does not provide antivirus scanning or guarantee detection of all malicious files. Automated file backups and an external tamper-proof audit logging service are not provided.

## 6. Testing

- [Manual file security testing](security_tests/README.md): fixture generation, independent verification and manual application checks.
- [OWASP ZAP testing](docs/owasp-zap.md): isolated SQLite database, synthetic accounts and captured emails. The launcher requires the `test/owasp-zap` branch and existing dependencies.

Additional backend regression checks (use the isolated test settings):

```bash
python backend/manage.py test user asset backend --settings=backend.test_settings --noinput
```

Frontend development checks:

```bash
cd frontend
npm run lint
npm run build
cd ..
```

Use `npm.cmd` on Windows if needed. These commands are available checks, not a claim that they were executed as part of the project evaluation.

## 7. Troubleshooting

| Problem | Solution |
| --- | --- |
| Command not found | Check software installation and PATH, then restart the terminal. |
| Database connection failed | Start PostgreSQL and check the database credentials. |
| Missing configuration | Check that `backend/.env` exists and placeholders are replaced. |
| Login or cookie error | Keep both servers running and use `127.0.0.1` consistently. |
| Verification email missing | Check SMTP credentials, TLS settings and spam folder. |
| MFA setup failed | Check the encryption key and authenticator device clock. |
| MP4 processing error | Check FFmpeg and FFprobe installation. |
| GLB processing error | Check Node.js and frontend dependencies. |
| GLB preview unavailable | Check internet access; the normal preview uses a CDN. |
| Account locked | Wait for the lockout period to expire. |
| Port already in use | Stop the conflicting process. |

Recover interrupted uploads:

```bash
python backend/manage.py cleanup_asset_files --process-uploads
```

Retry processing errors after correcting their cause:

```bash
python backend/manage.py cleanup_asset_files --process-uploads --retry-errors
```

Check stored files against recorded SHA-256 hashes:

```bash
python backend/manage.py verify_asset_files
```

## 8. Project structure

| Folder | Purpose |
| --- | --- |
| `frontend/` | User interface |
| `backend/` | API, database operations and private asset storage |
| `security_tests/` | Manual security testing kit |
| `scripts/` | Utility and testing scripts |
| `docs/` | Additional documentation |

PostgreSQL stores accounts, asset metadata, tags, versions and security logs. Uploaded files are stored separately in the backend's private storage. Supabase may provide PostgreSQL, but Supabase Storage is not used.

## 9. Deployment notes

This setup is for local development and demonstration only. Production requires HTTPS, secure cookies, independent secrets, dedicated database credentials, restricted private storage, production web servers and coordinated backups of the database and uploaded files. Do not use the local HTTP settings in production.
