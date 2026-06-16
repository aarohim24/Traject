"""Google Vertex AI provider adapter for the Traject SDK.

Wraps the ``google-cloud-aiplatform`` (``vertexai``) package to expose a
:class:`VertexAdapter` that translates Axon's generic message format into
Vertex AI ``generateContent`` requests and returns a normalised
:class:`~traject.providers.ProviderResponse`.

The heavyweight ``vertexai`` import is deferred to :meth:`VertexAdapter.__init__`
so that the module can be imported unconditionally without requiring the
optional dependency to be installed.
"""

from __future__ import annotations

from typing import Any

from traject.exceptions import TrajectDependencyError
from traject.providers import ProviderResponse


class VertexAdapter:
    """Google Vertex AI provider adapter using the generateContent API.

    Supported models: ``gemini-1.5-pro``, ``gemini-1.5-flash``,
    ``gemini-1.0-pro``.

    The adapter guards the ``google-cloud-aiplatform`` import inside
    :meth:`__init__` so that applications that do not use Vertex AI are not
    forced to install the dependency.

    Args:
        project: GCP project ID.  Defaults to the ``GOOGLE_CLOUD_PROJECT``
            environment variable when ``None``.
        location: GCP region for the Vertex AI endpoint.
            Defaults to ``"us-central1"``.

    Raises:
        TrajectDependencyError: If ``google-cloud-aiplatform`` is not installed.

    Example::

        adapter = VertexAdapter(project="my-gcp-project")
        response = adapter.complete(
            messages=[{"role": "user", "content": "Hello!"}],
            model="gemini-1.5-pro",
        )
        print(response.content)
    """

    def __init__(
        self,
        project: str | None = None,
        location: str = "us-central1",
    ) -> None:
        """Initialise the adapter, guarding the google-cloud-aiplatform import.

        Args:
            project: GCP project ID.  When ``None``, the underlying SDK falls
                back to the ``GOOGLE_CLOUD_PROJECT`` environment variable.
            location: GCP region for the Vertex AI endpoint.

        Raises:
            TrajectDependencyError: If ``google-cloud-aiplatform`` is not installed.
        """
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as exc:
            raise TrajectDependencyError(
                "Google Vertex AI support requires google-cloud-aiplatform. "
                "Install it with: pip install 'traject-sdk[vertex]'"
            ) from exc

        self._vertexai: Any = vertexai  # Any: vertexai module has no stubs
        self._GenerativeModel: Any = (  # Any: GenerativeModel has no stubs
            GenerativeModel
        )
        self._project = project
        self._location = location

    def complete(
        self,
        messages: list[dict[str, Any]],  # Any: Traject generic message format
        model: str,
        **kwargs: Any,  # Any: forwarded to Vertex generateContent call
    ) -> ProviderResponse:
        """Send a list of messages to Vertex AI and return a normalised response.

        Initialises the Vertex AI SDK, creates a :class:`GenerativeModel`
        instance, concatenates all message content into a single text string,
        calls ``generate_content``, and extracts token counts from
        ``response.usage_metadata``.

        Args:
            messages: List of Axon-format message dicts, each with at least
                ``"role"`` and ``"content"`` keys.
            model: Vertex AI model identifier, e.g. ``"gemini-1.5-pro"``,
                ``"gemini-1.5-flash"``, or ``"gemini-1.0-pro"``.
            **kwargs: Extra keyword arguments forwarded to
                ``GenerativeModel.generate_content``.

        Returns:
            A :class:`~traject.providers.ProviderResponse` with
            ``provider="vertex"`` populated.

        Raises:
            Exception: Any exception raised by the Vertex AI SDK is propagated
                to the caller unchanged.
        """
        self._vertexai.init(project=self._project, location=self._location)

        model_obj: Any = self._GenerativeModel(model)  # Any: no stubs

        contents: str = "\n".join(
            str(msg.get("content", "")) for msg in messages
        )

        response: Any = model_obj.generate_content(contents)  # Any: no stubs

        input_tokens: int = int(response.usage_metadata.prompt_token_count)
        output_tokens: int = int(response.usage_metadata.candidates_token_count)

        return ProviderResponse(
            provider="vertex",
            content=response.text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            raw_response={"text": response.text},
        )
