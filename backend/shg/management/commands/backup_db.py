"""
Safe SQLite backup while the system is running.

    python manage.py backup_db

- Uses SQLite's online backup API (a plain file copy during a save can corrupt the copy).
- Checks the copy with PRAGMA integrity_check and deletes it if it is damaged.
- Keeps the newest BACKUP_KEEP copies (default 30) in BACKUP_DIR.

Schedule it daily with Windows Task Scheduler (see README).
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a verified backup of the SQLite database and remove old copies."

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        if db["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("backup_db only handles SQLite. For MySQL use mysqldump.")

        src_path = Path(db["NAME"])
        if not src_path.exists():
            raise CommandError(f"Database not found: {src_path}")

        backup_dir = Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"shg_system_{datetime.now():%Y-%m-%d_%H%M%S}.sqlite3"

        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
            src.close()

        if result != "ok":
            target.unlink(missing_ok=True)
            raise CommandError(f"Backup failed integrity check: {result}")

        size_kb = target.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f"Backup OK: {target} ({size_kb:,.0f} KB)"))

        copies = sorted(backup_dir.glob("shg_system_*.sqlite3"))
        for old in copies[:-settings.BACKUP_KEEP]:
            old.unlink()
            self.stdout.write(f"Removed old backup: {old.name}")
