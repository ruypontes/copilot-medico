"""Gera um XML do CNES sintético para a instalação de treinamento do PEC.

O PEC só cria unidade, equipe e lotação a partir do XML do CNES, que vem da
área restrita do e-Gestor APS. Para testar a tela de atendimento (B50) sem
esse acesso, este script monta um XML no formato XSD 3.1 que o próprio PEC
5.5.28 valida (cnes/cnes_3.1.xsd, dentro do backend-5.5.28.jar), com uma
UBS, uma equipe de Saúde da Família e uma médica, todos fictícios.

Uso (o município precisa estar habilitado na instalação):

    python esus-pec/gerar_cnes_teste.py cnes_teste.xml                # Paulista/PE
    python esus-pec/gerar_cnes_teste.py cnes_teste.xml --ibge 2611606 --uf PE --cep 50000000
"""
from __future__ import annotations

import argparse
import random
from datetime import date


def cpf(rnd: random.Random) -> str:
    n = [rnd.randint(0, 9) for _ in range(9)]
    for k in (10, 11):
        d = sum(x * w for x, w in zip(n, range(k, 1, -1))) * 10 % 11
        n.append(0 if d == 10 else d)
    return "".join(map(str, n))


def cnpj(rnd: random.Random) -> str:
    n = [rnd.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        r = sum(x * w for x, w in zip(n, pesos)) % 11
        n.append(0 if r < 2 else 11 - r)
    return "".join(map(str, n))


def cns(rnd: random.Random) -> str:
    """CNS provisório (começa com 7): a soma ponderada (15..1) é múltipla de 11."""
    while True:
        base = [7] + [rnd.randint(0, 9) for _ in range(13)]
        s = sum(x * w for x, w in zip(base, range(15, 1, -1)))
        d = (11 - s % 11) % 11
        if d < 10:
            return "".join(map(str, base + [d]))


def gerar_xml(ibge: str, uf: str, cep: str, rnd: random.Random) -> str:
    unidade, ine = "9999901", "0000999901"
    # ORIGEM e DESTINO são fixos no XSD; TP_EQUIPE 70 = eSF; CBO 225142 = médico da ESF.
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<ImportarXMLCNES>
  <IDENTIFICACAO DATA="{date.today().isoformat()}" ORIGEM="PORTAL" DESTINO="ESUS_AB" CO_IBGE_MUN="{ibge}" VERSAO_XSD="3.1">
    <ESTABELECIMENTOS>
      <DADOS_GERAIS_ESTABELECIMENTOS NM_FANTA="UBS TESTE COPMED" CNPJ="{cnpj(rnd)}" CNES="{unidade}" TP_UNID_ID="2" DS_TP_UNID="CENTRO DE SAUDE/UNIDADE BASICA" CO_SUBTIPO_UNID="" DS_SUBTIPO_UNID="" TELEFONE1="" TELEFONE2="" FAX="" E_MAIL="">
        <ENDERECO>
          <DADOS_ENDERECO CO_CEP="{cep}" SG_UF="{uf}" CO_IBGE_MUN="{ibge}" BAIRRO="CENTRO" LOGRADOURO="RUA FICTICIA" NUMERO="100" COMPLEMENT="" PONTO_REF=""/>
        </ENDERECO>
        <COMPLEXIDADE>
          <DADOS_COMPLEXIDADE SG_COMPLEXIDADE="AB"/>
        </COMPLEXIDADE>
        <EQUIPES>
          <DADOS_EQUIPES ID_TP_EQUIPE="" TP_EQUIPE="70" SG_EQUIPE="ESF" DS_EQUIPE="ESF - EQUIPE DE SAUDE DA FAMILIA" CO_INE="{ine}" CO_AREA="1" DS_AREA="AREA TESTE" NM_REFERENCIA="EQUIPE TESTE COPMED" DT_DESATIVACAO=""/>
        </EQUIPES>
      </DADOS_GERAIS_ESTABELECIMENTOS>
    </ESTABELECIMENTOS>
    <PROFISSIONAIS>
      <DADOS_PROFISSIONAIS NM_PROF="MEDICA TESTE COPMED" CPF_PROF="{cpf(rnd)}" CO_CNS="{cns(rnd)}" DT_NASC="1985-05-10" SEXO="F">
        <ENDERECO/>
        <LOTACOES>
          <DADOS_LOTACOES CNES="{unidade}" CO_INE="{ine}" CO_CBO="225142" MICROAREA=""/>
        </LOTACOES>
      </DADOS_PROFISSIONAIS>
    </PROFISSIONAIS>
  </IDENTIFICACAO>
</ImportarXMLCNES>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera um XML do CNES sintético para o PEC de treinamento.")
    parser.add_argument("saida", help="arquivo XML a gerar")
    parser.add_argument("--ibge", default="2610707", help="código IBGE do município (padrão: Paulista/PE)")
    parser.add_argument("--uf", default="PE")
    parser.add_argument("--cep", default="53401000")
    parser.add_argument("--semente", type=int, default=2410, help="semente dos números fictícios")
    args = parser.parse_args()

    xml = gerar_xml(args.ibge, args.uf, args.cep, random.Random(args.semente))
    with open(args.saida, "w", encoding="iso-8859-1", newline="\n") as arquivo:
        arquivo.write(xml)
    print(f"XML gerado em {args.saida} (município IBGE {args.ibge}).")


if __name__ == "__main__":
    main()
