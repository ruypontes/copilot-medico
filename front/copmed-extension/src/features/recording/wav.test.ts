import { describe, expect, it } from "vitest";
import { audioBufferToWavBlob, formatDuration } from "./wav";

// O AudioBuffer só existe no navegador; aqui basta o que o codificador lê dele.
function buffer(canais: number[][], sampleRate = 16000): AudioBuffer {
  return {
    numberOfChannels: canais.length,
    length: canais[0].length,
    sampleRate,
    getChannelData: (i: number) => Float32Array.from(canais[i]),
  } as unknown as AudioBuffer;
}

async function ler(blob: Blob) {
  const view = new DataView(await blob.arrayBuffer());
  const amostras: number[] = [];
  for (let offset = 44; offset < view.byteLength; offset += 2) amostras.push(view.getInt16(offset, true));
  return {
    canais: view.getUint16(22, true),
    taxa: view.getUint32(24, true),
    bytesPorSegundo: view.getUint32(28, true),
    bytesDeDados: view.getUint32(40, true),
    amostras,
  };
}

describe("audioBufferToWavBlob", () => {
  it("mantém os canais intercalados por padrão", async () => {
    const wav = await ler(audioBufferToWavBlob(buffer([[1, 0], [-1, 0.5]], 48000)));

    expect(wav).toMatchObject({ canais: 2, taxa: 48000, bytesPorSegundo: 48000 * 2 * 2, bytesDeDados: 8 });
    expect(wav.amostras).toEqual([32767, -32768, 0, 16383]);
  });

  it("com mono mistura os canais em um só (parte enviada para transcrição)", async () => {
    const blob = audioBufferToWavBlob(buffer([[1, 0, -1], [0, 0, -1]]), { mono: true });
    const wav = await ler(blob);

    expect(blob.type).toBe("audio/wav");
    expect(wav).toMatchObject({ canais: 1, taxa: 16000, bytesPorSegundo: 16000 * 2, bytesDeDados: 6 });
    expect(wav.amostras).toEqual([16383, 0, -32768]);
  });

  it("5 min em 16 kHz mono ficam abaixo de 10 MB", () => {
    const cincoMinutos = buffer([Array.from({ length: 16000 * 300 }, () => 0)]);

    expect(audioBufferToWavBlob(cincoMinutos, { mono: true }).size).toBe(16000 * 300 * 2 + 44);
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0:00"],
    [65.9, "1:05"],
    [7200, "120:00"],
  ])("%d s vira %s", (segundos, texto) => {
    expect(formatDuration(segundos)).toBe(texto);
  });
});
