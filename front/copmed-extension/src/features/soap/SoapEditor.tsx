import { useEffect, useRef, useState } from "react";
import { Check, LoaderCircle, Plus, Save, Search, Sparkles, Trash2, X } from "lucide-react";
import {
  ApiError,
  approveSoap,
  generateSoap,
  getSoap,
  saveSoapDoctorVersion,
  searchCid10,
  type Cid10Result,
} from "../../services/api";
import { getErrorMessage, type SoapDocument, type SoapHypothesis, type SoapVersion } from "../shared/types";
import { normalizarCid10 } from "./cid10";
import InsertIntoPepButton from "./InsertIntoPepButton";
import SoapDiff from "./SoapDiff";

// Editor do SOAP na extensão (B43 / US018): gerar pela IA (B40), revisar as quatro
// seções, as hipóteses com CID-10 (busca na tabela embarcada, B42), os alertas e as
// pendências, e aprovar. Toda gravação passa pelo SoapV1 da API (B39): um 400 volta
// com os erros campo a campo. Aprovado, o SOAP fica só leitura e libera o
// "Inserir no prontuário" (B53); a diferença IA x médico vem pronta da API (B44).

const SECOES: { key: "subjetivo" | "objetivo" | "avaliacao" | "plano"; label: string }[] = [
  { key: "subjetivo", label: "Subjetivo" },
  { key: "objetivo", label: "Objetivo" },
  { key: "avaliacao", label: "Avaliação" },
  { key: "plano", label: "Plano" },
];

const STATUS: Record<SoapDocument["status"], string> = {
  gerado: "Gerado pela IA",
  editado: "Editado pelo médico",
  aprovado: "Aprovado",
  inserido_no_pep: "Inserido no prontuário",
};

// Tira linhas e hipóteses em branco antes de gravar: o SoapV1 recusa itens vazios.
function paraGravar(soap: SoapVersion): SoapVersion {
  const limpar = (itens: string[]) => itens.map((item) => item.trim()).filter(Boolean);
  return {
    ...soap,
    hipoteses: soap.hipoteses
      .map((h) => ({ ...h, descricao: h.descricao.trim() }))
      .filter((h) => h.descricao || h.cid10),
    alertas: limpar(soap.alertas),
    pendencias: limpar(soap.pendencias),
  };
}

type Busy = "carregar" | "gerar" | "salvar" | "aprovar" | null;

type Props = {
  consultationId: string | null;
  /** Nome do paciente da consulta, para conferir com o PEP antes de inserir. */
  patientName: string | null;
};

