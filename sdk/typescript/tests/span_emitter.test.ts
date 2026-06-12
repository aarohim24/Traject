/**
 * Tests for the SpanEmitter class.
 *
 * Validates: Requirements 8.5, 8.6, 8.7
 */

import { SpanEmitter } from "../src/span_emitter";
import type { InferenceSpan } from "../src/types";

const mockSpan: InferenceSpan = {
  spanId: "test-span-id-0000-0000-000000000001",
  model: "gpt-4o",
  provider: "openai",
  startTime: "2025-01-01T00:00:00.000Z",
  endTime: "2025-01-01T00:00:00.100Z",
  durationMs: 100,
  usage: {
    inputTokens: 10,
    outputTokens: 20,
    totalTokens: 30,
  },
  promptHash: "abc123",
};

describe("SpanEmitter", () => {
  // Validates: Requirements 8.5
  it("console output is valid JSON when exportToConsole is true", () => {
    const consoleSpy = jest
      .spyOn(console, "log")
      .mockImplementation(() => undefined);
    const emitter = new SpanEmitter({ exportToConsole: true });
    emitter.emit(mockSpan);
    const output = consoleSpy.mock.calls[0]?.[0] as string;
    expect(() => JSON.parse(output)).not.toThrow();
    consoleSpy.mockRestore();
  });

  // Validates: Requirements 8.5
  it("does not write to console when exportToConsole is false", () => {
    const consoleSpy = jest
      .spyOn(console, "log")
      .mockImplementation(() => undefined);
    const emitter = new SpanEmitter({ exportToConsole: false });
    emitter.emit(mockSpan);
    expect(consoleSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  // Validates: Requirements 8.6
  it("POSTs to {backendUrl}/v1/spans with X-Axon-API-Key header", async () => {
    const mockFetch = jest
      .fn()
      .mockResolvedValue({ ok: true } as Response);
    global.fetch = mockFetch;

    const emitter = new SpanEmitter({
      backendUrl: "https://example.com",
      apiKey: "test-key",
    });
    emitter.emit(mockSpan);

    // Wait for fire-and-forget Promise to settle
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(mockFetch).toHaveBeenCalledWith(
      "https://example.com/v1/spans",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-Axon-API-Key": "test-key",
          "Content-Type": "application/json",
        }),
      }),
    );
  });

  // Validates: Requirements 8.7
  it("backend fetch failure does not throw", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("Network error"));
    const consoleSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    const emitter = new SpanEmitter({ backendUrl: "https://example.com" });
    expect(() => emitter.emit(mockSpan)).not.toThrow();

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  // Validates: Requirements 8.7
  it("does not POST when backendUrl is empty string", async () => {
    const mockFetch = jest.fn();
    global.fetch = mockFetch;

    const emitter = new SpanEmitter({ backendUrl: "" });
    emitter.emit(mockSpan);

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(mockFetch).not.toHaveBeenCalled();
  });

  // Validates: Requirements 8.6
  it("does not set X-Axon-API-Key header when apiKey is not configured", async () => {
    const mockFetch = jest
      .fn()
      .mockResolvedValue({ ok: true } as Response);
    global.fetch = mockFetch;

    const emitter = new SpanEmitter({ backendUrl: "https://example.com" });
    emitter.emit(mockSpan);

    await new Promise((resolve) => setTimeout(resolve, 30));

    const callArgs = mockFetch.mock.calls[0] as [string, RequestInit];
    const headers = callArgs[1]?.headers as Record<string, string>;
    expect(headers["X-Axon-API-Key"]).toBeUndefined();
  });
});
