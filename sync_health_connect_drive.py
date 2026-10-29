"""Import the newest private Health Connect ZIP in Google Drive into PostgreSQL.

Requires GitHub Actions Google Workload Identity Federation through a service
account shared as Viewer on the export folder. The script never writes to Drive.

Design:
- Query metadata first; skip already-imported ZIP revisions without downloading.
- Verify downloaded file size and Drive MD5 (if provided).
- Reuse v0.4 idempotent UPSERT importers for four measurement categories.
- Record a success marker only after both importer calls complete.
- If a partial import fails, rerunning safely upserts those records again.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from pathlib import Path

from datastore import connect
from garmin_importer import ensure_schema, log_import
from importer import import_health_zip
from health_extra import import_health_extras

DRIVE_READ_ONLY = "https://www.googleapis.com/auth/drive.readonly"
SOURCE = "Health Connect Drive"


def latest_export(folder_id: str):
    """Return (Google Drive client, newest ZIP metadata) with read-only OAuth."""
    import google.auth
    from googleapiclient.discovery import build

    credentials, _ = google.auth.default(scopes=[DRIVE_READ_ONLY])
    client = build("drive", "v3", credentials=credentials, cache_discovery=False)
    # Escape characters within Drive's query syntax; don't interpolate arbitrary
    # folder ids into the query without validating them.
    if not folder_id or not all(c.isascii() and (c.isalnum() or c in "_-" ) for c in folder_id):
        raise ValueError("GOOGLE_DRIVE_FOLDER_ID is missing or malformed")
    response = client.files().list(
        q=f"'{folder_id}' in parents and name = 'Health Connect.zip' and trashed = false",
        fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,version)",
        orderBy="modifiedTime desc",
        pageSize=50,
    ).execute()
    # The folder can contain old backups; choose newest by modifiedTime.
    files = [f for f in response.get("files", [])
             if f.get("mimeType") in ("application/zip", "application/x-zip-compressed")]
    if not files:
        raise RuntimeError("Health Connect.zip not found. Check folder sharing and Drive API access.")
    files.sort(key=lambda f: f.get("modifiedTime", ""), reverse=True)
    return client, files[0]


def fingerprint(meta: dict) -> str:
    """Stable success marker; file ID handles exporters that create new files."""
    payload = "|".join((meta["id"], str(meta.get("md5Checksum", "")),
                        str(meta.get("size", "")),
                        str(meta.get("modifiedTime", "")),
                        str(meta.get("version", ""))))
    return "drive_zip:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def previously_imported(db, marker: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM ingestion_log WHERE source=? AND dataset=? AND status='ok' LIMIT 1",
        (SOURCE, marker),
    ).fetchone()
    return row is not None


def download_and_verify(client, meta: dict, destination: Path):
    """Resumable chunked download, constrained to a temporary local file."""
    from googleapiclient.http import MediaIoBaseDownload

    maximum = 512 * 1024 * 1024  # unexpected archives should not consume runner disk
    size = int(meta.get("size", "0"))
    if not 0 < size <= maximum:
        raise RuntimeError(f"Unexpected archive size: {size} bytes")
    md5 = hashlib.md5()  # used for transport integrity, not security
    request = client.files().get_media(fileId=meta["id"])
    # MediaIoBaseDownload writes chunks into this file; hash afterward.
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=3)
    actual_size = destination.stat().st_size
    if actual_size != size:
        raise RuntimeError(f"Incomplete Drive download ({actual_size} != {size} bytes)")
    if meta.get("md5Checksum"):
        with destination.open("rb") as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                md5.update(chunk)
        if md5.hexdigest().lower() != meta["md5Checksum"].lower():
            raise RuntimeError("Google Drive MD5 checksum mismatch; refusing to import")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="Verify Drive access and identify latest ZIP; no download or DB writes")
    parser.add_argument("--force", action="store_true",
                        help="Reprocess even if this ZIP revision was already imported")
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("DATABASE_URL must be a PostgreSQL URL; refusing SQLite fallback")

    client, latest = latest_export(os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip())
    print("Drive export:", latest.get("name"),
          "modified", latest.get("modifiedTime"),
          "size", latest.get("size"), "bytes")
    if args.check_only:
        print("Drive authentication and folder access confirmed. No data downloaded.")
        return

    db = connect(url=db_url)
    try:
        ensure_schema(db)
        marker = fingerprint(latest)
        if previously_imported(db, marker) and not args.force:
            print("Unchanged Drive export; skipping download and import.")
            return
        with tempfile.TemporaryDirectory(prefix="health_connect_") as temp_dir:
            filename = Path(temp_dir) / "Health Connect.zip"
            download_and_verify(client, latest, filename)
            # Existing v0.4 importers perform idempotent UPSERTs into PostgreSQL.
            nutrition, weights = import_health_zip(db, filename)
            extra = import_health_extras(db, filename)
        total = nutrition + weights + extra["body_fat"] + extra["blood_pressure"]
        # Only successful imports receive the marker, permitting safe retries.
        log_import(db, SOURCE, marker, total)
        print("Health Connect import completed:",
              {"nutrition": nutrition, "weights": weights,
               "body_fat": extra["body_fat"],
               "blood_pressure": extra["blood_pressure"]})
    finally:
        db.close()


if __name__ == "__main__":
    main()
