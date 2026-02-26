"""Pydantic models for aumai-otel-genai."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "GenAISpanAttributes",
    "GenAIMetrics",
]


class GenAISpanAttributes(BaseModel):
    """
    Attributes attached to an OpenTelemetry span representing a GenAI call.

    Follows the OpenTelemetry semantic conventions for Generative AI systems
    (https://opentelemetry.io/docs/specs/semconv/gen-ai/).
    """

    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    temperature: float | None = None
    max_tokens: int | None = None
    finish_reason: str = "stop"
    latency_ms: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_otel_dict(self) -> dict[str, Any]:
        """Return a flat dict of OTel attribute names -> values."""
        attrs: dict[str, Any] = {
            "gen_ai.system": self.provider,
            "gen_ai.request.model": self.model,
            "gen_ai.usage.input_tokens": self.input_tokens,
            "gen_ai.usage.output_tokens": self.output_tokens,
            "gen_ai.response.finish_reason": self.finish_reason,
            "aumai.genai.cost_usd": self.cost_usd,
            "aumai.genai.latency_ms": self.latency_ms,
        }
        if self.temperature is not None:
            attrs["gen_ai.request.temperature"] = self.temperature
        if self.max_tokens is not None:
            attrs["gen_ai.request.max_tokens"] = self.max_tokens
        attrs.update(self.extra)
        return attrs


class GenAIMetrics(BaseModel):
    """Aggregated metrics for GenAI telemetry collection."""

    request_count: int = 0
    token_count: int = 0
    error_count: int = 0
    # latency_histogram stores (bucket_upper_ms, count) pairs
    latency_histogram: list[tuple[float, int]] = Field(default_factory=list)

    model_config = {"frozen": False}

    def record_request(
        self,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        error: bool = False,
    ) -> None:
        """Update counters for one completed request."""
        self.request_count += 1
        self.token_count += input_tokens + output_tokens
        if error:
            self.error_count += 1
        self._record_latency(latency_ms)

    def _record_latency(self, latency_ms: float) -> None:
        """Insert into histogram using exponential buckets."""
        buckets = [10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, float("inf")]
        for upper in buckets:
            if latency_ms <= upper:
                # Find existing bucket entry
                for i, (b, _) in enumerate(self.latency_histogram):
                    if b == upper:
                        self.latency_histogram[i] = (b, self.latency_histogram[i][1] + 1)
                        return
                self.latency_histogram.append((upper, 1))
                return
