"""OpenAI basic example for Traject SDK.

Demonstrates @traject.instrument() wrapping an OpenAI chat completion call.
An OTEL span with token counts, cost, and compression analysis is printed
to stdout after each call.

Prerequisites:
    pip install traject-sdk[openai]
    export OPENAI_API_KEY=your-key-here
"""
from __future__ import annotations

import traject
import openai


@traject.instrument(feature_tag="demo-basic", shadow_mode=True)
def call_llm(messages: list[dict]) -> openai.types.chat.ChatCompletion:
    """Call the OpenAI API with Traject instrumentation."""
    client = openai.OpenAI()
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )


if __name__ == "__main__":
    messages = [
        {"role": "system", "content": "You are a concise AI assistant."},
        {"role": "user", "content": "What is the capital of France? One word."},
    ]
    response = call_llm(messages)
    print(f"Response: {response.choices[0].message.content}")
