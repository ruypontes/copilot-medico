"""envio_externo: auditoria de envios a provedores externos (B36)

So metadados (quando, consulta, provedor, tamanho): nenhuma coluna guarda
conteudo enviado (US016-CA004).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 23:41:26.798134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('envio_externo',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('consulta_id', sa.Uuid(), nullable=True),
    sa.Column('medico_id', sa.Uuid(), nullable=True),
    sa.Column('provedor', sa.String(length=32), nullable=False),
    sa.Column('operacao', sa.String(length=32), nullable=False),
    sa.Column('tamanho_bytes', sa.Integer(), nullable=False),
    sa.Column('chamadas', sa.Integer(), server_default='1', nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['consulta_id'], ['consulta.id'], name=op.f('fk_envio_externo_consulta_id_consulta'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['medico_id'], ['medico.id'], name=op.f('fk_envio_externo_medico_id_medico'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_envio_externo'))
    )
    with op.batch_alter_table('envio_externo', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_envio_externo_consulta_id'), ['consulta_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_envio_externo_medico_id'), ['medico_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_envio_externo_provedor'), ['provedor'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('envio_externo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_envio_externo_provedor'))
        batch_op.drop_index(batch_op.f('ix_envio_externo_medico_id'))
        batch_op.drop_index(batch_op.f('ix_envio_externo_consulta_id'))

    op.drop_table('envio_externo')
