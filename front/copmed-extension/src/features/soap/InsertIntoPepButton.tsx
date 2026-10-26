import { useEffect, useState } from "react";
import type { MotivoFalhaEscrita } from "../../pep/pepAdapter";
import { formatSoapForPep } from "../../pep/formatarSoap";
import { markSoapInserted } from "../../services/api";
import { getErrorMessage, type SoapDocument } from "../shared/types";
import { ponteChrome, type PonteDoPep } from "./pepDaAba";

// Botão "Inserir no prontuário" (B53 / US019-CA006). A escrita nunca é automática:
// só acontece no clique, e o botão só habilita com o SOAP aprovado e um PEP
// aberto na aba. Primeiro escreve pelo adaptador do PEP; só com a escrita
// confirmada registra o status `inserido_no_pep` na API. Pronto para o
// SoapEditor (B43) usar depois do "Aprovar".

const NOMES_PEP: Record<string, string> = { "esus-pec": "e-SUS PEC", amplimed: "Amplimed" };

const FALHAS: Record<MotivoFalhaEscrita, string> = {
  texto_vazio: "O SOAP está vazio: nada foi inserido.",
  campo_nao_encontrado:
    "Não encontrei o campo de evolução nesta tela do prontuário. Abra o atendimento e tente de novo.",
  falha_ao_escrever: "O prontuário não aceitou o texto (campo cheio ou tela mudou). Nada foi registrado.",
};

type Props = {
  consultationId: string;
  soap: SoapDocument;
  onInserted?: (soap: SoapDocument) => void;
  ponte?: PonteDoPep;
};

export default function InsertIntoPepButton({ consultationId, soap, onInserted, ponte = ponteChrome }: Props) {
  const [pep, setPep] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  // Texto já está no PEP, mas o status não foi gravado: só falta registrar.
  const [pendenteRegistro, setPendenteRegistro] = useState<string | null>(null);

  useEffect(() => {
    let ativo = true;
    void ponte.pepDaAba().then((id) => ativo && setPep(id));
    return () => {
      ativo = false;
    };
  }, [ponte, soap.id]);

  const inserido = soap.status === "inserido_no_pep";
  const aprovado = soap.status === "aprovado";
  const motivoDesabilitado = inserido
    ? "Este SOAP já foi inserido no prontuário."
    : !aprovado
      ? "Aprove o SOAP para inserir no prontuário."
      : !pep
        ? "Abra o atendimento do paciente no Amplimed ou no e-SUS PEC nesta aba."
        : null;

  async function registrar(pepId: string) {
    try {
      const resposta = await markSoapInserted(consultationId, soap.id, pepId);
      setPendenteRegistro(null);
      setAviso(`SOAP inserido no ${NOMES_PEP[pepId] ?? pepId}.`);
      onInserted?.(resposta.soap as SoapDocument);
    } catch (error) {
      setPendenteRegistro(pepId);
      setAviso(
        `O texto já está no prontuário, mas o status não foi registrado (${getErrorMessage(error, "erro de conexão")}). ` +
          "Não insira de novo: use “Registrar inserção”.",
      );
    }
  }

  async function inserir() {
    if (motivoDesabilitado || ocupado) return;
    setOcupado(true);
    setAviso(null);
    try {
      const escrita = await ponte.escrever(formatSoapForPep(soap.atual, pep ?? undefined));
      if (!escrita) {
        setPep(null);
        setAviso("A aba não mostra mais um prontuário. Nada foi inserido.");
      } else if (!escrita.resultado.ok) {
        setAviso(FALHAS[escrita.resultado.motivo]);
      } else {
        await registrar(escrita.pep);
      }
    } finally {
      setOcupado(false);
    }
  }

  async function registrarDeNovo() {
    if (!pendenteRegistro || ocupado) return;
    setOcupado(true);
    try {
      await registrar(pendenteRegistro);
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="soap-inserir">
      {pendenteRegistro ? (
        <button type="button" className="btn-green" onClick={registrarDeNovo} disabled={ocupado}>
          {ocupado ? "Registrando..." : "Registrar inserção"}
        </button>
      ) : (
        <button
          type="button"
          className="btn-green"
          onClick={inserir}
          disabled={Boolean(motivoDesabilitado) || ocupado}
          aria-describedby={motivoDesabilitado ? "soap-inserir-motivo" : undefined}
        >
          {ocupado ? "Inserindo..." : inserido ? "Inserido no prontuário" : "Inserir no prontuário"}
        </button>
      )}
      {motivoDesabilitado && !pendenteRegistro && !aviso && (
        <p id="soap-inserir-motivo" className="soap-diff-aviso">
          {motivoDesabilitado}
        </p>
      )}
      {aviso && (
        <p className="soap-diff-aviso" role="status">
          {aviso}
        </p>
      )}
    </div>
  );
}
