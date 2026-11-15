# DAM File Validation Testing Kit

This guide explains how to generate sample files and manually test the ManticAI application's file security controls. It includes valid and deliberately malformed images, videos and 3D models.

The scripts generate and verify sample files only. They do not upload files, test the running application or perform security scans.

## 1. First-time setup

### Step 1: Install the required software

| Software | Requirement |
| --- | --- |
| Git | Download the project |
| Python | 3.12 recommended |
| Node.js | 20.9.0 or newer, with npm |
| FFmpeg and FFprobe | Generate and verify videos; both must be on PATH |
| Bash | Included on macOS/Linux; use Git Bash or WSL on Windows |

If you already installed the application using the [main README](../README.md), skip cloning and dependency installation.

### Step 2: Download the project

```bash
git clone https://github.com/braaaaayaaaaan/6000CMD.CW2.AUG2026.Group-20.git
cd 6000CMD.CW2.AUG2026.Group-20
```

Run all subsequent commands from the project root unless stated otherwise.

### Step 3: Install dependencies

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
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
cd frontend
npm.cmd ci
cd ..
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` instead of `python` for Python commands. The frontend dependencies include the Khronos GLB validator required for verification.

Check your installation:

```bash
python --version
node --version
ffmpeg -version
ffprobe -version
```

You do **not** need a database, SMTP account or running application to generate the sample files. These are needed only for normal manual application testing.

## 2. Generate and verify the test files

### macOS / Linux

```bash
source .venv/bin/activate
python security_tests/make_dam_images_glb.py
PYTHON=python bash security_tests/make_dam_videos.sh
python security_tests/verify_fixtures.py
```

### Windows (Git Bash)

Open Git Bash in the project root after installing the Windows dependencies above:

```bash
source .venv/Scripts/activate
python security_tests/make_dam_images_glb.py
PYTHON=python bash security_tests/make_dam_videos.sh
python security_tests/verify_fixtures.py
```

If using WSL instead, install the Linux dependencies and create a separate Linux virtual environment. Do not reuse the Windows virtual environment in WSL.

| Script | Purpose |
| --- | --- |
| `make_dam_images_glb.py` | Generates seven images, four GLB models and an initial manifest. |
| `make_dam_videos.sh` | Generates four MP4 videos and checks them using FFprobe. |
| `verify_fixtures.py` | Checks the samples, runs Khronos GLB validation, calculates SHA-256 checksums and updates the manifest. |

The files and verification reports are saved in `security_tests/generated/`. The `generated/` and `evidence/` folders are ignored by Git.

Resolve any failed commands before proceeding. Running the scripts again overwrites named samples and verification reports, so save existing evidence first. Record tool versions and actual checksums because outputs may vary across versions.

### Optional verification commands

Verify images and GLBs before generating videos:

```bash
python security_tests/verify_fixtures.py --skip-videos
```

Run only the Khronos GLB checks:

```bash
node security_tests/verify_glbs.cjs
```

The `--skip-khronos` option is available for preliminary checks, but full verification must run without skip flags.

To use a different output folder (Bash), pass the same folder to every script:

```bash
python security_tests/make_dam_images_glb.py --output ./dam-security-inputs
PYTHON=python bash security_tests/make_dam_videos.sh ./dam-security-inputs
python security_tests/verify_fixtures.py --output ./dam-security-inputs
```

## 3. Understand the special test files

| File or technique | Purpose |
| --- | --- |
| `IMG06_overpixels.png` | Valid 6000 × 5000 PNG (30 million pixels), below 1 MiB. Tests the 25-million-pixel limit independently of file size. |
| `IMG05_corrupted.png` | Altered zlib checksum with rebuilt PNG chunk CRCs. Pillow `verify()` should pass but full `load()` should fail. |
| `GLB03_external.glb` | Contains a metadata URI that does not fetch a resource. Tests the application's stricter URI restrictions, even though Khronos should accept the format. |
| `GLB02_broken.glb` | Contains structural errors that Khronos should detect. |
| `GLB04_invalid_accessor.glb` | Contains a NaN value; Khronos should report `ACCESSOR_INVALID_FLOAT`. |

Khronos JSON reports are saved beside the GLB files. Expect zero errors for GLB01 and GLB03, and errors for GLB02 and GLB04. These are fixture expectations, not application test results.

## 4. Prepare the application for testing

1. Follow the [main README](../README.md) to start a separate local test instance with a fresh database and separate private/media storage. Alternatively, follow the [isolated ZAP guide](../docs/owasp-zap.md) on the `test/owasp-zap` branch for SQLite, synthetic accounts and captured emails.
2. Prepare Admin, Editor and Viewer accounts. Complete email verification and MFA for each.
3. Ensure the backend can access FFprobe, Node.js and the Khronos validator.
4. Open `http://127.0.0.1:3000/login` for the normal local setup and sign in as an Editor for the media tests.
5. Prepare a place to record actual results, screenshots and Pass / Fail / Blocked outcomes.

