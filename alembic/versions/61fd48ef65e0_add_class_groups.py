"""add class_groups

Revision ID: 61fd48ef65e0
Revises: 3828b67d8a86
Create Date: 2026-09-17 00:00:00.000000

NOTE: this app creates tables at startup via `Base.metadata.create_all()`
(see app/main.py), not via `alembic upgrade`. That means `class_groups` (a
brand new table) gets created automatically on the next deploy — but the new
`class_group_id` column on the *existing* `timetable_slots` table does NOT,
because create_all() only creates missing tables, it never alters existing
ones. If you're not using Alembic as your source of truth, run the single
ALTER TABLE statement in this file's upgrade() manually instead (see the
project README for the exact one-off command).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '61fd48ef65e0'
down_revision: Union[str, Sequence[str], None] = '3828b67d8a86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "class_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_class_groups_id"), "class_groups", ["id"], unique=False)
    op.create_index(op.f("ix_class_groups_name"), "class_groups", ["name"], unique=True)

    op.add_column("timetable_slots", sa.Column("class_group_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_timetable_slots_class_group_id",
        "timetable_slots",
        "class_groups",
        ["class_group_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_timetable_slots_class_group_id", "timetable_slots", type_="foreignkey")
    op.drop_column("timetable_slots", "class_group_id")

    op.drop_index(op.f("ix_class_groups_name"), table_name="class_groups")
    op.drop_index(op.f("ix_class_groups_id"), table_name="class_groups")
    op.drop_table("class_groups")
