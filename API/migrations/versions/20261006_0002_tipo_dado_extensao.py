"""tipo e pep_origem em dado_extensao (B07)

Separa o formato livre legado ("extracted_data") do contrato tipado
("pep_import") e guarda o PEP de origem dos campos importados.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('dado_extensao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tipo', sa.String(length=20), server_default='extracted_data', nullable=False))
        batch_op.add_column(sa.Column('pep_origem', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('dado_extensao', schema=None) as batch_op:
        batch_op.drop_column('pep_origem')
        batch_op.drop_column('tipo')
