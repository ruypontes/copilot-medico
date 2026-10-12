import { CHUNK_ROTATION_MS, MAX_RECORDING_MS, type StopReason } from "./recordingProtocol";

// Máquina de estados da gravação (B29): iniciar, pausar, retomar, parar, limite de 120 min e
// corte do áudio em partes de até 5 min (B30). Não conhece chrome.* nem a API: o microfone, o
// MediaRecorder e o relógio são injetados, o que permite testar tudo sem navegador.

/** O que a máquina usa de um MediaRecorder. */
export type RecorderLike = {
  readonly state: string;
  start(timeslice?: number): void;
  stop(): void;
  pause(): void;
  resume(): void;
  ondataavailable: ((event: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
};

/** O que a máquina usa de um MediaStream. */
export type StreamLike = {
  getTracks(): Array<{
    stop(): void;
    addEventListener?: (type: "ended", listener: () => void) => void;
  }>;
};

/** Um trecho contínuo da gravação, já fechado e pronto para envio. */
export type RecordedSegment = {
  seq: number;
  blob: Blob;
  /** Tempo de áudio do trecho (as pausas não contam). */
  durationMs: number;
  /** true no trecho que encerra a gravação. */
  last: boolean;
};

export type EngineStatus = "idle" | "recording" | "paused" | "stopped";

export type EngineState = {
  status: EngineStatus;
  accumulatedMs: number;
  resumedAt: number | null;
  stopReason: StopReason | null;
};

export type EngineDeps = {
  getStream: () => Promise<StreamLike>;
  createRecorder: (stream: StreamLike) => RecorderLike;
  now: () => number;
  onSegment: (segment: RecordedSegment) => void;
  onChange: () => void;
  maxDurationMs?: number;
  chunkDurationMs?: number;
};

// O MediaRecorder entrega dados a cada segundo; é nessa cadência que o limite e a troca de
// parte são conferidos. Eventos de mídia não sofrem o atraso que o navegador impõe a
// setTimeout/setInterval em páginas ocultas (caso do documento offscreen).
const TIMESLICE_MS = 1000;

type OpenSegment = {
  seq: number;
  recorder: RecorderLike;
  parts: Blob[];
  startedAtMs: number;
  endedAtMs: number;
  last: boolean;
};

/** Uma instância por gravação: depois de parar, crie outra para gravar de novo. */
export class RecorderEngine {
  private status: EngineStatus = "idle";
  private starting = false;
  private accumulatedMs = 0;
  private resumedAt: number | null = null;
  private stopReason: StopReason | null = null;
  private stream: StreamLike | null = null;
  private segment: OpenSegment | null = null;
  private nextSeq = 1;
  private readonly maxDurationMs: number;
  private readonly chunkDurationMs: number;

  constructor(private readonly deps: EngineDeps) {
    this.maxDurationMs = deps.maxDurationMs ?? MAX_RECORDING_MS;
    this.chunkDurationMs = deps.chunkDurationMs ?? CHUNK_ROTATION_MS;
  }

  get state(): EngineState {
    return {
      status: this.status,
      accumulatedMs: this.accumulatedMs,
      resumedAt: this.resumedAt,
      stopReason: this.stopReason,
    };
  }

  /** Tempo gravado até agora, sem as pausas. */
  elapsedMs(): number {
    const running = this.resumedAt === null ? 0 : this.deps.now() - this.resumedAt;
    return Math.min(this.maxDurationMs, this.accumulatedMs + running);
  }

  /** Abre o microfone e começa a gravar. Rejeita se o microfone for negado. */
  async start(): Promise<void> {
    if (this.status !== "idle" || this.starting) throw new Error("already_recording");
    this.starting = true;
    try {
      this.stream = await this.deps.getStream();
    } finally {
      this.starting = false;
    }
    // Microfone desconectado no meio da consulta: encerra e envia o que já foi gravado.
    for (const track of this.stream.getTracks()) {
      track.addEventListener?.("ended", () => this.stop("device"));
    }
    try {
      this.openSegment();
    } catch (error) {
      this.releaseStream(); // não deixa o microfone aberto se o gravador não puder ser criado
      throw error;
    }
    this.status = "recording";
    this.resumedAt = this.deps.now();
    this.deps.onChange();
  }

  pause(): void {
    if (this.status !== "recording") return;
    this.accumulatedMs = this.elapsedMs();
    this.resumedAt = null;
    this.status = "paused";
    this.segment?.recorder.pause();
    this.deps.onChange();
  }

  resume(): void {
    if (this.status !== "paused") return;
    this.resumedAt = this.deps.now();
    this.status = "recording";
    this.segment?.recorder.resume();
    this.deps.onChange();
  }

  stop(reason: StopReason = "manual"): void {
    if (this.status !== "recording" && this.status !== "paused") return;
    this.accumulatedMs = this.elapsedMs();
    this.resumedAt = null;
    this.status = "stopped";
    this.stopReason = reason;
    this.closeSegment(true);
    this.deps.onChange();
  }

  /** Confere o limite de 120 min e a hora de trocar de parte. */
  tick(): void {
    if (this.status !== "recording" || !this.segment) return;
    const elapsed = this.elapsedMs();
    if (elapsed >= this.maxDurationMs) {
      this.stop("limit");
    } else if (elapsed - this.segment.startedAtMs >= this.chunkDurationMs) {
      this.rotate();
    }
  }

  // Cada parte é um arquivo completo: os pedaços de um mesmo MediaRecorder só têm cabeçalho
  // no primeiro e não podem ser decodificados sozinhos. Por isso a troca de parte abre um
  // gravador novo no mesmo microfone — antes de fechar o anterior, para não perder áudio.
  private rotate(): void {
    const previous = this.segment;
    this.openSegment();
    if (previous) this.finishSegment(previous, false);
  }

  private openSegment(): void {
    if (!this.stream) return;
    const segment: OpenSegment = {
      seq: this.nextSeq++,
      recorder: this.deps.createRecorder(this.stream),
      parts: [],
      startedAtMs: this.elapsedMs(),
      endedAtMs: 0,
      last: false,
    };
    segment.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) segment.parts.push(event.data);
      if (segment === this.segment) this.tick();
    };
    segment.recorder.onstop = () => {
      if (segment.last) this.releaseStream();
      this.deps.onSegment({
        seq: segment.seq,
        blob: new Blob(segment.parts, { type: segment.parts[0]?.type || "audio/webm" }),
        durationMs: segment.endedAtMs - segment.startedAtMs,
        last: segment.last,
      });
    };
    segment.recorder.start(TIMESLICE_MS);
    this.segment = segment;
  }

  private closeSegment(last: boolean): void {
    const segment = this.segment;
    this.segment = null;
    if (segment) this.finishSegment(segment, last);
  }

  private finishSegment(segment: OpenSegment, last: boolean): void {
    segment.endedAtMs = this.elapsedMs();
    segment.last = last;
    if (segment.recorder.state !== "inactive") segment.recorder.stop();
  }

  // Solta o microfone (apaga o indicador de gravação do navegador).
  private releaseStream(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}
