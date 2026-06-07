"""LangChain agent example for Axon SDK.

Demonstrates axon.patch() applied to a LangChain ChatOpenAI model.

Prerequisites:
    pip install axon-sdk[openai,langchain] langchain-openai
    export OPENAI_API_KEY=your-key-here
"""
from __future__ import annotations

import axon

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except ImportError as exc:
    raise SystemExit(
        "Missing dependencies. Run: pip install axon-sdk[openai,langchain] langchain-openai"
    ) from exc


if __name__ == "__main__":
    model = ChatOpenAI(model="gpt-4o-mini")
    axon.patch(model, feature_tag="langchain-demo", shadow_mode=True)

    messages = [
        SystemMessage(content="You are a concise AI assistant."),
        HumanMessage(content="What is the tallest mountain? One sentence."),
    ]
    response = model.invoke(messages)
    print(f"Response: {response.content}")
