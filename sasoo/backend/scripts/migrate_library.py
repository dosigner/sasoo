#!/usr/bin/env python3
"""
Sasoo Library Migration Script
Migrates from ~/sasoo-library/ (flat UUID-based) to sasoo/library/ (project-internal, named folders).

Usage:
    cd sasoo/backend
    python scripts/migrate_library.py

What it does:
1. Copies sasoo.db and config.json to new location
2. For each paper:
   a. Generates a new folder name via Gemini Flash
   b. Copies papers/{uuid_folder}/ → library/{new_name}/
   c. Moves figures/{uuid_folder}/ → library/{new_name}/figures/
   d. Moves paperbanana/{uuid_folder}/ → library/{new_name}/paperbanana/
   e. Updates DB folder_name and figure file_path
3. Copies agent_profiles/ to new location
"""

import asyncio
import json
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

# Add backend to path for imports
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

OLD_ROOT = Path.home() / "sasoo-library"
NEW_ROOT = BACKEND_DIR / "library"


def migrate_static_files():
    """Copy config.json and sasoo.db to new location."""
    NEW_ROOT.mkdir(parents=True, exist_ok=True)

    # Copy config.json
    old_config = OLD_ROOT / "config.json"
    new_config = NEW_ROOT / "config.json"
    if old_config.exists() and not new_config.exists():
        shutil.copy2(str(old_config), str(new_config))
        logger.info("Copied config.json")

    # Copy sasoo.db
    old_db = OLD_ROOT / "sasoo.db"
    new_db = NEW_ROOT / "sasoo.db"
    if old_db.exists() and not new_db.exists():
        shutil.copy2(str(old_db), str(new_db))
        logger.info("Copied sasoo.db")

    # Copy agent_profiles/
    old_profiles = OLD_ROOT / "agent_profiles"
    new_profiles = NEW_ROOT / "agent_profiles"
    if old_profiles.exists() and not new_profiles.exists():
        shutil.copytree(str(old_profiles), str(new_profiles))
        logger.info("Copied agent_profiles/")


async def generate_new_name(title, year, journal, domain, abstract_text=""):
    """Generate a new folder name using Gemini Flash."""
    try:
        from services.naming_service import generate_folder_name
        return await generate_folder_name(
            title=title,
            year=year,
            journal=journal,
            domain=domain,
            abstract=abstract_text[:500],
        )
    except Exception as exc:
        logger.warning("Gemini naming failed for '%s': %s", title[:50], exc)
        # Fallback: use sanitized title
        import re
        safe = re.sub(r'[^\w\s-]', '', title).strip()
        safe = re.sub(r'[-\s]+', '_', safe)[:40]
        prefix = f"{year}_" if year else ""
        return f"{prefix}{safe}" if safe else f"paper_{id(title) % 10000}"


async def migrate_papers():
    """Migrate each paper from old to new structure."""
    db_path = NEW_ROOT / "sasoo.db"
    if not db_path.exists():
        logger.error("Database not found at %s. Run migrate_static_files() first.", db_path)
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    papers = conn.execute("SELECT * FROM papers").fetchall()
    logger.info("Found %d papers to migrate", len(papers))

    migrated = 0
    skipped = 0
    errors = 0

    for paper in papers:
        paper_id = paper["id"]
        old_folder = paper["folder_name"]
        title = paper["title"]
        year = paper["year"]
        journal = paper["journal"]
        domain = paper["domain"]

        logger.info("--- Paper %d: %s ---", paper_id, title[:60])

        # Check if old folder exists
        old_paper_dir = OLD_ROOT / "papers" / old_folder
        if not old_paper_dir.exists():
            logger.warning("  Old paper dir not found: %s (skipping)", old_paper_dir)
            skipped += 1
            continue

        # Generate new folder name
        try:
            new_folder = await generate_new_name(title, year, journal, domain)
        except Exception as exc:
            logger.error("  Failed to generate name: %s", exc)
            new_folder = old_folder
            errors += 1

        new_paper_dir = NEW_ROOT / new_folder

        # Handle name collision
        if new_paper_dir.exists():
            counter = 2
            while (NEW_ROOT / f"{new_folder}_{counter}").exists():
                counter += 1
            new_folder = f"{new_folder}_{counter}"
            new_paper_dir = NEW_ROOT / new_folder

        logger.info("  %s → %s", old_folder, new_folder)

        # Copy paper directory (PDF + text cache)
        try:
            shutil.copytree(str(old_paper_dir), str(new_paper_dir))
            logger.info("  Copied paper files")
        except Exception as exc:
            logger.error("  Failed to copy paper dir: %s", exc)
            errors += 1
            continue

        # Move figures into paper folder
        old_figures_dir = OLD_ROOT / "figures" / old_folder
        new_figures_dir = new_paper_dir / "figures"
        if old_figures_dir.exists():
            if not new_figures_dir.exists():
                shutil.copytree(str(old_figures_dir), str(new_figures_dir))
            logger.info("  Copied figures")

        # Move paperbanana into paper folder
        old_pb_dir = OLD_ROOT / "paperbanana" / old_folder
        new_pb_dir = new_paper_dir / "paperbanana"
        if old_pb_dir.exists():
            if not new_pb_dir.exists():
                shutil.copytree(str(old_pb_dir), str(new_pb_dir))
            logger.info("  Copied paperbanana")

        # Create mermaid and exports dirs
        (new_paper_dir / "mermaid").mkdir(exist_ok=True)
        (new_paper_dir / "exports").mkdir(exist_ok=True)

        # Update DB: folder_name
        conn.execute(
            "UPDATE papers SET folder_name = ? WHERE id = ?",
            (new_folder, paper_id),
        )

        # Update DB: figure file_path references
        figures = conn.execute(
            "SELECT id, file_path FROM figures WHERE paper_id = ?",
            (paper_id,),
        ).fetchall()

        for fig in figures:
            old_path = fig["file_path"]
            if old_path:
                fig_filename = Path(old_path).name
                new_path = str(new_figures_dir / fig_filename)
                conn.execute(
                    "UPDATE figures SET file_path = ? WHERE id = ?",
                    (new_path, fig["id"]),
                )

        conn.commit()
        migrated += 1
        logger.info("  Migration complete")

    conn.close()

    logger.info("=" * 60)
    logger.info("Migration Summary:")
    logger.info("  Migrated: %d", migrated)
    logger.info("  Skipped:  %d", skipped)
    logger.info("  Errors:   %d", errors)
    logger.info("=" * 60)


async def main():
    logger.info("Starting Sasoo Library Migration")
    logger.info("Old root: %s", OLD_ROOT)
    logger.info("New root: %s", NEW_ROOT)

    if not OLD_ROOT.exists():
        logger.error("Old library root not found: %s", OLD_ROOT)
        logger.info("Nothing to migrate.")
        return

    # Step 1: Copy static files
    migrate_static_files()

    # Step 2: Migrate papers
    await migrate_papers()

    logger.info("Migration complete! You can now start the backend.")
    logger.info("The old library at %s has NOT been deleted (for safety).", OLD_ROOT)
    logger.info("Once verified, you can remove it manually.")


if __name__ == "__main__":
    asyncio.run(main())
