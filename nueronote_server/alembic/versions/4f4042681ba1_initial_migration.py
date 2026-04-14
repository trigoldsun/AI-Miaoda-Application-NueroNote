"""Initial migration - Create all tables

Revision ID: 4f4042681ba1
Revises: 
Create Date: 2026-04-14 11:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f4042681ba1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Create all NueroNote tables."""
    
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.Text),
        sa.Column('plan', sa.String(32), default='free'),
        sa.Column('storage_quota', sa.BigInteger, default=536870912),  # 512MB
        sa.Column('storage_used', sa.BigInteger, default=0),
        sa.Column('vault_version', sa.Integer, default=1),
        sa.Column('created_at', sa.Integer, nullable=False),
        sa.Column('updated_at', sa.Integer, nullable=False),
        sa.Column('login_fails', sa.Integer, default=0),
        sa.Column('locked_until', sa.Integer, default=0),
        sa.Column('last_login', sa.Integer, default=0),
        sa.Column('last_ip', sa.String(64)),
        sa.Column('cloud_config', sa.Text),
    )
    op.create_index('idx_users_email', 'users', ['email'])
    
    # Vaults table
    op.create_table(
        'vaults',
        sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('vault_json', sa.Text, nullable=False),
        sa.Column('vault_version', sa.Integer, default=1),
        sa.Column('updated_at', sa.Integer, nullable=False),
        sa.Column('updated_seq', sa.Integer, default=0),
        sa.Column('storage_bytes', sa.BigInteger, default=0),
        sa.Column('last_synced_at', sa.Integer, default=0),
    )
    
    # Sync log table
    op.create_table(
        'sync_log',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('record_type', sa.String(32), nullable=False),
        sa.Column('record_id', sa.String(64), nullable=False),
        sa.Column('operation', sa.String(32), nullable=False),
        sa.Column('encrypted_data', sa.Text, nullable=False),
        sa.Column('vector_clock', sa.Integer, default=0),
        sa.Column('created_at', sa.Integer, nullable=False),
    )
    op.create_index('idx_sync_user', 'sync_log', ['user_id', 'created_at'])
    
    # Audit log table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.String(64)),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('ip_addr', sa.String(64)),
        sa.Column('user_agent', sa.Text),
        sa.Column('resource_type', sa.String(64)),
        sa.Column('resource_id', sa.String(64)),
        sa.Column('details', sa.Text),
        sa.Column('created_at', sa.Integer, nullable=False),
    )
    op.create_index('idx_audit_user', 'audit_log', ['user_id', 'created_at'])
    op.create_index('idx_audit_time', 'audit_log', ['created_at'])
    
    # Vault versions table
    op.create_table(
        'vault_versions',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('vault_json', sa.Text, nullable=False),
        sa.Column('vault_bytes', sa.BigInteger, nullable=False),
        sa.Column('created_at', sa.Integer, nullable=False),
        sa.Column('note', sa.Text, default=''),
        sa.Column('is_auto', sa.Boolean, default=True),
    )
    op.create_index('idx_vaultver_user', 'vault_versions', ['user_id', 'version'])
    
    # Document versions table
    op.create_table(
        'document_versions',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('doc_id', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('doc_snapshot', sa.Text, nullable=False),
        sa.Column('created_at', sa.Integer, nullable=False),
        sa.Column('change_summary', sa.Text, default=''),
    )
    op.create_index('idx_docver_doc', 'document_versions', ['doc_id', 'version'])
    
    # Rate limit table
    op.create_table(
        'rate_limit',
        sa.Column('ip_addr', sa.String(64), primary_key=True),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('count', sa.Integer, default=1),
        sa.Column('window_start', sa.Integer, nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema - Drop all tables."""
    op.drop_table('rate_limit')
    op.drop_index('idx_docver_doc', 'document_versions')
    op.drop_table('document_versions')
    op.drop_index('idx_vaultver_user', 'vault_versions')
    op.drop_table('vault_versions')
    op.drop_index('idx_audit_time', 'audit_log')
    op.drop_index('idx_audit_user', 'audit_log')
    op.drop_table('audit_log')
    op.drop_index('idx_sync_user', 'sync_log')
    op.drop_table('sync_log')
    op.drop_table('vaults')
    op.drop_index('idx_users_email', 'users')
    op.drop_table('users')
