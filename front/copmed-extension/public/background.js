// Mesmas chaves de src/services/api.ts. O token mora em chrome.storage.session (memoria,
// apagado ao fechar o navegador); o API_URL e publicado pelo popup em chrome.storage.local.
const TOKEN_KEY = 'copmed_extension_token';
const SESSION_KEYS = [TOKEN_KEY, 'copmed_extension_user', 'copmed_extension_profile'];
const API_URL_KEY = 'copmed_api_url';
const DEFAULT_API_URL = 'http://localhost:3001';

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'SEND_COMBINED_DATA') {
    chrome.storage.local.get(
      ['patientId', 'consultationId', 'copilotMedicoPatientId', API_URL_KEY],
      (storageResult) => {
        chrome.storage.session.get([TOKEN_KEY], (sessionResult) => {
          const legacyPatientId = storageResult.copilotMedicoPatientId;
          const currentPatientId = storageResult.patientId || legacyPatientId;
          const currentConsultationId = storageResult.consultationId || null;
          const apiUrl = storageResult[API_URL_KEY] || DEFAULT_API_URL;
          const token = sessionResult[TOKEN_KEY];

          if (!currentPatientId) {
            const errorMessage = 'patientId nao encontrado no armazenamento. Selecione um paciente e tente novamente.';
            console.error(errorMessage);
            sendResponse({ status: 'error', message: errorMessage });
            return;
          }

          if (!token) {
            const errorMessage = 'Sessao nao encontrada. Abra a extensao e entre novamente.';
            console.error(errorMessage);
            sendResponse({ status: 'error', code: 'session_expired', message: errorMessage });
            return;
          }

          const sourceUrl = request.source_url || sender?.tab?.url || null;
          const payload = {
            patient_id: currentPatientId,
            consultation_id: currentConsultationId,
            source_url: sourceUrl,
            extracted_content: request.extracted_content,
          };

          fetch(`${apiUrl}/api/extension/extracted-data`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(payload),
          })
            .then((response) => {
              if (response.status === 401) {
                // mesmo tratamento do popup: sessao invalida -> limpa e pede novo login
                chrome.storage.session.remove(SESSION_KEYS);
                sendResponse({
                  status: 'error',
                  code: 'session_expired',
                  message: 'Sessao expirada. Abra a extensao e entre novamente.',
                });
                return null;
              }
              return response.json();
            })
            .then((data) => {
              if (!data) return;
              console.log('Resposta do servidor:', data);

              if (data.patient_id && data.patient_id !== currentPatientId) {
                chrome.storage.local.set({ patientId: data.patient_id });
              }
              if (data.consultation_id && data.consultation_id !== currentConsultationId) {
                chrome.storage.local.set({ consultationId: data.consultation_id });
              }

              sendResponse(data);
            })
            .catch((error) => {
              console.error('Erro no fetch para a API:', error);
              sendResponse({ status: 'error', message: error.message });
            });
        });
      }
    );

    return true; // manter a comunicação aberta para a resposta assíncrona.
  }
});

// ---------------------------------------------------------------------------
// Botao flutuante do PEP (B52)
//
// O content script (src/content/main.ts) le as notas pelo adaptador do PEP
// detectado e manda aqui; o envio vai para a consulta selecionada no popup, na
// mesma rota tipada do botao "Extrair Dados da Pagina" (pep-import).
// ---------------------------------------------------------------------------
async function importarDoPep(message, sender) {
  const local = await chrome.storage.local.get(['consultationId', API_URL_KEY]);
  const session = await chrome.storage.session.get([TOKEN_KEY]);
  const token = session[TOKEN_KEY];
  if (!token) return { ok: false, mensagem: 'Entre na extensao primeiro' };
  if (!local.consultationId) return { ok: false, mensagem: 'Selecione paciente e consulta na extensao' };
  // O content script conferiu o paciente do PEP com a consulta que leu no clique: se a
  // selecao mudou desde entao, a conferencia nao vale para a consulta de agora.
  if (message.consultation_id !== local.consultationId) {
    return { ok: false, mensagem: 'A consulta selecionada mudou: confira e envie de novo' };
  }

  const apiUrl = local[API_URL_KEY] || DEFAULT_API_URL;
  const response = await fetch(
    `${apiUrl}/api/consultations/${encodeURIComponent(local.consultationId)}/pep-import`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        pep_origem: message.pep_origem,
        source_url: message.source_url || sender.tab?.url || null,
        campos: message.campos,
      }),
    }
  );
  if (response.status === 401) {
    await chrome.storage.session.remove(SESSION_KEYS);
    return { ok: false, mensagem: 'Sessao expirada: entre de novo' };
  }
  const data = await response.json().catch(() => ({}));
  // So a mensagem da API volta ao botao: nunca o conteudo enviado.
  return response.ok ? { ok: true } : { ok: false, mensagem: data.message || 'Nao foi possivel enviar' };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'pep:import') return;
  // Vem do nosso content script, que roda so nos dominios dos PEPs (manifest).
  if (sender.id !== chrome.runtime.id || !sender.tab) {
    sendResponse({ ok: false, mensagem: 'forbidden' });
    return;
  }
  importarDoPep(message, sender).then(sendResponse, (error) => {
    console.error('Erro ao enviar dados do PEP:', error?.name || error);
    sendResponse({ ok: false, mensagem: 'Sem conexao com a API' });
  });
  return true; // resposta assincrona
});

