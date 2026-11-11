"""experiment plan

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10 18:00:00.000000

An experiment remembers what it was asked to run (the items and the sweep), so that a cancelled or interrupted sweep can be
resumed: the plan is expanded again and only the runs that are missing are made.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plan', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_column('plan')
