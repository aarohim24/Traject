/**
 * Tests for the instrumentor module (patch and instrument).
 *
 * Validates: Requirements 8.1, 8.2, 8.3, 8.4
 */

import { patch } from "../src/instrumentor";

describe("patch — OpenAI client", () => {
  // Validates: Requirements 8.1
  it("detects OpenAI client and wraps chat.completions.create", async () => {
    const mockResponse = {
      id: "chatcmpl-test",
      choices: [],
      usage: { prompt_tokens: 5, completion_tokens: 10, total_tokens: 15 },
    };
    const mockCreate = jest.fn().mockResolvedValue(mockResponse);
    const client = { chat: { completions: { create: mockCreate } } };

    const consoleSpy = jest
      .spyOn(console, "log")
      .mockImplementation(() => undefined);
    patch(client, { exportToConsole: true });

    const result = await client.chat.completions.create({
      model: "gpt-4o",
      messages: [],
    });
    expect(result).toEqual(mockResponse);
    expect(mockCreate).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  // Validates: Requirements 8.1 — original response is returned unchanged
  it("returns original OpenAI response unchanged", async () => {
    const mockResponse = {
      id: "chatcmpl-test",
      choices: [{ message: { role: "assistant", content: "hello" } }],
      usage: { prompt_tokens: 2, completion_tokens: 1, total_tokens: 3 },
    };
    const mockCreate = jest.fn().mockResolvedValue(mockResponse);
    const client = { chat: { completions: { create: mockCreate } } };

    patch(client);
    const result = await client.chat.completions.create({
      model: "gpt-4o",
      messages: [],
    });
    expect(result).toEqual(mockResponse);
  });

  // Validates: Requirements 8.3
  it("propagates errors from wrapped OpenAI function unchanged", async () => {
    const error = new Error("LLM error");
    const mockCreate = jest.fn().mockRejectedValue(error);
    const client = { chat: { completions: { create: mockCreate } } };

    patch(client);
    await expect(
      client.chat.completions.create({ model: "gpt-4o", messages: [] }),
    ).rejects.toThrow("LLM error");
  });

  // Validates: Requirements 8.4
  it("emits span to console on successful OpenAI call", async () => {
    const mockResponse = {
      usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
    };
    const mockCreate = jest.fn().mockResolvedValue(mockResponse);
    const client = { chat: { completions: { create: mockCreate } } };

    const consoleSpy = jest
      .spyOn(console, "log")
      .mockImplementation(() => undefined);
    patch(client, { exportToConsole: true });

    await client.chat.completions.create({ model: "gpt-4o", messages: [] });

    expect(consoleSpy).toHaveBeenCalled();
    const output = consoleSpy.mock.calls[0]?.[0] as string;
    const span = JSON.parse(output) as Record<string, unknown>;
    expect(span).toHaveProperty("spanId");
    expect(span["provider"]).toBe("openai");
    expect(span["model"]).toBe("gpt-4o");
    consoleSpy.mockRestore();
  });
});

describe("patch — Anthropic client", () => {
  // Validates: Requirements 8.2
  it("detects Anthropic client and wraps messages.create", async () => {
    const mockResponse = {
      id: "msg-test",
      content: [],
      usage: { input_tokens: 5, output_tokens: 10 },
    };
    const mockCreate = jest.fn().mockResolvedValue(mockResponse);
    const client = { messages: { create: mockCreate } };

    const consoleSpy = jest
      .spyOn(console, "log")
      .mockImplementation(() => undefined);
    patch(client, { exportToConsole: true });

    const result = await client.messages.create({
      model: "claude-3-5-haiku-20241022",
      messages: [],
      max_tokens: 100,
    });
    expect(result).toEqual(mockResponse);
    expect(mockCreate).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  // Validates: Requirements 8.2 — original response unchanged
  it("returns original Anthropic response unchanged", async () => {
    const mockResponse = {
      content: [{ type: "text", text: "hello" }],
      usage: { input_tokens: 3, output_tokens: 2 },
    };
    const mockCreate = jest.fn().mockResolvedValue(mockResponse);
    const client = { messages: { create: mockCreate } };

    patch(client);
    const result = await client.messages.create({
      model: "claude-3-5-haiku-20241022",
      messages: [],
      max_tokens: 50,
    });
    expect(result).toEqual(mockResponse);
  });

  // Validates: Requirements 8.3
  it("propagates errors from wrapped Anthropic function unchanged", async () => {
    const error = new Error("Anthropic API error");
    const mockCreate = jest.fn().mockRejectedValue(error);
    const client = { messages: { create: mockCreate } };

    patch(client);
    await expect(
      client.messages.create({ model: "claude-3-5-haiku-20241022", messages: [] }),
    ).rejects.toThrow("Anthropic API error");
  });

  // Validates: Requirements 8.4
  it("emits span with provider=anthropic on successful Anthropic call", async () => {
    const mockResponse = {
      usage: { input_tokens: 8, output_tokens: 4 },
    };
    const mockCreate = jest.fn().mockResolvedValue(mockResponse);
    const client = { messages: { create: mockCreate } };

    const consoleSpy = jest
      .spyOn(console, "log")
      .mockImplementation(() => undefined);
    patch(client, { exportToConsole: true });

    await client.messages.create({
      model: "claude-3-5-haiku-20241022",
      messages: [],
      max_tokens: 50,
    });

    expect(consoleSpy).toHaveBeenCalled();
    const output = consoleSpy.mock.calls[0]?.[0] as string;
    const span = JSON.parse(output) as Record<string, unknown>;
    expect(span["provider"]).toBe("anthropic");
    expect(span["model"]).toBe("claude-3-5-haiku-20241022");
    consoleSpy.mockRestore();
  });
});

describe("patch — unrecognised client", () => {
  it("does not throw for a client with no recognised structure", () => {
    expect(() => patch({})).not.toThrow();
    expect(() => patch(null)).not.toThrow();
    expect(() => patch(undefined)).not.toThrow();
  });
});
