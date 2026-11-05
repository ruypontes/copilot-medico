"""parte_audio: partes (chunks) de audio aguardando transcricao (B30)

Guarda so os metadados de cada parte recebida em
POST /api/consultations/<id>/audio/chunks (sequencia, tamanho, duracao e o
caminho do arquivo temporario). O audio em si nunca entra no banco.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 23:31:54.534720

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
    op.create_table('parte_audio',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('consulta_id', sa.Uuid(), nullable=False),
    sa.Column('gravacao_id', sa.String(length=64), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('caminho', sa.Text(), nullable=False),
    sa.Column('tamanho_bytes', sa.Integer(), nullable=False),
    sa.Column('duracao_s', sa.Float(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['consulta_id'], ['consulta.id'], name=op.f('fk_parte_audio_consulta_id_consulta'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parte_audio')),
    sa.UniqueConstraint('consulta_id', 'gravacao_id', 'seq', name=op.f('uq_parte_audio_consulta_id'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('parte_audio')
