// URL padrão da API; o popup salva a URL configurada (VITE_API_URL) em copmed_api_url.
const DEFAULT_API_URL = 'http://localhost:3001';
const TOKEN_KEY = 'copmed_extension_token';

// O token fica no chrome.storage.session; o local só é lido para sessões antigas.
function getToken(callback) {
  const sessionArea = chrome.storage.session || chrome.storage.local;
  sessionArea.get([TOKEN_KEY], (sessionResult) => {
    if (sessionResult && sessionResult[TOKEN_KEY]) {
      callback(sessionResult[TOKEN_KEY]);
      return;
    }
    chrome.storage.local.get([TOKEN_KEY], (localResult) => callback(localResult[TOKEN_KEY]));
  });
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'SEND_COMBINED_DATA') {
    chrome.storage.local.get(
      ['patientId', 'consultationId', 'copilotMedicoPatientId', 'copmed_api_url'],
      (storageResult) => getToken((token) => {
        const legacyPatientId = storageResult.copilotMedicoPatientId;
        const currentPatientId = storageResult.patientId || legacyPatientId;
        const currentConsultationId = storageResult.consultationId || null;
        const apiUrl = storageResult.copmed_api_url || DEFAULT_API_URL;

        if (!currentPatientId) {
          const errorMessage = 'patientId nao encontrado no armazenamento. Selecione um paciente e tente novamente.';
          console.error(errorMessage);
          sendResponse({ status: 'error', message: errorMessage });
          return;
        }

        const sourceUrl = request.source_url || sender?.tab?.url || null;
        const payload = {
          patient_id: currentPatientId,
          consultation_id: currentConsultationId,
          source_url: sourceUrl,
          extracted_content: request.extracted_content,
        };

        const headers = {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };

        fetch(`${apiUrl}/api/extension/extracted-data`, {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
        })
          .then((response) => {
            if (response.status === 401) {
              throw new Error('Sessão expirada. Abra a extensão e entre novamente.');
            }
            return response.json();
          })
          .then((data) => {
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
      })
    );

    return true; // manter a comunicação aberta para a resposta assíncrona.
  }
});