import {
  RECORDING_STATE_KEY,
  normalizeSnapshot,
  type RecordingCommand,
  type RecordingReply,
  type RecordingSnapshot,
} from "./recordingProtocol";

// Lado do popup na gravação (B29): envia comandos ao background.js e acompanha o estado que
// ele guarda em chrome.storage.session. O popup não grava nada — pode fechar à vontade.

/** Envia um comando de gravação. Nunca rejeita: sem resposta vira `ok: false`. */
export function sendRecordingCommand(command: RecordingCommand): Promise<RecordingReply> {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({ ...command, target: "background" }, (reply?: RecordingReply) => {
        if (chrome.runtime.lastError || !reply) {
          resolve({ ok: false, error: "background_unavailable" });
        } else {
          resolve(reply);
        }
      });
    } catch {
      resolve({ ok: false, error: "background_unavailable" });
    }
  });
}

export function readRecordingSnapshot(): Promise<RecordingSnapshot> {
  return new Promise((resolve) => {
    chrome.storage.session.get([RECORDING_STATE_KEY], (stored) =>
      resolve(normalizeSnapshot(stored[RECORDING_STATE_KEY]))
    );
  });
}

/** Avisa a cada mudança do estado da gravação; devolve a função que cancela a inscrição. */
export function watchRecordingSnapshot(onChange: (snapshot: RecordingSnapshot) => void) {
  const listener = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    if (area === "session" && RECORDING_STATE_KEY in changes) {
      onChange(normalizeSnapshot(changes[RECORDING_STATE_KEY].newValue));
    }
  };
  chrome.storage.onChanged.addListener(listener);
  return () => chrome.storage.onChanged.removeListener(listener);
}

/** Estado da permissão do microfone para a extensão ("prompt" se não der para consultar). */
export async function microphonePermission(): Promise<PermissionState> {
  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    return status.state;
  } catch {
    return "prompt";
  }
}

// O pedido de permissão não aparece no popup nem no documento offscreen: abre uma aba da
// extensão (microfone.html) onde o médico autoriza uma única vez.
export function openMicrophonePermissionPage(): void {
  chrome.tabs.create({ url: chrome.runtime.getURL("microfone.html") });
}
