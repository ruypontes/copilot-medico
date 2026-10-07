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
