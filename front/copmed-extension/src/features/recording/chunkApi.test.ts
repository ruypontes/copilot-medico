import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createAudioApi, retryTransient } from "./chunkApi";
import { PermanentUploadError, UploadAuthError } from "./chunkUploader";

// B30: chamadas das rotas audio/chunks e transcribe feitas pelo documento offscreen.

const REF = { consultationId: "c1 xx", recordingId: "gravacao-teste-0001" };
const PARTE = { seq: 2, blob: new Blob(["RIFF"], { type: "audio/wav" }), durationMs: 1000 };

let fetchMock: ReturnType<typeof vi.fn>;
let token: string | null;

const api = () => createAudioApi({ apiUrl: "http://api.teste", getToken: async () => token });
const resposta = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status });

beforeEach(() => {
  token = "tok-1";
  fetchMock = vi.fn(async () => resposta(202));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sendChunk", () => {
  it("envia a parte em multipart com a sequência e o id da gravação", async () => {
    await api().sendChunk(REF, PARTE);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.teste/api/consultations/c1%20xx/audio/chunks");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ Authorization: "Bearer tok-1" }); // sem Content-Type: o navegador põe o boundary
    const form = init.body as FormData;
    expect(form.get("seq")).toBe("2");
    expect(form.get("recording_id")).toBe("gravacao-teste-0001");
    const arquivo = form.get("audio_file") as File;
    expect(arquivo.name).toBe("parte-0002.wav");
    expect(arquivo.type).toBe("audio/wav");
    expect(await arquivo.text()).toBe("RIFF");
  });

  it("pede o token a cada envio (um novo login vale para os reenvios)", async () => {
    await api().sendChunk(REF, PARTE);
    token = "tok-2";
    await api().sendChunk(REF, PARTE);

    expect(fetchMock.mock.calls.map(([, init]) => init.headers.Authorization)).toEqual([
      "Bearer tok-1",
      "Bearer tok-2",
    ]);
  });

  it("sem token nem tenta enviar: a parte espera o login", async () => {
    token = null;

    await expect(api().sendChunk(REF, PARTE)).rejects.toBeInstanceOf(UploadAuthError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("401 é sessão expirada", async () => {
    fetchMock.mockResolvedValue(resposta(401));

    await expect(api().sendChunk(REF, PARTE)).rejects.toBeInstanceOf(UploadAuthError);
  });

  it.each([400, 403, 404, 413])("%i é recusa definitiva (não adianta reenviar)", async (status) => {
    fetchMock.mockResolvedValue(resposta(status));

    await expect(api().sendChunk(REF, PARTE)).rejects.toBeInstanceOf(PermanentUploadError);
  });

  it.each([408, 429, 500, 503])("%i é falha passageira (a parte será reenviada)", async (status) => {
    fetchMock.mockResolvedValue(resposta(status));

    const erro = await api().sendChunk(REF, PARTE).catch((e) => e);

    expect(erro).toBeInstanceOf(Error);
    expect(erro).not.toBeInstanceOf(PermanentUploadError);
    expect(erro).not.toBeInstanceOf(UploadAuthError);
  });

  it("queda de rede é falha passageira", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const erro = await api().sendChunk(REF, PARTE).catch((e) => e);

    expect(erro).not.toBeInstanceOf(PermanentUploadError);
  });
});

describe("transcribe", () => {
  it("informa a gravação e quantas partes o servidor deve esperar", async () => {
    const corpo = { transcription: "texto", is_error: false, chunks: { received: [1, 2, 3], missing: [], failed: [] } };
    fetchMock.mockResolvedValue(resposta(200, corpo));

    const data = await api().transcribe(REF, 3);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.teste/api/consultations/c1%20xx/transcribe");
    expect(init.headers).toEqual({ "Content-Type": "application/json", Authorization: "Bearer tok-1" });
    expect(JSON.parse(init.body)).toEqual({ recording_id: "gravacao-teste-0001", total_chunks: 3 });
    expect(data).toEqual(corpo);
  });
});

describe("retryTransient", () => {
  const semEspera = { wait: async () => {}, intervalMs: 5 };

  it("repete falhas passageiras até dar certo", async () => {
    const acao = vi.fn().mockRejectedValueOnce(new Error("503")).mockRejectedValueOnce(new UploadAuthError()).mockResolvedValue("ok");

    await expect(retryTransient(acao, { ...semEspera, deadlineMs: 1000 })).resolves.toBe("ok");
    expect(acao).toHaveBeenCalledTimes(3);
  });

  it("não repete recusa definitiva", async () => {
    const acao = vi.fn().mockRejectedValue(new PermanentUploadError("404"));

    await expect(retryTransient(acao, { ...semEspera, deadlineMs: 1000 })).rejects.toBeInstanceOf(PermanentUploadError);
    expect(acao).toHaveBeenCalledTimes(1);
  });

  it("desiste quando o prazo vence", async () => {
    let agora = 0;
    const acao = vi.fn().mockRejectedValue(new Error("fora do ar"));
    const wait = async (ms: number) => {
      agora += ms;
    };

    await expect(
      retryTransient(acao, { deadlineMs: 10_000, intervalMs: 5000, now: () => agora, wait })
    ).rejects.toThrow("fora do ar");
    expect(acao).toHaveBeenCalledTimes(3); // em 0 s, 5 s e 10 s
  });
});