// ---------------------------------------------------------------------------
// Gravacao da consulta (B29/B30)
//
// Quem grava e o documento offscreen (src/offscreen/main.ts): o popup e destruido ao fechar
// e levaria o MediaRecorder junto. Este service worker cria/fecha esse documento, repassa os
// comandos do popup e guarda o estado da gravacao em chrome.storage.session - e de la que o
// popup o le ao reabrir. As chaves e mensagens espelham
// src/features/recording/recordingProtocol.ts.
// ---------------------------------------------------------------------------
const RECORDING_STATE_KEY = 'copmed_recording_state';
const OFFSCREEN_URL = 'offscreen.html';
const IDLE_RECORDING = {
  status: 'idle',
  recordingId: null,
  patientId: null,
  consultationId: null,
  accumulatedMs: 0,
  resumedAt: null,
  chunksSent: 0,
  chunksPending: 0,
  chunksRejected: 0,
  warning: null,
  result: null,
};

let creatingOffscreen = null;

async function hasOffscreenDocument() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_URL)],
  });
  return contexts.length > 0;
}

async function ensureOffscreenDocument() {
  if (await hasOffscreenDocument()) return;
  // Dois comandos seguidos nao podem criar dois documentos: o Chrome so permite um.
  if (!creatingOffscreen) {
    creatingOffscreen = chrome.offscreen
      .createDocument({
        url: OFFSCREEN_URL,
        reasons: ['USER_MEDIA'],
        justification: 'Gravar o audio da consulta enquanto o popup da extensao esta fechado.',
      })
      .finally(() => {
        creatingOffscreen = null;
      });
  }
  await creatingOffscreen;
}

async function closeOffscreenDocument() {
  if (await hasOffscreenDocument()) {
    await chrome.offscreen.closeDocument().catch(() => {});
  }
}

async function readRecordingState() {
  const stored = await chrome.storage.session.get([RECORDING_STATE_KEY]);
  return stored[RECORDING_STATE_KEY] || IDLE_RECORDING;
}

function writeRecordingState(snapshot) {
  return chrome.storage.session.set({ [RECORDING_STATE_KEY]: snapshot });
}

function sendToOffscreen(message) {
  return chrome.runtime.sendMessage({ ...message, target: 'offscreen' });
}

// Repassa um comando ao documento offscreen e guarda o estado que ele devolve.
async function forwardToOffscreen(type) {
  if (!(await hasOffscreenDocument())) return reconcileRecordingState();
  const reply = await sendToOffscreen({ type });
  if (reply?.snapshot) await writeRecordingState(reply.snapshot);
  return reply;
}

// Sem documento offscreen nao ha gravacao em curso: se o estado guardado diz o contrario
// (o documento caiu), volta para "idle" em vez de mostrar um cronometro que nao grava nada.
async function reconcileRecordingState() {
  const stored = await readRecordingState();
  if (stored.status === 'idle') return { ok: true, snapshot: stored };
  const snapshot = { ...IDLE_RECORDING, result: stored.result || null };
  await writeRecordingState(snapshot);
  return { ok: true, snapshot };
}

async function startRecording(message) {
  if (!message.patientId || !message.consultationId) return { ok: false, error: 'invalid' };
  await ensureOffscreenDocument();
  const reply = await sendToOffscreen({
    type: 'start',
    patientId: message.patientId,
    consultationId: message.consultationId,
  });
  if (reply?.ok) {
    await writeRecordingState(reply.snapshot);
  } else if (reply?.error !== 'already_recording') {
    await closeOffscreenDocument(); // microfone negado: nada para manter aberto
  }
  return reply || { ok: false, error: 'offscreen_error' };
}

async function handleRecordingMessage(message) {
  switch (message.type) {
    // --- do documento offscreen ---
    case 'recording:state':
      await writeRecordingState(message.snapshot);
      // "idle" = gravacao encerrada (o resultado ja esta no estado): libera o documento.
      if (message.snapshot.status === 'idle') await closeOffscreenDocument();
      return { ok: true };
    case 'recording:get-token': {
      // Documentos offscreen nao tem acesso ao chrome.storage: o token e pedido aqui a cada
      // envio, entao um novo login vale tambem para as partes que aguardam reenvio.
      const session = await chrome.storage.session.get([TOKEN_KEY]);
      return { ok: true, token: session[TOKEN_KEY] || null };
    }

    // --- do popup ---
    case 'recording:start':
      return startRecording(message);
    case 'recording:pause':
      return forwardToOffscreen('pause');
    case 'recording:resume':
      return forwardToOffscreen('resume');
    case 'recording:stop':
      return forwardToOffscreen('stop');
    case 'recording:sync':
      return forwardToOffscreen('get-state');
    case 'recording:cancel':
      if (await hasOffscreenDocument()) {
        await sendToOffscreen({ type: 'cancel' }).catch(() => {});
        await closeOffscreenDocument();
      }
      await writeRecordingState(IDLE_RECORDING);
      return { ok: true, snapshot: IDLE_RECORDING };
    case 'recording:ack-result': {
      // O popup ja entregou a transcricao ao chat: o resultado sai da memoria.
      const snapshot = { ...(await readRecordingState()), result: null };
      await writeRecordingState(snapshot);
      return { ok: true, snapshot };
    }
    default:
      return { ok: false, error: 'unknown_command' };
  }
}

// So paginas da propria extensao (popup e offscreen) comandam a gravacao e recebem o token.
// O content script roda dentro das paginas visitadas e chega aqui com a origem delas.
function isExtensionPage(sender) {
  if (sender.id !== chrome.runtime.id) return false;
  const origin = sender.origin || (sender.url ? new URL(sender.url).origin : null);
  return origin === new URL(chrome.runtime.getURL('')).origin;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target !== 'background') return;
  if (!isExtensionPage(sender)) {
    sendResponse({ ok: false, error: 'forbidden' });
    return;
  }
  handleRecordingMessage(message).then(sendResponse, (error) => {
    console.error('Erro ao tratar comando de gravacao:', error);
    sendResponse({ ok: false, error: 'background_error' });
  });
  return true; // resposta assincrona
});
