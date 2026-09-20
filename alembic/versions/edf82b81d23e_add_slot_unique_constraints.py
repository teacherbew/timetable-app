"""add unique constraints on timetable_slots

Revision ID: edf82b81d23e
Revises: d4277bfcf402
Create Date: 2026-09-19 00:00:00.000000

Closes a rare race condition: two simultaneous requests could both pass the
app-level conflict check before either commits, resulting in a real double
booking. These constraints make that impossible at the database level.

Same note as previous migrations: if you're not using `alembic upgrade`,
apply the equivalent ALTER TABLE statements manually (see the README).
Check for existing violations FIRST — see the manual command in the chat
before running this against a database that already has real schedule data.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'edf82b81d23e'
down_revision: Union[str, Sequence[str], None] = 'd4277bfcf402'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_slot_day_period_teacher", "timetable_slots", ["day", "period", "teacher_id"]
    )
    op.create_unique_constraint(
        "uq_slot_day_period_room", "timetable_slots", ["day", "period", "room_id"]
    )
    op.create_unique_constraint(
        "uq_slot_day_period_class_group", "timetable_slots", ["day", "period", "class_group_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_slot_day_period_class_group", "timetable_slots", type_="unique")
    op.drop_constraint("uq_slot_day_period_room", "timetable_slots", type_="unique")
    op.drop_constraint("uq_slot_day_period_teacher", "timetable_slots", type_="unique")
