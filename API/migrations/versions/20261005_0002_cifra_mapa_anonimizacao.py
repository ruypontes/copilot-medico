"""B26: cifra do mapa de pseudonimos (US016-CA002 / ADR-03).

Duas adicoes, nenhuma destrutiva:

- `medico.chave_cifrada` / `medico.chave_salt`: envelope da chave de dados
  (DEK) embrulhada pela chave derivada da senha. Nulos ate o primeiro login
  apos a atualizacao, quando o backend cria o cofre do medico.
- `mapa_anonimizacao`: mapa token -> valor real por consulta, cifrado. E o
  que mantem os tokens estaveis entre mensagens (B25) e permite reidratar a
  resposta do modelo so na exibicao.

Nenhuma linha existente e alterada: `pseudonimo` ja tinha `dados_cifrados` e
`algoritmo_cifra` desde o B19, e as linhas com algoritmo "none" seguem
legiveis ate serem recifradas na proxima escrita.

Revision ID: 0002
Revises: 0001
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
    op.create_table('mapa_anonimizacao',
    sa.Column('consulta_id', sa.Uuid(), nullable=False),
    sa.Column('dados_cifrados', sa.LargeBinary(), nullable=False),
    sa.Column('algoritmo_cifra', sa.String(length=32), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['consulta_id'], ['consulta.id'], name=op.f('fk_mapa_anonimizacao_consulta_id_consulta'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('consulta_id', name=op.f('pk_mapa_anonimizacao'))
    )
    with op.batch_alter_table('medico', schema=None) as batch_op:
        batch_op.add_column(sa.Column('chave_cifrada', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('chave_salt', sa.LargeBinary(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('medico', schema=None) as batch_op:
        batch_op.drop_column('chave_salt')
        batch_op.drop_column('chave_cifrada')

    op.drop_table('mapa_anonimizacao')
