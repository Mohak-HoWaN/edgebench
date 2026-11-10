"""dataset versions and experiments

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10 12:00:00.000000

A dataset becomes a named history of versions: what used to sit on the dataset row (counts, class names, the normalised
zip, statistics) moves to version 1 of that dataset. The picture-kind tag ("origin") is dropped. Experiments get a name's
worth of context (notes, dataset version, device, settings), and the runs that existed before experiments are gathered into
one experiment so the Results page has no loose rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COPIED = ('format', 'image_count', 'labelled_count', 'instance_count', 'class_names', 'names_generic', 'dataset_hash',
          'artifact_sha256', 'size_bytes', 'stats', 'calibration', 'source_path')
MOVED_OUT = ('status', 'error', 'origin', 'format', 'image_count', 'labelled_count', 'instance_count', 'class_names',
             'names_generic', 'dataset_hash', 'artifact_sha256', 'source_sha256', 'source_path', 'size_bytes', 'stats',
             'calibration')


def upgrade() -> None:
    op.create_table('dataset_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('message', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('manifest', sa.JSON(), nullable=True),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('format', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('image_count', sa.Integer(), nullable=False),
        sa.Column('labelled_count', sa.Integer(), nullable=False),
        sa.Column('instance_count', sa.Integer(), nullable=False),
        sa.Column('class_names', sa.JSON(), nullable=True),
        sa.Column('names_generic', sa.Boolean(), nullable=False),
        sa.Column('dataset_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('artifact_sha256', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=True),
        sa.Column('calibration', sa.JSON(), nullable=True),
        sa.Column('source_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['artifact_sha256'], ['artifacts.sha256'], ),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id', 'number', name='uq_dataset_version_number'),
    )
    with op.batch_alter_table('dataset_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_versions_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_versions_dataset_hash'), ['dataset_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_versions_artifact_sha256'), ['artifact_sha256'], unique=False)

    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('head_version_id', sa.Integer(), nullable=True))

    # Every existing dataset becomes version 1 of itself. Its files were never kept as separate blobs, so its manifest is
    # empty (NULL): it can be run, previewed and downloaded in normalised form, but not restored from.
    bind = op.get_bind()
    columns = ', '.join(COPIED)
    bind.execute(sa.text(
        "INSERT INTO dataset_versions (dataset_id, number, message, created_at, status, error, " + columns + ") "
        "SELECT id, 1, 'Imported before versions existed', created_at, "
        "CASE WHEN status = 'ready' THEN 'ready' WHEN status = 'failed' THEN 'failed' ELSE 'failed' END, error, " + columns
        + " FROM datasets"))
    bind.execute(sa.text(
        "UPDATE datasets SET head_version_id = (SELECT v.id FROM dataset_versions v WHERE v.dataset_id = datasets.id "
        "AND v.status = 'ready')"))

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dataset_version_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_runs_dataset_version_id'), ['dataset_version_id'], unique=False)
        batch_op.create_foreign_key('fk_runs_dataset_version', 'dataset_versions', ['dataset_version_id'], ['id'])
    bind.execute(sa.text(
        "UPDATE runs SET dataset_version_id = (SELECT v.id FROM dataset_versions v WHERE v.dataset_id = runs.dataset_id "
        "AND v.number = 1)"))

    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_datasets_artifact', type_='foreignkey')
        batch_op.drop_index('ix_datasets_artifact_sha256')
        batch_op.drop_index('ix_datasets_dataset_hash')
        for column in MOVED_OUT:
            batch_op.drop_column(column)

    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notes', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('dataset_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('dataset_version_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('device_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('params', sa.JSON(), nullable=True))
        batch_op.create_foreign_key('fk_experiments_dataset', 'datasets', ['dataset_id'], ['id'])
        batch_op.create_foreign_key('fk_experiments_dataset_version', 'dataset_versions', ['dataset_version_id'], ['id'])
        batch_op.create_foreign_key('fk_experiments_device', 'devices', ['device_id'], ['id'])

    # Runs made before experiments existed share one experiment, so every row on the Results page is an experiment.
    orphans = bind.execute(sa.text("SELECT COUNT(*) FROM runs WHERE experiment_id IS NULL")).scalar()
    if orphans:
        bind.execute(sa.text(
            "INSERT INTO experiments (name, notes, created_at, dataset_id, dataset_version_id, device_id) "
            "SELECT 'First benchmark (made before experiments existed)', '', MIN(created_at), MIN(dataset_id), "
            "MIN(dataset_version_id), MIN(device_id) FROM runs WHERE experiment_id IS NULL"))
        bind.execute(sa.text(
            "UPDATE runs SET experiment_id = (SELECT MAX(id) FROM experiments) WHERE experiment_id IS NULL"))


def downgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_experiments_device', type_='foreignkey')
        batch_op.drop_constraint('fk_experiments_dataset_version', type_='foreignkey')
        batch_op.drop_constraint('fk_experiments_dataset', type_='foreignkey')
        for column in ('params', 'device_id', 'dataset_version_id', 'dataset_id', 'notes'):
            batch_op.drop_column(column)

    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='ready'))
        batch_op.add_column(sa.Column('error', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='real camera'))
        batch_op.add_column(sa.Column('format', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('image_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('labelled_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('instance_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('class_names', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('names_generic', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('dataset_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('artifact_sha256', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('source_sha256', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('source_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('stats', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('calibration', sa.JSON(), nullable=True))
        batch_op.create_index('ix_datasets_artifact_sha256', ['artifact_sha256'], unique=False)
        batch_op.create_index('ix_datasets_dataset_hash', ['dataset_hash'], unique=False)
        batch_op.create_foreign_key('fk_datasets_artifact', 'artifacts', ['artifact_sha256'], ['sha256'])

    # Hand each dataset its newest finished version's content back (the history itself cannot be kept in the old shape).
    bind = op.get_bind()
    sets = ', '.join(f"{c} = (SELECT v.{c} FROM dataset_versions v WHERE v.id = datasets.head_version_id)" for c in COPIED)
    bind.execute(sa.text(f"UPDATE datasets SET {sets}, status = 'ready' WHERE head_version_id IS NOT NULL"))

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_runs_dataset_version', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_runs_dataset_version_id'))
        batch_op.drop_column('dataset_version_id')

    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_column('head_version_id')
        batch_op.drop_column('description')

    op.drop_table('dataset_versions')
