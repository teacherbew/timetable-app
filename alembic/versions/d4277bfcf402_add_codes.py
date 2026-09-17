"""add teacher and room codes, relax required fields

Revision ID: d4277bfcf402
Revises: 61fd48ef65e0
Create Date: 2026-09-18 00:00:00.000000

Same note as the previous migration: this app uses create_all() at startup,
so if you're not running `alembic upgrade`, apply the equivalent ALTER TABLE
statements manually once (see the README for the exact one-off commands).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4277bfcf402'
down_revision: Union[str, Sequence[str], None] = '61fd48ef65e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teachers", sa.Column("code", sa.String(), nullable=True))
    op.create_unique_constraint("uq_teachers_code", "teachers", ["code"])
    op.alter_column("teachers", "email", existing_type=sa.String(), nullable=True)

    op.add_column("rooms", sa.Column("code", sa.String(), nullable=True))
    op.create_unique_constraint("uq_rooms_code", "rooms", ["code"])
    op.alter_column("rooms", "name", existing_type=sa.String(), nullable=True)
    op.alter_column("rooms", "capacity", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("rooms", "capacity", existing_type=sa.Integer(), nullable=False)
    op.alter_column("rooms", "name", existing_type=sa.String(), nullable=False)
    op.drop_constraint("uq_rooms_code", "rooms", type_="unique")
    op.drop_column("rooms", "code")

    op.alter_column("teachers", "email", existing_type=sa.String(), nullable=False)
    op.drop_constraint("uq_teachers_code", "teachers", type_="unique")
    op.drop_column("teachers", "code")
