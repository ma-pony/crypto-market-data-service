"""Initial migration - Create OHLCV table.

Revision ID: 001
Revises: 
Create Date: 2025-01-01

Creates the OHLCV table for storing K-line data with:
- Unique constraint on (exchange, symbol, timeframe, timestamp)
- Index for efficient lookups

Requirements: 8.1
"""

from alembic import op
import sqlalchemy as sa


# Revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create OHLCV table with constraints and indexes."""
    op.create_table(
        'ohlcv',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(8), nullable=False),
        sa.Column('timestamp', sa.BigInteger(), nullable=False),
        sa.Column('open', sa.Numeric(18, 8), nullable=False),
        sa.Column('high', sa.Numeric(18, 8), nullable=False),
        sa.Column('low', sa.Numeric(18, 8), nullable=False),
        sa.Column('close', sa.Numeric(18, 8), nullable=False),
        sa.Column('volume', sa.Numeric(18, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            'exchange', 'symbol', 'timeframe', 'timestamp',
            name='uq_ohlcv_key'
        ),
    )
    
    # Create index for efficient lookups by exchange/symbol/timeframe/timestamp
    op.create_index(
        'idx_ohlcv_lookup',
        'ohlcv',
        ['exchange', 'symbol', 'timeframe', 'timestamp']
    )


def downgrade() -> None:
    """Drop OHLCV table and related objects."""
    op.drop_index('idx_ohlcv_lookup', table_name='ohlcv')
    op.drop_table('ohlcv')
