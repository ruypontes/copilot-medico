import { beforeEach, describe, expect, it } from "vitest";
import {
  RecorderEngine,
  type RecordedSegment,
  type RecorderLike,
  type StreamLike,
} from "./recorderEngine";
import { CHUNK_MAX_MS, CHUNK_ROTATION_MS, MAX_RECORDING_MS, elapsedMs } from "./recordingProtocol";

// B29/B30: a máquina de gravação testada sem navegador — microfone, MediaRecorder e relógio
// são falsos, então dá para "gravar" 120 minutos em milissegundos.

class GravadorFalso implements RecorderLike {
  state = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  start() {
    this.state = "recording";
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  // Como o MediaRecorder real: entrega o que restou e só então avisa que parou.
  stop() {
    this.state = "inactive";
    this.entregar();
    this.onstop?.();
  }
  entregar() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
  }
}

let agora: number;
let gravadores: GravadorFalso[];
let trechos: RecordedSegment[];
let mudancas: number;
let faixaParada: boolean;
let aoDesconectar: (() => void) | null;
let microfone: () => Promise<StreamLike>;

function criar(opcoes: { maxDurationMs?: number; chunkDurationMs?: number } = {}) {
  return new RecorderEngine({
    getStream: () => microfone(),
    createRecorder: () => {
      const gravador = new GravadorFalso();
      gravadores.push(gravador);
      return gravador;
    },
    now: () => agora,
    onSegment: (trecho) => trechos.push(trecho),
    onChange: () => mudancas++,
    ...opcoes,
  });
}

/** Passa `segundos` de gravação: o gravador em uso entrega um bloco de áudio por segundo. */
function gravar(segundos: number) {
  for (let i = 0; i < segundos; i++) {
    agora += 1000;
    gravadores[gravadores.length - 1].entregar();
  }
}

beforeEach(() => {
  agora = 1_000_000;
  gravadores = [];
  trechos = [];
  mudancas = 0;
  faixaParada = false;
  aoDesconectar = null;
  microfone = async () => ({
    getTracks: () => [
      {
        stop: () => {
          faixaParada = true;
        },
        addEventListener: (_tipo: "ended", ouvinte: () => void) => {
          aoDesconectar = ouvinte;
        },
      },
    ],
  });
});

describe("iniciar, pausar, retomar e parar", () => {
  it("iniciar abre o microfone e começa a contar", async () => {
    const engine = criar();
    expect(engine.state.status).toBe("idle");

    await engine.start();

    expect(engine.state).toEqual({
      status: "recording",
      accumulatedMs: 0,
      resumedAt: agora,
      stopReason: null,
    });
    expect(gravadores).toHaveLength(1);
    expect(gravadores[0].state).toBe("recording");
    expect(mudancas).toBe(1);
  });

  it("o tempo pausado não entra no cronômetro", async () => {
    const engine = criar();
    await engine.start();
    gravar(10);

    engine.pause();
    expect(engine.state).toMatchObject({ status: "paused", accumulatedMs: 10_000, resumedAt: null });
    expect(gravadores[0].state).toBe("paused");
    agora += 30 * 60_000; // meia hora de pausa
    expect(engine.elapsedMs()).toBe(10_000);

    engine.resume();
    expect(engine.state).toMatchObject({ status: "recording", accumulatedMs: 10_000, resumedAt: agora });
    gravar(5);
    expect(engine.elapsedMs()).toBe(15_000);
    // o popup calcula o mesmo valor a partir do estado publicado
    expect(elapsedMs(engine.state, agora)).toBe(15_000);
  });

  it("parar fecha o trecho, solta o microfone e guarda o tempo final", async () => {
    const engine = criar();
    await engine.start();
    gravar(42);

    engine.stop();

    expect(engine.state).toEqual({
      status: "stopped",
      accumulatedMs: 42_000,
      resumedAt: null,
      stopReason: "manual",
    });
    expect(trechos).toHaveLength(1);
    expect(trechos[0]).toMatchObject({ seq: 1, durationMs: 42_000, last: true });
    expect(trechos[0].blob.size).toBeGreaterThan(0);
    expect(faixaParada).toBe(true);
  });

  it("parar funciona também com a gravação pausada", async () => {
    const engine = criar();
    await engine.start();
    gravar(7);
    engine.pause();
    agora += 60_000;

    engine.stop();

    expect(engine.state).toMatchObject({ status: "stopped", accumulatedMs: 7_000 });
    expect(trechos[0]).toMatchObject({ seq: 1, durationMs: 7_000, last: true });
  });

  it("comandos fora de hora são ignorados", async () => {
    const engine = criar();
    engine.pause();
    engine.resume();
    engine.stop();
    expect(engine.state.status).toBe("idle");

    await engine.start();
    engine.resume(); // já está gravando
    expect(engine.state.status).toBe("recording");
    engine.stop();
    engine.stop(); // parar duas vezes não gera um segundo trecho
    engine.pause();
    expect(engine.state.status).toBe("stopped");
    expect(trechos).toHaveLength(1);
  });

  it("iniciar duas vezes é recusado", async () => {
    const engine = criar();
    await engine.start();

    await expect(engine.start()).rejects.toThrow("already_recording");
    expect(gravadores).toHaveLength(1);
  });

  it("microfone negado: não grava e deixa tentar de novo", async () => {
    const negado = Object.assign(new Error("negado"), { name: "NotAllowedError" });
    microfone = () => Promise.reject(negado);
    const engine = criar();

    await expect(engine.start()).rejects.toBe(negado);
    expect(engine.state.status).toBe("idle");
    expect(gravadores).toHaveLength(0);
  });

  it("microfone desconectado encerra a gravação com o que já foi gravado", async () => {
    const engine = criar();
    await engine.start();
    gravar(20);

    aoDesconectar?.();

    expect(engine.state).toMatchObject({ status: "stopped", stopReason: "device", accumulatedMs: 20_000 });
    expect(trechos[0]).toMatchObject({ seq: 1, last: true });
  });
});