### API requests

Some tests require direct API requests rather than the interface.

| Action | Endpoint | Multipart fields |
| --- | --- | --- |
| Upload | `POST /assets/` | `name`, `description`, `url` |
| Replace | `PATCH /assets/<id>/` | `url` containing the replacement file |

A metadata-only edit does not create a new version. Use the browser developer tools Network panel to inspect successful requests, then adapt them in an API client with the normal session and CSRF handling. Never include cookies, access tokens or signed media URLs in shared evidence.

## 5. Manual test cases

### Part A: Media upload validation (01–14)

Upload each file as an Editor. Record the HTTP response, asset/version ID if created, final processing status and evidence.

| ID | File | Expected result |
| --- | --- | --- |
| 01 | `IMG01_valid.jpg` | Accepted; becomes Ready. |
| 02 | `IMG02_valid.jpeg` | Accepted; becomes Ready. |
| 03 | `IMG03_valid.png` | Accepted; becomes Ready. |
| 04 | `IMG04_fake.png` | HTTP 400; no asset or version created. |
| 05 | `IMG05_corrupted.png` | Accepted into quarantine, then rejected by the worker; never Ready. |
| 06 | `IMG06_overpixels.png` | HTTP 400 before asset/version creation; exceeds 25 million pixels. |
| 07 | `VID01_valid.mp4` | Accepted; becomes Ready. |
| 08 | `VID02_fake.mp4` | HTTP 400; no asset or version created. |
| 09 | `VID03_broken.mp4` | HTTP 400; no asset or version created. |
| 10 | `VID04_over4k.mp4` | Accepted into quarantine, then rejected by the worker for excessive resolution. |
| 11 | `GLB01_valid.glb` | Accepted; becomes Ready. Retain zero-error Khronos report. |
| 12 | `GLB02_broken.glb` | HTTP 400; no asset or version created. |
| 13 | `GLB03_external.glb` | HTTP 400 due to the application's URI policy, regardless of Khronos format validation. |
| 14 | `GLB04_invalid_accessor.glb` | Rejected by the worker. Retain report showing `ACCESSOR_INVALID_FLOAT`. |

Ready corresponds to the backend status `approved`. Some valid files progress through Pending and Processing too quickly to observe; use API metadata and processing details instead. For every HTTP 400 case, confirm that no new asset/version exists. A request-time rejection does not prove the worker inspected the file. Missing dependencies, timeouts and worker `error` statuses are operational failures, not successful security rejections.

### Part B: Upload and delivery security (15–20)

#### Test 15: MIME Type Spoofing

**Purpose:** Check whether the backend trusts the file's actual contents rather than the MIME type declared by the uploader.

Perform two authenticated multipart uploads:

1. Upload the real `IMG03_valid.png`, but declare the file part as `text/plain`. **Expected:** The file is accepted and becomes Ready.

2. Upload the text-based `IMG04_fake.png`, but declare the file part as `image/png`. **Expected:** HTTP 400, with no asset created.

Change only the **file part's MIME type**, not the overall multipart request's `Content-Type` or boundary. Record both responses separately.

#### Test 16: Upload Size Limit

**Purpose:** Confirm that the backend enforces the configured maximum upload size.

1. Set `ASSET_UPLOAD_MAX_MB=1` in the disposable backend and restart it.

2. Upload `SHR01_over1MiB.png`. It is a valid 800 × 800 PNG, so this checks bytes rather than the pixel ceiling.

3. **Expected:** HTTP 400, with no new asset created.

4. Record the file's actual byte count and restore the original setting.

