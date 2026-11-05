
import { useState } from "react";
import { updateTranscriptionRoles } from "../../services/api";
import type {
  TranscriptionDialogueTurn,
  TranscriptionLogItem,
} from "../shared/types";

type Role = "Médico" | "Paciente" | "Outro";

const validRoles: Role[] = ["Médico", "Paciente", "Outro"];

function normalizeRole(turn: TranscriptionDialogueTurn): Role {
  const role = turn.role?.toLowerCase();

  if (role === "médico" || role === "medico" || role === "doctor") {
    return "Médico";
  }

  if (role === "paciente" || role === "patient") {
    return "Paciente";
  }

  return "Outro";
}

function getBubbleStyle(role: Role): React.CSSProperties {
  const isDoctor = role === "Médico";

  return {
    alignSelf: isDoctor ? "flex-start" : "flex-end",
    backgroundColor:
      role === "Médico"
        ? "#2c3e50"
        : role === "Paciente"
          ? "#27ae60"
          : "#6b5b95",
    color: "#fff",
    padding: "10px 14px",
    borderRadius: "12px",
    maxWidth: "85%",
    width: "fit-content",
    boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
  };
}

export default function TranscriptionViewer({
  log,
  patientId,
  onClose,
  onSaved,
}: {
  log: TranscriptionLogItem;
  patientId: string | null;
  onClose: () => void;
  onSaved: (updatedLog: TranscriptionLogItem) => void;
}) {
  const logDate = new Date(log.timestamp || log.created_at || Date.now());

  const [roles, setRoles] = useState<Role[]>(
    (log.dialogue || []).map(normalizeRole),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function handleSave() {
    if (!patientId || !log.id || !log.dialogue) {
      setError("Não foi possível identificar o paciente ou a transcrição.");
      return;
    }

    if (roles.length !== log.dialogue.length) {
      setError("A quantidade de papéis não corresponde aos turnos.");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      const response = await updateTranscriptionRoles(
        patientId,
        String(log.id),
        roles,
      ) as {
        log?: TranscriptionLogItem;
        transcription?: TranscriptionLogItem;
      };

      const updatedLog = response.log || response.transcription;

      if (!updatedLog) {
        throw new Error("A API não retornou a transcrição atualizada.");
      }

      onSaved(updatedLog);
      setSuccess("Papéis salvos com sucesso.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Erro ao salvar os papéis dos turnos.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        backgroundColor: "#2d2d2d",
        border: "1px solid #444",
        borderRadius: "8px",
        padding: "15px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        minHeight: "400px",
        maxHeight: "600px",
        color: "#fff",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid #555",
          paddingBottom: "10px",
        }}
      >
        <div>
          <div style={{ fontWeight: "bold", fontSize: "0.9em" }}>
            Transcrição de {logDate.toLocaleDateString()}
          </div>
          <div style={{ color: "#aaa", fontSize: "0.8em" }}>
            Horário: {logDate.toLocaleTimeString()} · Duração: {log.duration || "—"}
          </div>
        </div>

        <button onClick={onClose} disabled={saving}>
          Fechar arquivo
        </button>
      </div>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "10px",
          backgroundColor: "#1a1a1a",
          borderRadius: "4px",
          border: "1px solid #333",
          display: "flex",
          flexDirection: "column",
          gap: "10px",
        }}
      >
        {log.dialogue && Array.isArray(log.dialogue) ? (
          log.dialogue.map(
            (turn: TranscriptionDialogueTurn, idx: number) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignSelf: "stretch",
                  alignItems: roles[idx] === "Médico" ? "flex-start" : "flex-end",
                  gap: "5px",
                }}
              >
                <label
                  style={{
                    color: "#ccc",
                    fontSize: "0.8em",
                  }}
                >
                  Papel do turno {idx + 1}
                  <select
                    value={roles[idx]}
                    disabled={saving}
                    onChange={(event) => {
                      const newRole = event.target.value as Role;
                      if (!validRoles.includes(newRole)) return;

                      setRoles((current) =>
                        current.map((role, index) =>
                          index === idx ? newRole : role,
                        ),
                      );
                      setSuccess("");
                      setError("");
                    }}
                    style={{
                      marginLeft: "8px",
                      padding: "4px",
                      borderRadius: "4px",
                    }}
                  >
                    {validRoles.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </label>

                <div style={getBubbleStyle(roles[idx])}>
                  <div
                    style={{
                      fontSize: "0.75em",
                      color: "rgba(255,255,255,0.7)",
                      marginBottom: "4px",
                      fontWeight: "bold",
                      textTransform: "uppercase",
                    }}
                  >
                    {roles[idx]}
                  </div>
                  <div style={{ lineHeight: "1.4", whiteSpace: "pre-wrap" }}>
                    {turn.text}
                  </div>
                </div>
              </div>
            ),
          )
        ) : (
          <div
            style={{
              whiteSpace: "pre-wrap",
              color: "#e0e0e0",
              lineHeight: "1.5",
              fontSize: "0.95em",
            }}
          >
            {log.text || log.text_summary}
          </div>
        )}
      </div>

      {log.dialogue && log.dialogue.length > 0 && (
        <button
          onClick={handleSave}
          disabled={saving || !patientId || !log.id}
          style={{
            padding: "10px",
            backgroundColor: saving ? "#666" : "#1976d2",
            color: "#fff",
            border: "none",
            borderRadius: "5px",
            cursor: saving ? "wait" : "pointer",
          }}
        >
          {saving ? "Salvando..." : "Salvar alterações"}
        </button>
      )}

      {error && (
        <div role="alert" style={{ color: "#ff8a80" }}>
          {error}
        </div>
      )}

      {success && (
        <div role="status" style={{ color: "#81c784" }}>
          {success}
        </div>
      )}

      <div style={{ textAlign: "right", fontSize: "0.75em", color: "#999" }}>
        ID Ref: {log.consultation_id}
      </div>
    </div>
  );
}
