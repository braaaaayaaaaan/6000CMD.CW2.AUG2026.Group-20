# DAM File Validation Testing Kit

This testing kit helps you prepare and check sample files for security testing of the Digital Asset Management (DAM) application. It covers **images, MP4 videos and GLB 3D models**, including valid files and deliberately malformed examples.

The scripts **only generate and verify test files**. They do not upload files, sign in, change application settings, test the running application or scan the server. You will carry out the application tests manually using the cases below.

## 1. Before You Start

### Requirements

Make sure the following tools are available:

- **Python 3.9+** and **Pillow** for preparing and checking images. Pillow is already included in the project's Python environment.
- **FFmpeg and FFprobe** on your `PATH` for preparing and inspecting videos.
- **Node.js** and the project's `frontend/node_modules/gltf-validator` package for independent Khronos GLB validation. If the package is missing, run `npm ci` inside `frontend/`.
- **Bash** for the video-generation script (macOS, Linux, WSL or Git Bash).

You can use your existing Python environment. Alternatively, create a separate environment for these tests:

```bash
python3 -m venv security_tests/.venv
source security_tests/.venv/bin/activate
python -m pip install Pillow
```

> **Important:** Run the commands in this README from the **repository root**, with your Python environment activated. If you are using the existing macOS project environment, activate it with `source .venv/bin/activate` instead.

## 2. Generate and Verify the Test Files

Run these three commands in order:

```bash
python security_tests/make_dam_images_glb.py
PYTHON=python bash security_tests/make_dam_videos.sh
python security_tests/verify_fixtures.py
```

Here's what each command does:

| Step | Script | What it does |
| --- | --- | --- |
| 1 | `make_dam_images_glb.py` | Creates seven image files (including the optional size-limit sample), four GLB files and an initial `manifest.csv`. |
| 2 | `make_dam_videos.sh` | Creates four MP4 files and checks them using FFprobe. |
| 3 | `verify_fixtures.py` | Checks the generated files, runs Khronos GLB validation, calculates SHA-256 checksums and updates the manifest to include videos. |

**Check the verification result before proceeding.** If a command exits with a nonzero status, something failed during preparation or verification. Resolve the issue before using those files as evidence in your report.

### Where are the files saved?

By default, everything is saved in:

```text
security_tests/generated/
```

The `generated/` and `evidence/` folders are ignored by Git.

**Be careful when running the scripts again:** generators overwrite their named test files, and verification overwrites its reports, manifest and checksum inventory. Save any evidence you want to keep before regenerating the files.

File outputs can also vary between library or encoder versions, so record the versions of the tools you used and the actual checksums generated on your machine.

### Optional: Use a different output folder

If you want to save the files elsewhere, provide the **same output path** to all three commands:

```bash
python security_tests/make_dam_images_glb.py --output /tmp/dam-security-inputs
PYTHON=python bash security_tests/make_dam_videos.sh /tmp/dam-security-inputs
python security_tests/verify_fixtures.py --output /tmp/dam-security-inputs
```

### Optional: Verify files in stages

If you have only prepared the images and GLBs, you can temporarily skip video verification:

```bash
python security_tests/verify_fixtures.py --skip-videos
```

To run only the independent Khronos GLB checks:

```bash
node security_tests/verify_glbs.cjs
```

You can also use `--skip-khronos` for initial checks if Node.js or the validator package is unavailable. However, **skipping Khronos does not prove that the GLB files are valid**.

Before claiming that all test files have been verified, run the full verification command **without any skip flags**.

## 3. Understanding the Malformed Test Files

Some files are deliberately damaged in specific ways to check whether the application detects unsafe or invalid content.

| Test file or technique | What it is designed to check |
| --- | --- |
| **Corrupted PNG** | The zlib stream checksum is altered while the PNG chunk CRCs are rebuilt. Pillow's `verify()` should pass, but a full `load()` should fail. This checks whether the application actually decodes image content. |
| **GLB with a metadata URI** | The URI is stored in metadata and does not fetch an external resource. This checks whether the DAM's recursive URI restrictions reject it, even though Khronos should consider the GLB format valid. |
| **Broken GLB** | The independent Khronos validator should report errors. |
| **GLB with an invalid floating-point accessor** | The validator should specifically report `ACCESSOR_INVALID_FLOAT` for a NaN value. |

The GLB validator saves JSON reports beside the GLB files. It expects **zero errors** for the valid GLB and the metadata-URI GLB, and errors for the two invalid GLBs.

> **Remember:** These are expected results, not proof that the application has passed. A worker status of `error` means processing could not complete. Investigate it rather than treating it as a successful security rejection.

## 4. Set Up the Application for Manual Testing

Before uploading the generated files:

1. Start a **disposable local application instance** using the instructions in the [main project README](../README.md).
2. Prepare disposable **Admin, Editor and Viewer** accounts. They should have completed email verification and MFA.
3. Ensure FFprobe, Node.js and the Khronos validator package are accessible to the backend.
4. Prepare somewhere to record each test's **actual result, Pass / Fail / Blocked status, and evidence**. You can use your report or notes; a separate spreadsheet is not required.
5. Keep the generated checksums, verification reports, validator output, upload responses, processing statuses and screenshots.

### API requests for specific tests