This case requires the separately configured instance described above; an unchanged ZAP instance keeps its own upload limit. In your report, clearly state that you tested a **reduced 1 MiB limit**. Testing the default **100 MiB** boundary requires a separate, valid, larger file.

#### Test 17: Upload Permissions by User Role

**Purpose:** Confirm that upload permissions are enforced by the backend, not merely by hiding buttons in the interface.

Submit `IMG03_valid.png` directly to the upload API under each identity:

| User | Expected result |
| --- | --- |
| Admin | Upload allowed |
| Editor | Upload allowed |
| Viewer | Upload denied; no asset created |
| Anonymous (not signed in) | Upload denied; no asset created |

Record the HTTP response and asset-creation check for **all four identities**. A missing upload button alone is not sufficient evidence of access control.

#### Test 18: Quarantine Access Protection

**Purpose:** Ensure that unapproved files cannot be downloaded or served publicly.

Use the unapproved version of `IMG05_corrupted.png` from Test 05.

While authenticated, try:

1. Requesting `/assets/<id>/media-url/`.

2. Accessing `/media/assets/<id>/?token=invalid`.

3. Repeating the media request using **HEAD** and **Range** requests.

4. Checking whether any observed storage or media path is publicly accessible.

**Expected:** No media bytes should be returned while the file is **Pending, Processing or Rejected**. Private storage must not be publicly served.

Record the file's actual state when each request was made. If processing is too fast to observe an intermediate state, state that limitation rather than claiming it was tested.

#### Test 19: Approved File Delivery and Logout

**Purpose:** Confirm that approved files can be delivered correctly, but previously issued links stop working after the issuing session logs out.

1. While authenticated, obtain a Ready PNG's URL through `/assets/<id>/media-url/`.

2. Download the file and compare its SHA-256 checksum with `checksums.sha256`.

3. Log out using the application.

4. Retry the **same previously issued URL**.

5. **Expected:** The file downloads successfully before logout, but access is denied after logout without returning file bytes.

For a stronger check, open a second authenticated session for the **same user**. After logging out the session that issued the URL, retry that old URL while the second session remains signed in. It should still be denied.

Keep evidence of both successful delivery and post-logout denial, with tokens redacted.

#### Test 20: Failed Asset Replacement

**Purpose:** Confirm that a rejected replacement does not destroy or expose the previously approved version.

1. Upload `IMG03_valid.png` and wait until it becomes Ready.

2. Record the approved version ID, download URL and checksum.

3. Replace it with `IMG05_corrupted.png`.

4. Record the new version ID and wait for the replacement to be rejected.

5. Confirm that the rejected replacement has **no usable media URL**.

6. Confirm that the original approved file is still downloadable and has the **same checksum**.

7. Confirm that the original approved version remains available in the shared library.

**Expected:** The failed replacement is rejected without affecting the approved original.

## 6. Record your results

For each case, record:

- **Test ID and file or scenario**

- **Expected result**

- **Actual result**, including relevant HTTP responses and processing status

- **Outcome:** Pass, Fail or Blocked

- **Evidence:** screenshots, responses, checksums, processing details or validator reports

Keep **separate evidence for each subcase**, especially tests involving multiple user roles, MIME declarations or sessions.

> **Final reminder:** A generated test file is only a test input. You can report a security control as passing only after you have carried out the corresponding manual test and recorded what the application actually did.

## 7. Troubleshooting

| Symptom | Action |
| --- | --- |
| `No module named PIL` | Activate the project virtual environment and install `backend/requirements.txt` |
| Missing FFmpeg / FFprobe | Install both executables and add them to PATH in the shell running generation/verification |
| Cannot find `gltf-validator` | Run `npm ci` in `frontend/`; the checker resolves that package relative to this repository |
| Missing `IMG06_overpixels.png` or video fixture | Regenerate using the current scripts and the same output directory; the old `IMG06_wide.png` is no longer a generated case |
| Verification succeeds with skip flags | Repeat without skip flags before claiming the full inventory was verified |
| Worker status `error` | Inspect backend processing details and dependencies; this is **Blocked**, not a security pass |

Full fixture verification checks the construction and expected validator behaviour

of deliberately invalid inputs. It does not certify that every generated file is

safe to publish or that the application's 20 manual cases passed. Run the isolated

application regressions separately using [Checks and tests](../README.md).

