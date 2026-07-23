"""bug_reports_table

Creates bug_reports table for QA Intelligence workflow.
All other schema changes (index optimization, nullable fixes) deferred
to a separate migration after data audit.

Revision ID: 692e77190ace
Revises: stripe01
Create Date: 2026-07-22 18:00:42.552915
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '692e77190ace'
down_revision: Union[str, None] = 'stripe01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create bug_reports table
    op.create_table('bug_reports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('bug_id', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('problem', sa.Text(), nullable=False),
        sa.Column('root_cause', sa.Text(), nullable=True),
        sa.Column('fix', sa.Text(), nullable=True),
        sa.Column('rule', sa.Text(), nullable=True),
        sa.Column('protection', sa.String(length=50), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('category', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('environment', sa.String(length=20), nullable=False),
        sa.Column('reporter', sa.String(length=200), nullable=False),
        sa.Column('reporter_role', sa.String(length=50), nullable=True),
        sa.Column('screenshot_url', sa.String(length=500), nullable=True),
        sa.Column('source_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('fixed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by', sa.String(length=100), nullable=True),
        sa.Column('verification_comment', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bug_reports_bug_id'), 'bug_reports', ['bug_id'], unique=True)
    op.create_index(op.f('ix_bug_reports_status'), 'bug_reports', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bug_reports_status'), table_name='bug_reports')
    op.drop_index(op.f('ix_bug_reports_bug_id'), table_name='bug_reports')
    op.drop_table('bug_reports')
