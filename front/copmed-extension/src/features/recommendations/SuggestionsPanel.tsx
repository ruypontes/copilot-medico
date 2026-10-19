import { SUGGESTION_WINDOWS, useSuggestions } from "./useSuggestions";

// Botão "Sugestões" da aba de gravação (B38 / US020-CA003): até 5 itens curtos sobre os
// últimos N minutos transcritos. O resultado é só exibido, nunca gravado no prontuário.

const TIPO_LABEL: Record<string, string> = {
  pergunta: "❓ Pergunta",
  exame: "🩺 Exame",
  diferencial: "🔀 Diferencial",
  alerta: "⚠️ Alerta",
  outro: "💡 Sugestão",
};

type Props = { patientId: string | null; consultationId: string | null };

export default function SuggestionsPanel({ patientId, consultationId }: Props) {
  const {
    items,
    info,
    error,
    loading,
    requested,
    windowMinutes,
    setWindowMinutes,
    requestSuggestions,
    clear,
  } = useSuggestions(patientId, consultationId);

  const disabled = loading || !patientId || !consultationId;

  return (
    <section
      aria-label="Sugestões da consulta"
      style={{ display: "flex", flexDirection: "column", gap: "8px", padding: "0 10px" }}
    >
      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
        <button
          type="button"
          onClick={requestSuggestions}
          disabled={disabled}
          style={{
            flex: 1,
            padding: "8px 12px",
            backgroundColor: disabled ? "#cccccc" : "#7B4FBF",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "⏳ Gerando sugestões..." : "💡 Sugestões"}
        </button>
        <label
          className="suggestions-window"
          style={{ fontSize: "0.85em", display: "flex", alignItems: "center", gap: "4px" }}
        >
          últimos
          <select
            aria-label="Janela das sugestões em minutos"
            value={windowMinutes}
            onChange={(event) => setWindowMinutes(Number(event.target.value))}
            disabled={loading}
          >
            {SUGGESTION_WINDOWS.map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} min
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <div role="alert" style={{ color: "#e66060", fontSize: "0.85em" }}>
          {error}
        </div>
      )}
      {info && <div style={{ color: "#888", fontSize: "0.85em" }}>{info}</div>}

      {items.length > 0 && (
        <div className="suggestions-box" style={{ borderRadius: "6px", padding: "8px" }}>
          <ul style={{ margin: 0, paddingLeft: "4px", listStyle: "none" }}>
            {items.map((item, index) => (
              <li key={`${index}-${item.texto}`} style={{ marginBottom: "6px", fontSize: "0.9em" }}>
                <strong style={{ marginRight: "6px" }}>{TIPO_LABEL[item.tipo] ?? TIPO_LABEL.outro}</strong>
                {item.texto}
              </li>
            ))}
          </ul>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <small className="suggestions-note">
              Apoio à decisão: valide clinicamente. Não é gravado no prontuário.
            </small>
            <button type="button" onClick={clear} style={{ fontSize: "0.8em" }}>
              Fechar
            </button>
          </div>
        </div>
      )}
      {requested && !loading && !error && !info && items.length === 0 && (
        <div style={{ color: "#888", fontSize: "0.85em" }}>Nenhuma sugestão no momento.</div>
      )}
    </section>
  );
}
