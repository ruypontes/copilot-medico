import { describe, expect, it } from "vitest";
import {
  CHUNK_MAX_MS,
  CHUNK_ROTATION_MS,
  IDLE_SNAPSHOT,
  MAX_RECORDING_MS,
  elapsedMs,
  normalizeSnapshot,
  shortenedBy,
} from "./recordingProtocol";

describe("limites da gravação", () => {
  it("por padrão: 120 min de gravação e partes abaixo de 5 min", () => {
    expect(MAX_RECORDING_MS).toBe(120 * 60 * 1000);
    expect(CHUNK_MAX_MS).toBe(5 * 60 * 1000);
    expect(CHUNK_ROTATION_MS).toBeLessThan(CHUNK_MAX_MS);
  });

  it("as variáveis de teste só encurtam os prazos, nunca aumentam", () => {
    expect(shortenedBy("20", 295_000)).toBe(20_000);
    expect(shortenedBy("900", 295_000)).toBe(295_000); // parte acima de 5 min seria recusada pela API
    expect(shortenedBy(undefined, 295_000)).toBe(295_000);
    expect(shortenedBy("abc", 295_000)).toBe(295_000);
    expect(shortenedBy("0", 295_000)).toBe(295_000);
    expect(shortenedBy("-5", 295_000)).toBe(295_000);
  });
});

describe("elapsedMs (cronômetro)", () => {
  it("soma o tempo acumulado ao trecho em curso", () => {
    expect(elapsedMs({ accumulatedMs: 60_000, resumedAt: 1_000_000 }, 1_005_000)).toBe(65_000);
  });

  it("pausado, fica no tempo acumulado", () => {
    expect(elapsedMs({ accumulatedMs: 60_000, resumedAt: null }, 9_999_999)).toBe(60_000);
  });

  it("não passa do limite nem anda para trás se o relógio recuar", () => {
    expect(elapsedMs({ accumulatedMs: 0, resumedAt: 0 }, MAX_RECORDING_MS + 60_000)).toBe(MAX_RECORDING_MS);
    expect(elapsedMs({ accumulatedMs: 10_000, resumedAt: 5000 }, 4000)).toBe(10_000);
  });
});

describe("normalizeSnapshot (estado lido do storage)", () => {
  it("valor ausente ou fora do formato vira 'sem gravação'", () => {
    expect(normalizeSnapshot(undefined)).toEqual(IDLE_SNAPSHOT);
    expect(normalizeSnapshot("gravando")).toEqual(IDLE_SNAPSHOT);
    expect(normalizeSnapshot({ status: "tocando" })).toEqual(IDLE_SNAPSHOT);
  });

  it("completa os campos que faltarem", () => {
    expect(normalizeSnapshot({ status: "paused", accumulatedMs: 5000 })).toEqual({
      ...IDLE_SNAPSHOT,
      status: "paused",
      accumulatedMs: 5000,
    });
  });
});
