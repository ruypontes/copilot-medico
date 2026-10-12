// Utilitários puros de áudio usados pela gravação.

export const formatDuration = (seconds: number): string => {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60); // Math.floor garante que não mostre decimais
  return `${mins}:${secs.toString().padStart(2, "0")}`;
};

const writeString = (view: DataView, offset: number, str: string) => {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
};

// A transcrição trabalha em 16 kHz mono: enviar mais que isso só aumenta o upload
// (5 min a 48 kHz estéreo ≈ 58 MB; a 16 kHz mono ≈ 10 MB).
export const SPEECH_SAMPLE_RATE = 16000;

// Converte o áudio decodificado em WAV PCM 16 bits, formato aceito pelas rotas de transcrição.
// Com `mono`, os canais são misturados em um só.
export function audioBufferToWavBlob(audioBuffer: AudioBuffer, { mono = false } = {}) {
  const sourceChannels: Float32Array[] = [];
  for (let i = 0; i < audioBuffer.numberOfChannels; i++) {
    sourceChannels.push(audioBuffer.getChannelData(i));
  }
  const numOfChan = mono ? 1 : sourceChannels.length;
  const dataLength = audioBuffer.length * numOfChan * 2;
  const buffer = new ArrayBuffer(dataLength + 44);
  const view = new DataView(buffer);
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataLength, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numOfChan, true);
  view.setUint32(24, audioBuffer.sampleRate, true);
  view.setUint32(28, audioBuffer.sampleRate * numOfChan * 2, true);
  view.setUint16(32, numOfChan * 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataLength, true);
  let offset = 44;
  for (let i = 0; i < audioBuffer.length; i++) {
    for (let channel = 0; channel < numOfChan; channel++) {
      let sample = mono
        ? sourceChannels.reduce((sum, data) => sum + data[i], 0) / sourceChannels.length
        : sourceChannels[channel][i];
      sample = Math.max(-1, Math.min(1, sample));
      sample = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      view.setInt16(offset, sample, true);
      offset += 2;
    }
  }
  return new Blob([view], { type: "audio/wav" });
}

// Decodifica um trecho gravado pelo MediaRecorder (webm/opus) e o devolve em WAV 16 kHz mono.
// O OfflineAudioContext reamostra para a taxa pedida e não abre saída de áudio.
export async function decodeToSpeechWav(recorded: Blob): Promise<Blob> {
  const context = new OfflineAudioContext(1, 1, SPEECH_SAMPLE_RATE);
  const decoded = await context.decodeAudioData(await recorded.arrayBuffer());
  return audioBufferToWavBlob(decoded, { mono: true });
}
