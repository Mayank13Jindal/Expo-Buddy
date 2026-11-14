#!/usr/bin/env python3
"""Generate an explicit initial-table migration from *new* table definitions.

This script is for development, not runtime; generated migrations are reviewed and committed.
Existing-table changes require an ordinary Alembic migration.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from alembic.autogenerate import render_python_code
from alembic.operations import ops

from app.db import library  # noqa: F401
from app.db import processing  # noqa: F401
from app.db import grouping  # noqa: F401
from app.db import intelligence  # noqa: F401
from app.db import search  # noqa: F401
from app.db import operations  # noqa: F401
from app.db import agent  # noqa: F401
from app.db import exports  # noqa: F401
from app.db import capture  # noqa: F401
from app.db.models import Base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("revision")
    parser.add_argument("previous")
    parser.add_argument("tables", nargs="+")
    args = parser.parse_args()
    tables = [table for table in Base.metadata.sorted_tables if table.name in args.tables]
    upgrade = []
    for table in tables:
        upgrade.append(ops.CreateTableOp.from_table(table))
        upgrade += [ops.CreateIndexOp.from_index(index) for index in table.indexes]
    downgrade = [ops.DropTableOp.from_table(table) for table in reversed(tables)]
    source = ('"""' + args.revision + '"""\nfrom alembic import op\nimport sqlalchemy as sa\nfrom sqlalchemy.dialects import postgresql\n\n'
              f'revision = "{args.revision}"\ndown_revision = "{args.previous}"\n'
              'branch_labels = None\ndepends_on = None\n\ndef upgrade():\n'
              + render_python_code(ops.UpgradeOps(upgrade))
              + '\n\ndef downgrade():\n' + render_python_code(ops.DowngradeOps(downgrade)) + '\n')
    destination = Path(__file__).resolve().parents[1] / "backend/app/db/migrations/versions" / f"{args.revision}.py"
    destination.write_text(source)


if __name__ == "__main__":
    main()

