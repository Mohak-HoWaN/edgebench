"""model compatibility record and the converter versions that built each variant

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14 12:00:00.000000

``models.card``: what inspect read about the file's origin (library that trained it, architecture) and the compatibility verdict.
``variants.toolchain``: the converter library versions that built the variant; NULL for variants made before this column
existed, which are shown as "built before versions were recorded".
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('card', sa.JSON(), nullable=True))
    with op.batch_alter_table('variants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('toolchain', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('variants', schema=None) as batch_op:
        batch_op.drop_column('toolchain')
    with op.batch_alter_table('models', schema=None) as batch_op:
        batch_op.drop_column('card')
