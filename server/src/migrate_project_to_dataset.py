"""
One-time migration: rename project_id → dataset_id in JSON database files.

Migrates:
- projects.json → datasets.json (field: project_id → dataset_id)
- cure_projects.json → cure_datasets.json (field: project_id → dataset_id)
- new_texts.json (field: project_id → dataset_id in each record)

Called automatically on startup if old files exist.
"""
import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)


def _get_db_dir() -> str:
    return os.path.join(os.getcwd(), "data", "db")


def _migrate_file(old_name: str, new_name: str, field_renames: dict):
    """Migrate a JSON DB file: rename file and rename fields in each record."""
    db_dir = _get_db_dir()
    old_path = os.path.join(db_dir, old_name)
    new_path = os.path.join(db_dir, new_name)

    if not os.path.exists(old_path):
        return False

    if os.path.exists(new_path):
        # Check if target is empty (handler may have created it on startup)
        try:
            with open(new_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing:  # Non-empty — already migrated
                logger.info(f"Migration: {new_name} already exists with data, skipping")
                return False
        except Exception:
            pass

    logger.info(f"Migration: {old_name} → {new_name}")

    with open(old_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        for record in data:
            for old_field, new_field in field_renames.items():
                if old_field in record:
                    record[new_field] = record.pop(old_field)
    elif isinstance(data, dict):
        for old_field, new_field in field_renames.items():
            if old_field in data:
                data[new_field] = data.pop(old_field)

    # Write new file
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Keep old file as backup
    backup_path = old_path + ".bak"
    shutil.move(old_path, backup_path)
    logger.info(f"Migration: backed up {old_name} → {old_name}.bak")

    return True


def run_migration():
    """Run all project→dataset migrations if needed."""
    db_dir = _get_db_dir()
    if not os.path.exists(db_dir):
        return

    migrated = False

    # Migrate projects.json → datasets.json
    if _migrate_file("projects.json", "datasets.json", {"project_id": "dataset_id"}):
        migrated = True

    # Migrate cure_projects.json → cure_datasets.json
    if _migrate_file("cure_projects.json", "cure_datasets.json", {"project_id": "dataset_id"}):
        migrated = True

    # Migrate project_id → dataset_id in new_texts.json (in-place rename)
    new_texts_path = os.path.join(db_dir, "new_texts.json")
    if os.path.exists(new_texts_path):
        # Check if migration is needed by reading first record
        try:
            with open(new_texts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0 and "project_id" in data[0]:
                logger.info("Migration: new_texts.json — renaming project_id → dataset_id")
                for record in data:
                    if "project_id" in record:
                        record["dataset_id"] = record.pop("project_id")

                # Atomic write
                tmp_path = new_texts_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp_path, new_texts_path)
                logger.info("Migration: new_texts.json complete")
                migrated = True
        except Exception as e:
            logger.error(f"Migration: new_texts.json failed: {e}")

    # Migrate destination_project_id → destination_dataset_id in batch_recognition_jobs.json
    batch_jobs_path = os.path.join(db_dir, "batch_recognition_jobs.json")
    if os.path.exists(batch_jobs_path):
        try:
            with open(batch_jobs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0 and "destination_project_id" in data[0]:
                logger.info("Migration: batch_recognition_jobs.json — renaming destination_project_id → destination_dataset_id")
                for record in data:
                    if "destination_project_id" in record:
                        record["destination_dataset_id"] = record.pop("destination_project_id")

                tmp_path = batch_jobs_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, batch_jobs_path)
                logger.info("Migration: batch_recognition_jobs.json complete")
                migrated = True
        except Exception as e:
            logger.error(f"Migration: batch_recognition_jobs.json failed: {e}")

    if migrated:
        logger.info("Migration: project→dataset rename complete")
    else:
        logger.debug("Migration: no project→dataset migration needed")