export default function SoapEditor({ consultationId, patientName }: Props) {
  const [soap, setSoap] = useState<SoapDocument | null>(null);
  const [draft, setDraft] = useState<SoapVersion | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<{ message: string; errors: string[] } | null>(null);
  const [notice, setNotice] = useState("");
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => {
    let ativo = true;
    setSoap(null);
    setDraft(null);
    setError(null);
    setNotice("");
    setShowDiff(false);
    setBusy(null);
    if (!consultationId) return;
    setBusy("carregar");
    getSoap(consultationId)
      .then(({ soap: atual }) => {
        if (!ativo) return;
        setSoap(atual);
        setDraft(atual ? atual.atual : null);
      })
      .catch((erro: unknown) => ativo && setError({ message: getErrorMessage(erro, "Falha ao carregar o SOAP."), errors: [] }))
      .finally(() => ativo && setBusy(null));
    return () => {
      ativo = false;
    };
  }, [consultationId]);

  if (!consultationId) return null;

  const somenteLeitura = soap?.status === "aprovado" || soap?.status === "inserido_no_pep";
  const bloqueado = somenteLeitura || busy !== null;
  const alterado = Boolean(soap && draft && JSON.stringify(draft) !== JSON.stringify(soap.atual));

  function mostrar(documento: SoapDocument) {
    setSoap(documento);
    setDraft(documento.atual);
  }

  function falhou(erro: unknown, padrao: string) {
    setError({
      message: getErrorMessage(erro, padrao),
      errors: erro instanceof ApiError ? erro.errors : [],
    });
  }

  function editar(mudanca: (atual: SoapVersion) => SoapVersion) {
    setDraft((atual) => (atual ? mudanca(atual) : atual));
    setNotice("");
  }

  function editarHipotese(indice: number, mudanca: Partial<SoapHypothesis>) {
    editar((atual) => ({
      ...atual,
      hipoteses: atual.hipoteses.map((h, i) => (i === indice ? { ...h, ...mudanca } : h)),
    }));
  }

  async function executar<T>(etapa: Exclude<Busy, null>, acao: () => Promise<T>, padrao: string) {
    setBusy(etapa);
    setError(null);
    setNotice("");
    try {
      return await acao();
    } catch (erro) {
      falhou(erro, padrao);
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function gerar() {
    const resposta = await executar("gerar", () => generateSoap(consultationId!), "Falha ao gerar o SOAP.");
    if (!resposta) return;
    mostrar(resposta.soap);
    setShowDiff(false);
    setNotice("SOAP gerado. Revise antes de aprovar.");
  }

  async function salvar(): Promise<SoapDocument | null> {
    if (!soap || !draft) return null;
    const resposta = await executar(
      "salvar",
      () => saveSoapDoctorVersion(consultationId!, soap.id, paraGravar(draft)),
      "Falha ao salvar o SOAP.",
    );
    if (!resposta) return null;
    mostrar(resposta.soap);
    setNotice("Alterações salvas.");
    return resposta.soap;
  }

  async function aprovar() {
    if (!soap) return;
    // Aprova o que está na tela: se o médico editou, grava antes.
    const documento = alterado ? await salvar() : soap;
    if (!documento) return;
    const resposta = await executar("aprovar", () => approveSoap(consultationId!, documento.id), "Falha ao aprovar o SOAP.");
    if (!resposta) return;
    mostrar(resposta.soap);
    setNotice("SOAP aprovado. Agora ele pode ser inserido no prontuário.");
  }

  return (
    <section className="soap-editor" aria-label="Editor SOAP">
      <div className="soap-editor__header">
        <div>
          <h2>Registro SOAP</h2>
          {soap && <span className="soap-editor__status">{STATUS[soap.status]}</span>}
        </div>
        {!somenteLeitura && busy !== "carregar" && (
          <button
            type="button"
            className="soap-button soap-button--primary"
            onClick={gerar}
            disabled={busy !== null || alterado}
            title={alterado ? "Salve ou descarte as alterações antes de gerar de novo." : undefined}
          >
            {busy === "gerar" ? <LoaderCircle size={16} className="soap-spin" /> : <Sparkles size={16} />}
            {soap ? "Gerar de novo" : "Gerar SOAP"}
          </button>
        )}
      </div>

      {error && (
        <div className="soap-editor__message soap-editor__message--error" role="alert">
          <p>{error.message}</p>
          {error.errors.length > 0 && (
            <ul>
              {error.errors.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {notice && (
        <p className="soap-editor__message" role="status">
          {notice}
        </p>
      )}
      {busy === "carregar" && <p className="soap-editor__empty">Carregando o SOAP...</p>}
      {busy === "gerar" && <p className="soap-editor__empty">Gerando o SOAP a partir da consulta...</p>}
      {!soap && busy === null && !error && (
        <p className="soap-editor__empty">
          Gere um rascunho a partir da transcrição, do prontuário e do chat desta consulta.
        </p>
      )}

      {soap && draft && (
        <>
          <div className="soap-editor__sections">
            {SECOES.map(({ key, label }) => (
              <label className="soap-field" key={key}>
                <span>{label}</span>
                <textarea
                  value={draft[key]}
                  disabled={bloqueado}
                  rows={3}
                  onChange={(event) => editar((atual) => ({ ...atual, [key]: event.target.value }))}
                />
              </label>
            ))}
          </div>

          <div className="soap-editor__subsection">
            <div className="soap-editor__subheader">
              <h3>Hipóteses e CID-10</h3>
              {!somenteLeitura && (
                <button
                  type="button"
                  className="soap-icon-button"
                  aria-label="Adicionar hipótese"
                  title="Adicionar hipótese"
                  disabled={bloqueado}
                  onClick={() =>
                    editar((atual) => ({
                      ...atual,
                      hipoteses: [...atual.hipoteses, { descricao: "", cid10: null, confianca: "baixa" }],
                    }))
                  }
                >
                  <Plus size={16} />
                </button>
              )}
            </div>
            {draft.hipoteses.length === 0 && <p className="soap-editor__empty">Nenhuma hipótese.</p>}
            {draft.hipoteses.map((hipotese, indice) => (
              <div className="soap-hypothesis" key={indice}>
                <input
                  aria-label={`Descrição da hipótese ${indice + 1}`}
                  placeholder="Descrição"
                  value={hipotese.descricao}
                  disabled={bloqueado}
                  onChange={(event) => editarHipotese(indice, { descricao: event.target.value })}
                />
                <div className="soap-hypothesis__row">
                  <CidField
                    indice={indice}
                    value={hipotese.cid10}
                    disabled={bloqueado}
                    onSelect={(item) =>
                      editarHipotese(indice, {
                        cid10: item ? item.code : null,
                        // Sem descrição, usa a da tabela
                        ...(item && !hipotese.descricao.trim() ? { descricao: item.description } : {}),
                      })
                    }
                  />
                  <select
                    aria-label={`Confiança da hipótese ${indice + 1}`}
                    value={hipotese.confianca}
                    disabled={bloqueado}
                    onChange={(event) =>
                      editarHipotese(indice, { confianca: event.target.value as SoapHypothesis["confianca"] })
                    }
                  >
                    <option value="baixa">Confiança baixa</option>
                    <option value="media">Confiança média</option>
                    <option value="alta">Confiança alta</option>
                  </select>
                  {!somenteLeitura && (
                    <button
                      type="button"
                      className="soap-icon-button"
                      aria-label={`Remover hipótese ${indice + 1}`}
                      title="Remover hipótese"
                      disabled={bloqueado}
                      onClick={() =>
                        editar((atual) => ({ ...atual, hipoteses: atual.hipoteses.filter((_, i) => i !== indice) }))
                      }
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <ListaEditavel
            titulo="Alertas"
            item="alerta"
            itens={draft.alertas}
            disabled={bloqueado}
            somenteLeitura={somenteLeitura}
            onChange={(alertas) => editar((atual) => ({ ...atual, alertas }))}
          />
          <ListaEditavel
            titulo="Pendências"
            item="pendência"
            itens={draft.pendencias}
            disabled={bloqueado}
            somenteLeitura={somenteLeitura}
            onChange={(pendencias) => editar((atual) => ({ ...atual, pendencias }))}
          />

          <div className="soap-editor__actions">
            {soap.diff && (
              <button type="button" className="soap-button" onClick={() => setShowDiff((v) => !v)}>
                {showDiff ? "Ocultar alterações" : "Ver alterações (IA x médico)"}
              </button>
            )}
            {!somenteLeitura && (
              <>
                <button
                  type="button"
                  className="soap-button"
                  onClick={() => {
                    setDraft(soap.atual);
                    setError(null);
                  }}
                  disabled={busy !== null || !alterado}
                >
                  <X size={15} /> Descartar
                </button>
                <button type="button" className="soap-button" onClick={salvar} disabled={busy !== null || !alterado}>
                  {busy === "salvar" ? <LoaderCircle size={15} className="soap-spin" /> : <Save size={15} />} Salvar
                </button>
              </>
            )}
            <button
              type="button"
              className="soap-button soap-button--approve"
              onClick={aprovar}
              disabled={busy !== null || somenteLeitura}
            >
              {busy === "aprovar" ? <LoaderCircle size={16} className="soap-spin" /> : <Check size={16} />}{" "}
              {somenteLeitura ? "Aprovado" : "Aprovar"}
            </button>
          </div>

          {showDiff && soap.diff && (
            <div className="soap-editor__diff">
              <SoapDiff diff={soap.diff} />
            </div>
          )}

          {somenteLeitura && (
            <InsertIntoPepButton
              consultationId={consultationId}
              pacienteSelecionado={patientName}
              soap={soap}
              onInserted={mostrar}
            />
          )}
        </>
      )}
    </section>
  );
}

// Campo CID-10 de uma hipótese: busca na tabela da API enquanto o médico digita
// e grava só um código válido (escolhido na lista ou digitado no formato G44.2).
function CidField({
  indice,
  value,
  disabled,
  onSelect,
}: {
  indice: number;
  value: string | null;
  disabled: boolean;
  onSelect: (item: Cid10Result | null) => void;
}) {
  const [query, setQuery] = useState(value || "");
  const [focado, setFocado] = useState(false);
  const [results, setResults] = useState<Cid10Result[]>([]);
  const [semResultado, setSemResultado] = useState(false);
  const ultima = useRef("");

  useEffect(() => {
    if (!focado) setQuery(value || "");
  }, [value, focado]);

  useEffect(() => {
    const termo = query.trim();
    if (!focado || termo.length < 2 || termo === value) {
      setResults([]);
      setSemResultado(false);
      return;
    }
    let ativo = true;
    ultima.current = termo;
    const espera = window.setTimeout(() => {
      searchCid10(termo)
        .then(({ results: encontrados }) => {
          if (!ativo || ultima.current !== termo) return;
          setResults(encontrados);
          setSemResultado(encontrados.length === 0);
        })
        .catch(() => ativo && setResults([]));
    }, 250);
    return () => {
      ativo = false;
      window.clearTimeout(espera);
    };
  }, [query, focado, value]);

  function escolher(item: Cid10Result) {
    onSelect(item);
    setQuery(item.code);
    setResults([]);
    setFocado(false);
  }

  function sair() {
    setFocado(false);
    setResults([]);
    const termo = query.trim();
    if (!termo) {
      if (value) onSelect(null);
      return;
    }
    // Texto que não é código e não foi escolhido na lista: volta ao valor gravado.
    const codigo = normalizarCid10(termo);
    if (codigo && codigo !== value) onSelect({ code: codigo, description: "" });
    setQuery(codigo || value || "");
  }

  const listaId = `soap-cid-resultados-${indice}`;
  return (
    <div className="soap-cid-search">
      <div className="soap-cid-search__input">
        <Search size={14} aria-hidden="true" />
        <input
          aria-label={`CID-10 da hipótese ${indice + 1}`}
          aria-controls={results.length ? listaId : undefined}
          aria-expanded={results.length > 0}
          role="combobox"
          aria-autocomplete="list"
          placeholder="CID-10"
          value={query}
          disabled={disabled}
          onFocus={() => setFocado(true)}
          onBlur={sair}
          onChange={(event) => {
            setFocado(true);
            setQuery(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setResults([]);
            if (event.key === "Enter" && results.length) {
              event.preventDefault();
              escolher(results[0]);
            }
          }}
        />
      </div>
      {focado && results.length > 0 && (
        <ul className="soap-cid-search__results" id={listaId} role="listbox">
          {results.map((item) => (
            <li key={item.code} role="option" aria-selected={item.code === value}>
              <button
                type="button"
                // mousedown antes do blur do campo: o clique não se perde
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => escolher(item)}
              >
                <strong>{item.code}</strong> {item.description}
              </button>
            </li>
          ))}
        </ul>
      )}
      {focado && semResultado && <p className="soap-cid-search__vazio">Nenhum código encontrado.</p>}
    </div>
  );
}

// Alertas e pendências: um item por campo, com adicionar e remover.
function ListaEditavel({
  titulo,
  item,
  itens,
  disabled,
  somenteLeitura,
  onChange,
}: {
  titulo: string;
  item: string;
  itens: string[];
  disabled: boolean;
  somenteLeitura: boolean;
  onChange: (itens: string[]) => void;
}) {
  return (
    <div className="soap-editor__subsection" role="group" aria-label={titulo}>
      <div className="soap-editor__subheader">
        <h3>{titulo}</h3>
        {!somenteLeitura && (
          <button
            type="button"
            className="soap-icon-button"
            aria-label={`Adicionar ${item}`}
            title={`Adicionar ${item}`}
            disabled={disabled}
            onClick={() => onChange([...itens, ""])}
          >
            <Plus size={16} />
          </button>
        )}
      </div>
      {itens.length === 0 && <p className="soap-editor__empty">Nenhum item.</p>}
      {itens.map((texto, indice) => (
        <div className="soap-list-item" key={indice}>
          <input
            aria-label={`${titulo}: item ${indice + 1}`}
            value={texto}
            disabled={disabled}
            onChange={(event) => onChange(itens.map((t, i) => (i === indice ? event.target.value : t)))}
          />
          {!somenteLeitura && (
            <button
              type="button"
              className="soap-icon-button"
              aria-label={`Remover ${item} ${indice + 1}`}
              title={`Remover ${item}`}
              disabled={disabled}
              onClick={() => onChange(itens.filter((_, i) => i !== indice))}
            >
              <Trash2 size={15} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