Some tests require direct authenticated API requests, rather than just clicking through the interface.

| Action | Endpoint | Notes |
| --- | --- | --- |
| Upload an asset | `POST /assets/` | Multipart fields: `name`, `description`, `url` |
| Replace an asset | `PATCH /assets/<id>/` | Creates a new asset version |

For MIME spoofing and role checks, reuse the application's normal session and CSRF handling. You can inspect a successful request in your browser's **Network** panel and adapt it in an API client.

**Do not commit session cookies, access tokens or signed media links as evidence.** Redact them from screenshots and logs.

### Optional: Test a smaller upload limit

For the size-limit test, set the following in your **disposable backend environment**, then restart the backend:

```env
ASSET_UPLOAD_MAX_MB=1
```

This allows you to check whether the application enforces a **1 MiB limit** without generating a file over 100 MiB.

After testing, restore the original setting. This test only demonstrates enforcement of the reduced limit; it **does not verify the default 100 MiB boundary**.

## 5. Manual Test Cases

All 20 cases below must be carried out against the running application. Generating the files successfully does **not** mean that the application passed the tests.

### Part A: Media Upload Validation (Tests 01–14)

Upload each file while signed in as an **Editor**.

For every upload, record the filename, HTTP response, asset/version ID (if created), final `processing_status`, processing details and evidence. The backend status `approved` is shown as **Ready** in the interface.

| ID | File | Expected result |
| --- | --- | --- |
| 01 | `IMG01_valid.jpg` | Accepted and progresses from Pending → Processing → Ready. |
| 02 | `IMG02_valid.jpeg` | Accepted and progresses from Pending → Processing → Ready. |
| 03 | `IMG03_valid.png` | Accepted and progresses from Pending → Processing → Ready. |
| 04 | `IMG04_fake.png` | Rejected with HTTP 400. No asset or version is created. |
| 05 | `IMG05_corrupted.png` | Initially accepted into private quarantine, then rejected by the worker. Must never become Ready. |
| 06 | `IMG06_wide.png` | Becomes Ready. The image has 10 million total pixels, even though its width exceeds 4K. |
| 07 | `VID01_valid.mp4` | Accepted and becomes Ready. |
| 08 | `VID02_fake.mp4` | Rejected with HTTP 400. No asset or version is created. |
| 09 | `VID03_broken.mp4` | Rejected with HTTP 400. No asset or version is created. |
| 10 | `VID04_over4k.mp4` | Accepted into quarantine, then rejected by the worker for excessive resolution. |
| 11 | `GLB01_valid.glb` | Accepted and becomes Ready. Keep its zero-error Khronos validation report. |
| 12 | `GLB02_broken.glb` | Rejected with HTTP 400. No asset or version is created. |
| 13 | `GLB03_external.glb` | Rejected with HTTP 400 by the DAM's URI policy, even though its Khronos format validation is separate. |
| 14 | `GLB04_invalid_accessor.glb` | Rejected by the worker. Keep the independent report showing `ACCESSOR_INVALID_FLOAT`. |

**How to interpret the results:**

- Some files may process too quickly for you to see every intermediate status. Use the initial HTTP response, API metadata and processing details as supporting evidence.
- An HTTP 400 response shows that the request was rejected **before asset creation**. It does not prove that the background worker inspected the file.
- Missing dependencies, timeouts and worker `error` statuses are operational problems or **Blocked** tests, not successful security rejections.
- For every HTTP 400 case, confirm that no new asset or version was created.

### Part B: Upload and Delivery Security (Tests 15–20)

These tests go beyond file format checks. They examine MIME handling, size limits, user permissions, quarantine protection, session-bound delivery and version replacement.

#### Test 15: MIME Type Spoofing

**Purpose:** Check whether the backend trusts the file's actual contents rather than the MIME type declared by the uploader.

Perform two authenticated multipart uploads:

1. Upload the real `IMG03_valid.png`, but declare the file part as `text/plain`. **Expected:** The file is accepted and becomes Ready.
2. Upload the text-based `IMG04_fake.png`, but declare the file part as `image/png`. **Expected:** HTTP 400, with no asset created.

Change only the **file part's MIME type**, not the overall multipart request's `Content-Type` or boundary. Record both responses separately.

#### Test 16: Upload Size Limit

**Purpose:** Confirm that the backend enforces the configured maximum upload size.

1. Set `ASSET_UPLOAD_MAX_MB=1` in the disposable backend and restart it.
2. Upload `SHR01_over1MiB.png`.
3. **Expected:** HTTP 400, with no new asset created.
4. Record the file's actual byte count and restore the original setting.

In your report, clearly state that you tested a **reduced 1 MiB limit**. Testing the default **100 MiB** boundary requires a separate, valid, larger file.

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

## 6. Recording Your Results

For each case, record:

- **Test ID and file or scenario**
- **Expected result**
- **Actual result**, including relevant HTTP responses and processing status
- **Outcome:** Pass, Fail or Blocked
- **Evidence:** screenshots, responses, checksums, processing details or validator reports

Keep **separate evidence for each subcase**, especially tests involving multiple user roles, MIME declarations or sessions.

> **Final reminder:** A generated test file is only a test input. You can report a security control as passing only after you have carried out the corresponding manual test and recorded what the application actually did.