describe("limite de 120 min", () => {
  it("para sozinha ao atingir o limite", async () => {
    const engine = criar();
    await engine.start();

    gravar(MAX_RECORDING_MS / 1000 - 1);
    expect(engine.state.status).toBe("recording");
    gravar(1);

    expect(engine.state).toEqual({
      status: "stopped",
      accumulatedMs: MAX_RECORDING_MS,
      resumedAt: null,
      stopReason: "limit",
    });
    expect(trechos[trechos.length - 1].last).toBe(true);
    expect(faixaParada).toBe(true);
  });

  it("as pausas não contam para o limite", async () => {
    const engine = criar({ maxDurationMs: 60_000 });
    await engine.start();
    gravar(30);
    engine.pause();
    agora += 10 * 60_000;
    engine.resume();

    gravar(29);
    expect(engine.state.status).toBe("recording");
    gravar(1);
    expect(engine.state).toMatchObject({ status: "stopped", stopReason: "limit", accumulatedMs: 60_000 });
  });

  it("o cronômetro nunca passa do limite, mesmo que a conferência atrase", async () => {
    const engine = criar();
    await engine.start();
    agora += MAX_RECORDING_MS + 90_000; // nenhum bloco de áudio chegou nesse meio-tempo

    expect(engine.elapsedMs()).toBe(MAX_RECORDING_MS);
    engine.tick();
    expect(engine.state).toMatchObject({ status: "stopped", accumulatedMs: MAX_RECORDING_MS });
  });
});

describe("partes de até 5 min", () => {
  it("troca de parte sem interromper a gravação", async () => {
    const engine = criar();
    await engine.start();

    gravar(CHUNK_ROTATION_MS / 1000 - 1);
    expect(trechos).toHaveLength(0);
    gravar(1);

    expect(trechos).toHaveLength(1);
    expect(trechos[0]).toMatchObject({ seq: 1, durationMs: CHUNK_ROTATION_MS, last: false });
    expect(engine.state.status).toBe("recording");
    expect(faixaParada).toBe(false); // o microfone segue aberto para a parte seguinte
    // o gravador novo já estava ligado quando o anterior fechou: não há buraco entre as partes
    expect(gravadores.map((g) => g.state)).toEqual(["inactive", "recording"]);
  });

  it("120 min viram partes em sequência, todas com no máximo 5 min", async () => {
    const engine = criar();
    await engine.start();

    gravar(MAX_RECORDING_MS / 1000);

    expect(engine.state.stopReason).toBe("limit");
    expect(trechos.map((t) => t.seq)).toEqual(trechos.map((_, i) => i + 1));
    expect(trechos.length).toBe(Math.ceil(MAX_RECORDING_MS / CHUNK_ROTATION_MS));
    expect(Math.max(...trechos.map((t) => t.durationMs))).toBeLessThanOrEqual(CHUNK_MAX_MS);
    expect(trechos.reduce((soma, t) => soma + t.durationMs, 0)).toBe(MAX_RECORDING_MS);
    expect(trechos.filter((t) => t.last).map((t) => t.seq)).toEqual([trechos.length]);
  });

  it("a pausa não conta para o tamanho da parte", async () => {
    const engine = criar({ chunkDurationMs: 100_000 });
    await engine.start();
    gravar(60);
    engine.pause();
    agora += 3_600_000;
    engine.resume();

    gravar(39);
    expect(trechos).toHaveLength(0);
    gravar(1);
    expect(trechos).toHaveLength(1);
    expect(trechos[0].durationMs).toBe(100_000);
  });

  it("parar logo depois de uma troca fecha a parte seguinte como a última", async () => {
    const engine = criar({ chunkDurationMs: 10_000 });
    await engine.start();
    gravar(10); // fecha a parte 1 e abre a 2
    gravar(3);

    engine.stop();

    expect(trechos.map((t) => [t.seq, t.durationMs, t.last])).toEqual([
      [1, 10_000, false],
      [2, 3_000, true],
    ]);
  });
});
