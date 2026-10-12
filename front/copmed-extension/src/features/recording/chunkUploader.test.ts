import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChunkUploader,
  PermanentUploadError,
  UploadAuthError,
  type AudioChunk,
} from "./chunkUploader";

// B30: fila de envio das partes. Critério de aceite: 3 partes e um reenvio — a parte que
// falha é reenviada depois e a gravação segue enviando as demais.

const parte = (seq: number): AudioChunk => ({ seq, blob: new Blob([`parte ${seq}`]), durationMs: 1000 });

let enviadas: number[]; // toda tentativa de envio, na ordem
let falhas: Map<number, Error[]>; // erros a devolver nas próximas tentativas de cada sequência
let mudancas: number;

function criar(opcoes: { retryDelayMs?: number } = {}) {
  return new ChunkUploader({
    send: async (chunk) => {
      enviadas.push(chunk.seq);
      const erro = falhas.get(chunk.seq)?.shift();
      if (erro) throw erro;
    },
    onChange: () => mudancas++,
    retryDelayMs: 15_000,
    ...opcoes,
  });
}

/** Deixa as promessas pendentes (envios em andamento) terminarem. */
const assentar = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
  enviadas = [];
  falhas = new Map();
  mudancas = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("envio e reenvio", () => {
  it("3 partes e um reenvio: a parte que falhou é reenviada e as três chegam", async () => {
    falhas.set(2, [new Error("rede caiu")]);
    const uploader = criar();

    uploader.enqueue(parte(1));
    await assentar();
    uploader.enqueue(parte(2)); // o envio falha: a parte fica na fila
    await assentar();
    expect(uploader.status).toEqual({ sent: [1], pending: [2], dropped: [], warning: "upload_failed" });

    uploader.enqueue(parte(3)); // a gravação continuou; a parte nova leva junto o reenvio da 2
    await assentar();

    expect(uploader.status).toEqual({ sent: [1, 2, 3], pending: [], dropped: [], warning: null });
    // 4 envios para 3 partes: a 2 foi reenviada com a mesma sequência
    expect(enviadas).toEqual([1, 2, 2, 3]);
  });

  it("uma parte que continua falhando não segura as seguintes", async () => {
    falhas.set(2, [new Error("a"), new Error("b")]);
    const uploader = criar();

    uploader.enqueue(parte(1));
    uploader.enqueue(parte(2));
    await assentar();
    uploader.enqueue(parte(3));
    await assentar();

    expect(uploader.status).toEqual({ sent: [1, 3], pending: [2], dropped: [], warning: "upload_failed" });

    await vi.advanceTimersByTimeAsync(15_000); // rodada de reenvio com a gravação parada na parte 3

    expect(uploader.status).toEqual({ sent: [1, 2, 3], pending: [], dropped: [], warning: null });
  });

  it("o reenvio se repete enquanto a parte continuar falhando", async () => {
    falhas.set(1, [new Error("1"), new Error("2"), new Error("3")]);
    const uploader = criar();

    uploader.enqueue(parte(1));
    await assentar();
    await vi.advanceTimersByTimeAsync(15_000);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(uploader.status.pending).toEqual([1]);

    await vi.advanceTimersByTimeAsync(15_000);
    expect(uploader.status.sent).toEqual([1]);
    expect(enviadas).toEqual([1, 1, 1, 1]);
  });

  it("partes pendentes são reenviadas em ordem de sequência", async () => {
    falhas.set(1, [new Error("x")]);
    falhas.set(2, [new Error("x"), new Error("x")]); // falha sozinha e de novo quando a 1 entra
    const uploader = criar();
    uploader.enqueue(parte(2));
    uploader.enqueue(parte(1));
    await assentar();
    expect(uploader.status.pending).toEqual([1, 2]);
    enviadas = [];

    await vi.advanceTimersByTimeAsync(15_000);

    expect(enviadas).toEqual([1, 2]);
  });

  it("sessão expirada mantém a parte na fila e avisa o motivo", async () => {
    falhas.set(1, [new UploadAuthError()]);
    const uploader = criar();

    uploader.enqueue(parte(1));
    await assentar();
    expect(uploader.status).toMatchObject({ pending: [1], warning: "session_expired" });

    await vi.advanceTimersByTimeAsync(15_000); // o médico entrou de novo: o envio passa
    expect(uploader.status).toMatchObject({ sent: [1], pending: [], warning: null });
  });

  it("parte recusada de vez pelo servidor sai da fila sem reenvio", async () => {
    falhas.set(2, [new PermanentUploadError("400")]);
    const uploader = criar();

    uploader.enqueue(parte(1));
    uploader.enqueue(parte(2));
    await assentar();
    await vi.advanceTimersByTimeAsync(60_000);

    expect(uploader.status).toEqual({ sent: [1], pending: [], dropped: [2], warning: null });
    expect(enviadas).toEqual([1, 2]);
  });

  it("avisa a cada mudança da fila", async () => {
    const uploader = criar();
    uploader.enqueue(parte(1));
    await assentar();

    expect(mudancas).toBe(2); // entrou na fila; foi enviada
  });
});

describe("ao parar a gravação (flush)", () => {
  it("insiste nas partes pendentes até chegarem", async () => {
    falhas.set(1, [new Error("a"), new Error("b"), new Error("c")]);
    const uploader = criar();
    uploader.enqueue(parte(1));
    await assentar();

    const fim = uploader.flush({ deadlineMs: 60_000, intervalMs: 5000 });
    await vi.advanceTimersByTimeAsync(10_000);
    await fim;

    expect(uploader.status).toMatchObject({ sent: [1], pending: [] });
  });

  it("desiste quando o prazo vence e informa o que ficou faltando", async () => {
    falhas.set(2, Array.from({ length: 50 }, () => new Error("servidor fora")));
    const uploader = criar();
    uploader.enqueue(parte(1));
    uploader.enqueue(parte(2));
    await assentar();

    const fim = uploader.flush({ deadlineMs: 20_000, intervalMs: 5000 });
    await vi.advanceTimersByTimeAsync(30_000);
    await fim;

    expect(uploader.status).toMatchObject({ sent: [1], pending: [2], warning: "upload_failed" });
  });

  it("com a fila vazia termina na hora", async () => {
    const uploader = criar();
    uploader.enqueue(parte(1));
    await assentar();

    await uploader.flush();

    expect(uploader.status.sent).toEqual([1]);
  });

  it("depois do flush não há mais reenvio em segundo plano", async () => {
    falhas.set(1, Array.from({ length: 10 }, () => new Error("x")));
    const uploader = criar();
    uploader.enqueue(parte(1));
    await assentar();
    const fim = uploader.flush({ deadlineMs: 0, intervalMs: 5000 });
    await assentar();
    await fim;
    const tentativas = enviadas.length;

    await vi.advanceTimersByTimeAsync(120_000);

    expect(enviadas).toHaveLength(tentativas);
  });
});

describe("cancelar", () => {
  it("descarta a fila e para os reenvios", async () => {
    falhas.set(1, [new Error("x")]);
    const uploader = criar();
    uploader.enqueue(parte(1));
    await assentar();

    uploader.cancel();
    uploader.enqueue(parte(2));
    await vi.advanceTimersByTimeAsync(60_000);

    expect(uploader.status).toMatchObject({ sent: [], pending: [] });
    expect(enviadas).toEqual([1]);
  });
});
