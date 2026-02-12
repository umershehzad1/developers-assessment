"""Add worklog tables (freelancer, worklog, payment)

Revision ID: a1b2c3d4e5f6
Revises: 1a31ce608336
Create Date: 2026-02-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '1a31ce608336'
branch_labels = None
depends_on = None


def upgrade():
    # Create freelancer table
    op.create_table(
        'freelancer',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('hourly_rate', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_freelancer_email'), 'freelancer', ['email'], unique=False)
    op.create_index(op.f('ix_freelancer_created_at'), 'freelancer', ['created_at'], unique=False)

    # Create payment table
    op.create_table(
        'payment',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('total_amount', sa.Float(), nullable=False),
        sa.Column('date_range_start', sa.Date(), nullable=False),
        sa.Column('date_range_end', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payment_status'), 'payment', ['status'], unique=False)
    op.create_index(op.f('ix_payment_created_at'), 'payment', ['created_at'], unique=False)

    # Create worklog table (consolidated worklog + time_entry)
    op.create_table(
        'worklog',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('freelancer_id', sa.Integer(), nullable=True),
        sa.Column('task_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('hours', sa.Float(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['worklog.id'], ),
        sa.ForeignKeyConstraint(['freelancer_id'], ['freelancer.id'], ),
        sa.ForeignKeyConstraint(['payment_id'], ['payment.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_worklog_type'), 'worklog', ['type'], unique=False)
    op.create_index(op.f('ix_worklog_parent_id'), 'worklog', ['parent_id'], unique=False)
    op.create_index(op.f('ix_worklog_freelancer_id'), 'worklog', ['freelancer_id'], unique=False)
    op.create_index(op.f('ix_worklog_status'), 'worklog', ['status'], unique=False)
    op.create_index(op.f('ix_worklog_payment_id'), 'worklog', ['payment_id'], unique=False)
    op.create_index(op.f('ix_worklog_created_at'), 'worklog', ['created_at'], unique=False)


def downgrade():
    op.drop_table('worklog')
    op.drop_table('payment')
    op.drop_table('freelancer')
