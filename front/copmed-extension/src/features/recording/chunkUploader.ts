// Fila de envio das partes do áudio (B30 / US017-CA003).
//
// Cada parte é enviada assim que fica pronta. Se o envio falhar, a gravação NÃO para: a parte
// fica na fila (em memória — o áudio não é escrito em disco no navegador) e é reenviada
// depois, com a mesma sequência; o backend substitui a parte repetida, então reenviar é seguro.

/** Uma parte pronta para envio: WAV de até 5 min com a sua posição na gravação. */
export type AudioChunk = {
  seq: number;
  blob: Blob;
  durationMs: number;
};

/** O servidor recusou a parte de vez (ex.: 400, 403, 404): reenviar não adianta. */
export class PermanentUploadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PermanentUploadError";
  }
}

/** Sem sessão válida (token ausente ou 401): a parte espera o médico entrar de novo. */
export class UploadAuthError extends Error {
  constructor() {
    super("Sessão expirada.");
    this.name = "UploadAuthError";
  }
}

export type UploadWarning = "session_expired" | "upload_failed" | null;

export type UploaderStatus = {
  /** Sequências confirmadas pelo servidor. */
  sent: number[];
  /** Sequências aguardando (re)envio. */
  pending: number[];
  /** Sequências recusadas de vez pelo servidor. */
  dropped: number[];
  warning: UploadWarning;
};

export type UploaderDeps = {
  /** Envia uma parte; rejeita se o envio falhar. */
  send: (chunk: AudioChunk) => Promise<void>;
  onChange?: () => void;
  /** Intervalo entre as rodadas de reenvio enquanto a gravação segue. */
  retryDelayMs?: number;
  now?: () => number;
  wait?: (ms: number) => Promise<void>;
};

const RETRY_DELAY_MS = 15_000;
// Ao parar, as partes pendentes ainda são reenviadas por este prazo antes de desistir —
// tempo para a conexão voltar ou o médico entrar de novo se a sessão tiver expirado.
export const FLUSH_DEADLINE_MS = 5 * 60 * 1000;
export const FLUSH_INTERVAL_MS = 5000;

export class ChunkUploader {
  private pending: AudioChunk[] = [];
  private sent: number[] = [];
  private dropped: number[] = [];
  private warning: UploadWarning = null;
  private running: Promise<void> | null = null;
  private rerun = false;
  private closed = false;
  private cancelled = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly now: () => number;
  private readonly wait: (ms: number) => Promise<void>;

  constructor(private readonly deps: UploaderDeps) {
    this.now = deps.now ?? Date.now;
    this.wait = deps.wait ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  }

  get status(): UploaderStatus {
    return {
      sent: [...this.sent].sort((a, b) => a - b),
      pending: this.pending.map((chunk) => chunk.seq),
      dropped: [...this.dropped],
      warning: this.warning,
    };
  }

  /** Põe a parte na fila e dispara o envio em segundo plano. */
  enqueue(chunk: AudioChunk): void {
    if (this.closed) return;
    this.pending.push(chunk);
    this.pending.sort((a, b) => a.seq - b.seq);
    this.deps.onChange?.();
    void this.drain();
  }

  /**
   * Ao parar a gravação: insiste nas partes pendentes até a fila esvaziar ou o prazo vencer.
   * O que sobrar em `status.pending` não chegou ao servidor.
   */
  async flush({ deadlineMs = FLUSH_DEADLINE_MS, intervalMs = FLUSH_INTERVAL_MS } = {}): Promise<void> {
    this.closed = true;
    this.clearRetryTimer();
    const limit = this.now() + deadlineMs;
    for (;;) {
      await this.drain();
      if (this.cancelled || this.pending.length === 0 || this.now() >= limit) return;
      await this.wait(intervalMs);
    }
  }

  /** Descarta a fila (gravação cancelada). */
  cancel(): void {
    this.cancelled = true;
    this.closed = true;
    this.clearRetryTimer();
    this.pending = [];
  }

  // Uma rodada por vez. Parte que chega durante uma rodada pede outra logo em seguida.
  private drain(): Promise<void> {
    if (this.running) {
      this.rerun = true;
      return this.running;
    }
    this.running = this.run().finally(() => {
      this.running = null;
      this.scheduleRetry();
    });
    return this.running;
  }

  private async run(): Promise<void> {
    do {
      this.rerun = false;
      await this.pass();
    } while (this.rerun);
  }

  // Tenta cada parte pendente uma vez, em ordem. Uma falha não segura as partes seguintes.
  private async pass(): Promise<void> {
    for (const chunk of [...this.pending]) {
      if (this.cancelled) return;
      try {
        await this.deps.send(chunk);
        this.sent.push(chunk.seq);
        this.remove(chunk);
      } catch (error) {
        if (error instanceof PermanentUploadError) {
          this.dropped.push(chunk.seq);
          this.remove(chunk);
        } else {
          this.warning = error instanceof UploadAuthError ? "session_expired" : "upload_failed";
        }
      }
      if (this.pending.length === 0) this.warning = null;
      this.deps.onChange?.();
    }
  }

  private remove(chunk: AudioChunk): void {
    this.pending = this.pending.filter((item) => item !== chunk);
  }

  private scheduleRetry(): void {
    if (this.closed || this.pending.length === 0 || this.retryTimer) return;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.drain();
    }, this.deps.retryDelayMs ?? RETRY_DELAY_MS);
  }

  private clearRetryTimer(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }
}
