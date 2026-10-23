import { useEffect, useState } from "react";
import { Check, LoaderCircle, Plus, Save, Search, Sparkles, Trash2 } from "lucide-react";
import {
  approveConsultationSoap,
  generateConsultationSoap,
  getConsultationSoap,
  searchCid10,
  updateConsultationSoap,
} from "../../services/api";
import type { SoapDocument, SoapV1 } from "../shared/types";

const SECTIONS: { key: keyof Pick<SoapV1, "subjetivo" | "objetivo" | "avaliacao" | "plano">; label: string }[] = [
  { key: "subjetivo", label: "Subjetivo" },
  { key: "objetivo", label: "Objetivo" },
  { key: "avaliacao", label: "Avaliação" },
  { key: "plano", label: "Plano" },
];

function contentOf(document: SoapDocument): SoapV1 {
  return document.versao_medico || document.versao_ia;
}

export default function SoapEditor({ consultationId }: { consultationId: string | null }) {
  const [document, setDocument] = useState<SoapDocument | null>(null);
  const [draft, setDraft] = useState<SoapV1 | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cidQuery, setCidQuery] = useState("");
  const [cidSearchIndex, setCidSearchIndex] = useState<number | null>(null);
  const [cidResults, setCidResults] = useState<{ code: string; description: string }[]>([]);

  useEffect(() => {
    let cancelled = false;
    setDocument(null);
    setDraft(null);
    setError("");
    setNotice("");
    if (consultationId) {
      getConsultationSoap(consultationId)
        .then(({ soap }) => {
          if (!cancelled && soap) {
            setDocument(soap);
            setDraft(contentOf(soap));
          }
        })
        .catch((loadError: unknown) => {
          if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Falha ao carregar SOAP.");
        });
    }
    return () => {
      cancelled = true;
    };
  }, [consultationId]);

  useEffect(() => {
    let cancelled = false;
    if (cidQuery.trim().length < 2) {
      setCidResults([]);
      return;
    }
    const timeout = window.setTimeout(() => {
      searchCid10(cidQuery)
        .then(({ results }) => {
          if (!cancelled) setCidResults(results);
        })
        .catch(() => {
          if (!cancelled) setCidResults([]);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [cidQuery]);

  if (!consultationId) return null;

  const isApproved = document?.status === "aprovado" || document?.status === "inserido_no_pep";
  const original = document ? contentOf(document) : null;
  const isDirty = Boolean(draft && original && JSON.stringify(draft) !== JSON.stringify(original));

  function updateDraft(change: (current: SoapV1) => SoapV1) {
    setDraft((current) => current ? change(current) : current);
    setNotice("");
  }

  async function generate() {
    if (!consultationId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await generateConsultationSoap(consultationId);
      setDocument(result.soap);
      setDraft(result.soap.versao_ia);
      setNotice("SOAP gerado. Revise antes de aprovar.");
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : "Falha ao gerar SOAP.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft(): Promise<SoapDocument | null> {
    if (!consultationId || !document || !draft) return null;
    setBusy(true);
    setError("");
    try {
      const result = await updateConsultationSoap(consultationId, document.id, draft);
      setDocument(result.soap);
      setDraft(contentOf(result.soap));
      setNotice("Alterações salvas.");
      return result.soap;
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Falha ao salvar SOAP.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!consultationId || !document) return;
    let currentDocument = document;
    if (isDirty) {
      const saved = await saveDraft();
      if (!saved) return;
      currentDocument = saved;
    }
    setBusy(true);
    setError("");
    try {
      const result = await approveConsultationSoap(consultationId, currentDocument.id);
      setDocument(result.soap);
      setDraft(contentOf(result.soap));
      setNotice("SOAP aprovado.");
    } catch (approveError) {
      setError(approveError instanceof Error ? approveError.message : "Falha ao aprovar SOAP.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="soap-editor" aria-label="Editor SOAP">
      <div className="soap-editor__header">
        <div>
          <h2>Registro SOAP</h2>
          {document && <span className="soap-editor__status">{document.status}</span>}
        </div>
        {!document && (
          <button className="soap-button soap-button--primary" onClick={generate} disabled={busy}>
            {busy ? <LoaderCircle size={16} className="soap-spin" /> : <Sparkles size={16} />}
            Gerar SOAP
          </button>
        )}
      </div>

      {error && <p className="soap-editor__message soap-editor__message--error" role="alert">{error}</p>}
      {notice && <p className="soap-editor__message" role="status">{notice}</p>}
      {busy && !document && <p className="soap-editor__loading">Preparando registro...</p>}

      {!document && !busy && !error && (
        <p className="soap-editor__empty">Gere um rascunho a partir da consulta para revisar.</p>
      )}

      {draft && document && (
        <>
          <div className="soap-editor__sections">
            {SECTIONS.map(({ key, label }) => (
              <label className="soap-field" key={key}>
                <span>{label}</span>
                <textarea
                  aria-label={label}
                  value={draft[key]}
                  disabled={isApproved || busy}
                  onChange={(event) => updateDraft((current) => ({ ...current, [key]: event.target.value }))}
                  rows={3}
                />
              </label>
            ))}
          </div>

          <div className="soap-editor__subsection">
            <div className="soap-editor__subheader">
              <h3>Hipóteses e CID-10</h3>
              {!isApproved && (
                <button
                  className="soap-icon-button"
                  title="Adicionar hipótese"
                  aria-label="Adicionar hipótese"
                  onClick={() => updateDraft((current) => ({
                    ...current,
                    hipoteses: [...current.hipoteses, { descricao: "", cid10: null, confianca: "baixa" }],
                  }))}
                >
                  <Plus size={16} />
                </button>
              )}
            </div>
            {draft.hipoteses.map((hypothesis, index) => (
              <div className="soap-hypothesis" key={`${index}-${hypothesis.cid10 || "new"}`}>
                <input
                  aria-label={`Descrição da hipótese ${index + 1}`}
                  value={hypothesis.descricao}
                  placeholder="Descrição"
                  disabled={isApproved || busy}
                  onChange={(event) => updateDraft((current) => ({
                    ...current,
                    hipoteses: current.hipoteses.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, descricao: event.target.value } : item
                    ),
                  }))}
                />
                <div className="soap-cid-search">
                  <div className="soap-cid-search__input">
                    <Search size={14} />
                    <input
                      aria-label={`Buscar CID-10 para hipótese ${index + 1}`}
                      value={cidSearchIndex === index ? cidQuery : hypothesis.cid10 || ""}
                      placeholder="CID-10"
                      disabled={isApproved || busy}
                      onFocus={() => {
                        setCidSearchIndex(index);
                        setCidQuery(hypothesis.cid10 || "");
                      }}
                      onChange={(event) => {
                        setCidSearchIndex(index);
                        setCidQuery(event.target.value);
                        updateDraft((current) => ({
                          ...current,
                          hipoteses: current.hipoteses.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, cid10: event.target.value || null } : item
                          ),
                        }));
                      }}
                    />
                  </div>
                  {cidSearchIndex === index && cidResults.length > 0 && !isApproved && (
                    <ul className="soap-cid-search__results">
                      {cidResults.map((result) => (
                        <li key={result.code}>
                          <button
                            type="button"
                            onClick={() => {
                              updateDraft((current) => ({
                                ...current,
                                hipoteses: current.hipoteses.map((item, itemIndex) =>
                                  itemIndex === index ? { ...item, cid10: result.code } : item
                                ),
                              }));
                              setCidQuery(result.code);
                              setCidResults([]);
                            }}
                          >
                            <strong>{result.code}</strong> {result.description}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <select
                  aria-label={`Confiança da hipótese ${index + 1}`}
                  value={hypothesis.confianca}
                  disabled={isApproved || busy}
                  onChange={(event) => updateDraft((current) => ({
                    ...current,
                    hipoteses: current.hipoteses.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, confianca: event.target.value as typeof item.confianca } : item
                    ),
                  }))}
                >
                  <option value="baixa">Baixa</option>
                  <option value="media">Média</option>
                  <option value="alta">Alta</option>
                </select>
                {!isApproved && (
                  <button
                    className="soap-icon-button"
                    title="Remover hipótese"
                    aria-label={`Remover hipótese ${index + 1}`}
                    onClick={() => updateDraft((current) => ({
                      ...current,
                      hipoteses: current.hipoteses.filter((_, itemIndex) => itemIndex !== index),
                    }))}
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </div>
            ))}
          </div>

          <label className="soap-field">
            <span>Alertas</span>
            <textarea
              aria-label="Alertas"
              value={draft.alertas.join("\n")}
              disabled={isApproved || busy}
              onChange={(event) => updateDraft((current) => ({
                ...current,
                alertas: event.target.value.split("\n").filter(Boolean),
              }))}
              rows={2}
              placeholder="Um alerta por linha"
            />
          </label>
          <label className="soap-field">
            <span>Pendências</span>
            <textarea
              aria-label="Pendências"
              value={draft.pendencias.join("\n")}
              disabled={isApproved || busy}
              onChange={(event) => updateDraft((current) => ({
                ...current,
                pendencias: event.target.value.split("\n").filter(Boolean),
              }))}
              rows={2}
              placeholder="Uma pendência por linha"
            />
          </label>

          <div className="soap-editor__actions">
            {!isApproved && (
              <button className="soap-button" onClick={saveDraft} disabled={busy || !isDirty}>
                <Save size={15} /> Salvar
              </button>
            )}
            <button
              className="soap-button soap-button--approve"
              onClick={approve}
              disabled={busy || isApproved}
            >
              <Check size={16} /> {isApproved ? "Aprovado" : "Aprovar"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}