"""add_execution_tasks_and_delivery_attempts

Revision ID: 24d4adc2305b
Revises: 994620feea1e
Create Date: 2026-06-20 15:28:40.403447
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '24d4adc2305b'
down_revision: Union[str, None] = '994620feea1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ExecutionTask table ---
    op.create_table('execution_tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('task_code', sa.String(length=30), nullable=False),
        sa.Column('executor_token', sa.UUID(), nullable=False),
        sa.Column('epg_slot_id', sa.UUID(), nullable=False),
        sa.Column('draft_id', sa.UUID(), nullable=True),
        sa.Column('avatar_id', sa.UUID(), nullable=True),
        sa.Column('client_id', sa.UUID(), nullable=True),
        sa.Column('thread_id', sa.UUID(), nullable=True),
        sa.Column('executor_id', sa.UUID(), nullable=True),
        sa.Column('executor_contact', sa.String(length=255), nullable=False),
        sa.Column('executor_type', sa.String(length=50), nullable=False),
        sa.Column('delivery_channel', sa.String(length=50), nullable=False),
        sa.Column('task_type', sa.String(length=50), nullable=False),
        sa.Column('subreddit', sa.String(length=255), nullable=False),
        sa.Column('thread_url', sa.Text(), nullable=False),
        sa.Column('thread_title', sa.Text(), nullable=False),
        sa.Column('avatar_username', sa.String(length=255), nullable=False),
        sa.Column('client_name', sa.String(length=255), nullable=False),
        sa.Column('generated_text', sa.Text(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('status_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('status_history', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('latest_delivery_attempt_id', sa.UUID(), nullable=True),
        sa.Column('delivery_count', sa.Integer(), nullable=False),
        sa.Column('last_delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_url', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verification_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('failure_reason', sa.String(length=500), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('provider_id', sa.UUID(), nullable=True),
        sa.Column('cost_per_task', sa.Float(), nullable=True),
        sa.Column('resource_type', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['avatar_id'], ['avatars.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['draft_id'], ['comment_drafts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['epg_slot_id'], ['epg_slots.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['executor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['thread_id'], ['reddit_threads.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('epg_slot_id'),
        sa.UniqueConstraint('executor_token'),
        sa.UniqueConstraint('task_code'),
    )
    op.create_index('ix_execution_tasks_status', 'execution_tasks', ['status'], unique=False)
    op.create_index('ix_execution_tasks_executor_status', 'execution_tasks', ['executor_id', 'status'], unique=False)
    op.create_index('ix_execution_tasks_client_created', 'execution_tasks', ['client_id', 'created_at'], unique=False)
    op.create_index(
        'ix_execution_tasks_deadline_active', 'execution_tasks', ['deadline'],
        unique=False,
        postgresql_where=sa.text("status NOT IN ('verified', 'expired', 'failed', 'cancelled')"),
    )

    # --- DeliveryAttempt table ---
    op.create_table('delivery_attempts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False),
        sa.Column('recipient', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('provider_message_id', sa.String(length=255), nullable=True),
        sa.Column('provider_response', sa.String(length=500), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('template_version', sa.String(length=20), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('body_excerpt', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['execution_tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'attempt_number', name='uq_delivery_attempt_task_number'),
    )
    op.create_index('ix_delivery_attempts_task_id', 'delivery_attempts', ['task_id'], unique=False)
    op.create_index('ix_delivery_attempts_status_sent', 'delivery_attempts', ['status', 'sent_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_delivery_attempts_status_sent', table_name='delivery_attempts')
    op.drop_index('ix_delivery_attempts_task_id', table_name='delivery_attempts')
    op.drop_table('delivery_attempts')
    op.drop_index('ix_execution_tasks_deadline_active', table_name='execution_tasks')
    op.drop_index('ix_execution_tasks_client_created', table_name='execution_tasks')
    op.drop_index('ix_execution_tasks_executor_status', table_name='execution_tasks')
    op.drop_index('ix_execution_tasks_status', table_name='execution_tasks')
    op.drop_table('execution_tasks')
