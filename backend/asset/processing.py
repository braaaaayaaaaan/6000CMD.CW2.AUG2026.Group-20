"""Run upload checks after commit, outside the HTTP request."""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.db import connections, transaction

from .files import process_uploads


logger = logging.getLogger(__name__)
upload_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="asset-checks")


def process_uploaded_asset(asset_id):
    try:
        process_uploads(limit=1, asset_id=asset_id)
    except Exception:
        # Pending jobs remain available to the existing operator retry command.
        logger.exception("asset_processing_worker_failed", extra={"asset_id": str(asset_id)})
    finally:
        connections.close_all()


def schedule_upload_processing(asset_id):
    def enqueue():
        try:
            upload_workers.submit(process_uploaded_asset, asset_id)
        except RuntimeError:
            logger.exception("asset_processing_enqueue_failed", extra={"asset_id": str(asset_id)})

    transaction.on_commit(enqueue)
