"""Artifact type classifier for the Traject SDK.

Classifies context segments into typed artifact categories (system prompt,
user message, tool result, reasoning block, etc.) to enable per-type
compression policies.
"""

from traject.classifier.artifact_type import ArtifactType, classify, classify_sequence

__all__ = ["ArtifactType", "classify", "classify_sequence"]
