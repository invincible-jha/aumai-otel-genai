# API Reference — aumai-otel-genai

Complete reference for all public classes, methods, and Pydantic models.

Source modules:
- `aumai_otel_genai.core` — `GenAIInstrumentor`, `GenAISpanProcessor`, `GenAIMetricsCollector`
- `aumai_otel_genai.models` — `GenAISpanAttributes`, `GenAIMetrics`
- `aumai_otel_genai.cli` — CLI entry point (`aumai-otel-genai`)

---

## Module: `aumai_otel_genai.core`

### class `GenAIInstrumentor`

Auto-instruments LLM provider calls with OpenTelemetry tracing.

Manages a single `TracerProvider` shared across all instrumented providers in a process.
Thread-safe for read operations; `instrument()` should be called once at startup.

```python
from aumai_otel_genai.core import GenAIInstrumentor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

# Development: console output
instrumentor = GenAIInstrumentor()

# Production: OTLP exporter with batching
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
instrumentor = GenAIInstrumentor(
    exporter=OTLPSpanExporter(endpoint="http://collector:4317"),
    use_batch=True,
)
```

---

#### `GenAIInstrumentor.__init__()`

```python
def __init__(
    self,
    exporter: SpanExporter | None = None,
    use_batch: bool = False,
) -> None:
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `exporter` | `SpanExporter \| None` | `ConsoleSpanExporter()` | The OTel `SpanExporter` to ship finished spans to. |
| `use_batch` | `bool` | `False` | If `True`, wraps the exporter in `BatchSpanProcessor` for production throughput. If `False`, uses `SimpleSpanProcessor` (synchronous, good for development). |

---

#### `GenAIInstrumentor.instrument()`

```python
def instrument(self, provider: str) -> None:
```

Set up an OTel `TracerProvider` for the given LLM provider. Idempotent: calling multiple times
for the same or different providers does not create additional `TracerProvider` instances.

The first call to `instrument()` creates the `TracerProvider` and attaches the span processor.
Subsequent calls register additional provider names but do not modify the provider configuration.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | `str` | LLM provider name, e.g. `"openai"`, `"anthropic"`. Set as `gen_ai.system` in the OTel resource. |

**Example:**

```python
instrumentor = GenAIInstrumentor()
instrumentor.instrument("openai")
instrumentor.instrument("anthropic")  # idempotent; both registered
```

---

#### `GenAIInstrumentor.create_span()`

```python
@contextmanager
def create_span(
    self,
    operation: str,
    attributes: GenAISpanAttributes,
) -> Generator[Span, None, None]:
```

Context manager that creates an OTel span with all GenAI attributes attached.

If `instrument()` has not been called, it is called automatically using `attributes.provider`.

The span name is `gen_ai.{operation}` (e.g. `gen_ai.chat.completions`).

On entry:
- All `GenAISpanAttributes` fields are mapped to OTel attribute names via `to_otel_dict()`.
- A monotonic start time is recorded.

On exit (no exception):
- `aumai.genai.latency_ms` is set to elapsed wall-clock time in milliseconds.

On exit (exception):
- Span status is set to `StatusCode.ERROR` with the exception message.
- The exception is re-raised unchanged.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `operation` | `str` | Operation suffix for the span name. Common values: `"chat.completions"`, `"completions"`, `"embeddings"`. |
| `attributes` | `GenAISpanAttributes` | Pydantic model carrying all GenAI span attributes. |

**Yields:** `opentelemetry.trace.Span` — the active span, allowing `set_attribute()` calls.

**Raises:** Re-raises any exception thrown inside the `with` block after marking the span as an error.

**Example:**

```python
from aumai_otel_genai.models import GenAISpanAttributes

attrs = GenAISpanAttributes(
    model="gpt-4o",
    provider="openai",
    temperature=0.7,
    max_tokens=256,
)

with instrumentor.create_span("chat.completions", attrs) as span:
    response = my_llm_client.chat(prompt)
    span.set_attribute("gen_ai.usage.input_tokens", response.usage.prompt_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", response.usage.completion_tokens)
    span.set_attribute("gen_ai.response.finish_reason", response.finish_reason)
```

---

#### `GenAIInstrumentor.shutdown()`

```python
def shutdown(self) -> None:
```

Flush all pending spans and shut down the underlying `TracerProvider`. Call this before the
process exits to ensure no spans are lost in `BatchSpanProcessor` buffers.

**Example:**

```python
import atexit

atexit.register(instrumentor.shutdown)
```

---

### class `GenAISpanProcessor`

A simple OTel `SpanProcessor` wrapper that enriches GenAI spans before forwarding them.

Injects `gen_ai.opentelemetry.schema_version = "1.25.0"` into every span's attributes on
`on_end()`, ensuring downstream consumers can identify the semantic convention version in use.

```python
from aumai_otel_genai.core import GenAISpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

base = SimpleSpanProcessor(ConsoleSpanExporter())
enriching = GenAISpanProcessor(inner=base)
# Attach to a TracerProvider manually:
# provider.add_span_processor(enriching)
```

---

#### `GenAISpanProcessor.__init__()`

```python
def __init__(self, inner: Any) -> None:
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `inner` | Any (SpanProcessor) | The inner processor to delegate to after enrichment. |

---

#### `GenAISpanProcessor.on_start()`

```python
def on_start(self, span: Any, parent_context: Any = None) -> None:
```

Delegates directly to the inner processor. No enrichment on span start.

---

#### `GenAISpanProcessor.on_end()`

```python
def on_end(self, span: Any) -> None:
```

Sets `gen_ai.opentelemetry.schema_version` = `"1.25.0"` on the span, then forwards to the
inner processor. If setting the attribute fails (e.g., the span is read-only), the failure is
silently ignored and the inner processor still receives the span.

---

#### `GenAISpanProcessor.shutdown()`

```python
def shutdown(self) -> None:
```

Shuts down the inner processor.

---

#### `GenAISpanProcessor.force_flush()`

```python
def force_flush(self, timeout_millis: int = 30000) -> bool:
```

Flushes the inner processor and returns its result cast to `bool`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout_millis` | `int` | `30000` | Flush timeout in milliseconds. |

---

### class `GenAIMetricsCollector`

Collects and exposes Prometheus-compatible metrics for GenAI calls.

Metrics are accumulated per `provider/model` key in a `GenAIMetrics` instance.
Thread-safety is not guaranteed; use external locking for concurrent writes.

```python
from aumai_otel_genai.core import GenAIMetricsCollector

collector = GenAIMetricsCollector()
```

---

#### `GenAIMetricsCollector.record()`

```python
def record(
    self,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    error: bool = False,
) -> None:
```

Record metrics for a single completed GenAI request.

Increments `request_count` by 1, adds `input_tokens + output_tokens` to `token_count`,
increments `error_count` if `error=True`, and records `latency_ms` in the histogram.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | `str` | LLM provider name, e.g. `"openai"`. |
| `model` | `str` | Model name, e.g. `"gpt-4o"`. |
| `input_tokens` | `int` | Number of input/prompt tokens consumed. |
| `output_tokens` | `int` | Number of output/completion tokens generated. |
| `latency_ms` | `float` | Wall-clock latency in milliseconds. |
| `error` | `bool` | `True` if the request failed. Defaults to `False`. |

**Example:**

```python
collector.record(
    provider="anthropic",
    model="claude-3-5-sonnet-20241022",
    input_tokens=800,
    output_tokens=250,
    latency_ms=520.0,
    error=False,
)
```

---

#### `GenAIMetricsCollector.get_metrics()`

```python
def get_metrics(self, provider: str, model: str) -> GenAIMetrics:
```

Return the accumulated `GenAIMetrics` for a specific provider/model pair. Returns a fresh
zeroed `GenAIMetrics` if no data has been recorded for that key.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | `str` | LLM provider name. |
| `model` | `str` | Model name. |

**Returns:** `GenAIMetrics`

---

#### `GenAIMetricsCollector.all_metrics()`

```python
def all_metrics(self) -> dict[str, GenAIMetrics]:
```

Return all collected metrics keyed by `"{provider}/{model}"` strings.

**Returns:** `dict[str, GenAIMetrics]` — a shallow copy of the internal metrics dict.

---

#### `GenAIMetricsCollector.render_prometheus()`

```python
def render_prometheus(self) -> str:
```

Render all accumulated metrics in Prometheus text exposition format (v0.0.4).

Emits three metric families:

| Metric | Type | Description |
|--------|------|-------------|
| `genai_requests_total` | counter | Total GenAI requests per provider+model |
| `genai_tokens_total` | counter | Total tokens (input + output) per provider+model |
| `genai_errors_total` | counter | Total error responses per provider+model |

**Returns:** `str` — Prometheus exposition text ending with a newline.

**Example output:**

```
# HELP genai_requests_total Total GenAI requests
# TYPE genai_requests_total counter
genai_requests_total{provider="openai",model="gpt-4o"} 42
# HELP genai_tokens_total Total tokens consumed
# TYPE genai_tokens_total counter
genai_tokens_total{provider="openai",model="gpt-4o"} 18900
# HELP genai_errors_total Total GenAI errors
# TYPE genai_errors_total counter
genai_errors_total{provider="openai",model="gpt-4o"} 3
```

---

## Module: `aumai_otel_genai.models`

---

### class `GenAISpanAttributes`

Attributes attached to an OTel span representing a single GenAI call.

Follows the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

```python
from aumai_otel_genai.models import GenAISpanAttributes

attrs = GenAISpanAttributes(
    model="gpt-4o",
    provider="openai",
    input_tokens=512,
    output_tokens=128,
    cost_usd=0.0048,
    temperature=0.7,
    max_tokens=256,
    finish_reason="stop",
)
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `str` | required | Model name, e.g. `"gpt-4o"`, `"claude-3-5-sonnet-20241022"`. |
| `provider` | `str` | required | Provider name, e.g. `"openai"`, `"anthropic"`. |
| `input_tokens` | `int` | `0` | Number of prompt/input tokens. |
| `output_tokens` | `int` | `0` | Number of completion/output tokens. |
| `cost_usd` | `float` | `0.0` | Estimated cost in USD for this call. |
| `temperature` | `float \| None` | `None` | Sampling temperature. Omitted from span attributes if `None`. |
| `max_tokens` | `int \| None` | `None` | Maximum token limit. Omitted from span attributes if `None`. |
| `finish_reason` | `str` | `"stop"` | How the model stopped: `"stop"`, `"length"`, `"content_filter"`, etc. |
| `latency_ms` | `float` | `0.0` | Initial latency value (overwritten by `create_span()` at exit). |
| `extra` | `dict[str, Any]` | `{}` | Arbitrary additional OTel attributes forwarded verbatim. |

---

#### `GenAISpanAttributes.to_otel_dict()`

```python
def to_otel_dict(self) -> dict[str, Any]:
```

Return a flat dict of OTel attribute names mapped to their values. Optional fields
(`temperature`, `max_tokens`) are omitted if `None`. `extra` items are merged in last,
allowing them to override any standard attribute.

**Returns:** `dict[str, Any]`

**OTel attribute mapping:**

| Field | OTel Attribute Name |
|-------|-------------------|
| `provider` | `gen_ai.system` |
| `model` | `gen_ai.request.model` |
| `input_tokens` | `gen_ai.usage.input_tokens` |
| `output_tokens` | `gen_ai.usage.output_tokens` |
| `finish_reason` | `gen_ai.response.finish_reason` |
| `cost_usd` | `aumai.genai.cost_usd` |
| `latency_ms` | `aumai.genai.latency_ms` |
| `temperature` | `gen_ai.request.temperature` (if not None) |
| `max_tokens` | `gen_ai.request.max_tokens` (if not None) |
| `extra.*` | as-is |

---

### class `GenAIMetrics`

Aggregated metrics for a single `provider/model` bucket.

```python
from aumai_otel_genai.models import GenAIMetrics

metrics = GenAIMetrics()
metrics.record_request(input_tokens=500, output_tokens=120, latency_ms=310.0)
print(metrics.request_count)  # 1
print(metrics.token_count)    # 620
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `request_count` | `int` | `0` | Total number of completed requests. |
| `token_count` | `int` | `0` | Total tokens consumed (input + output). |
| `error_count` | `int` | `0` | Total failed requests. |
| `latency_histogram` | `list[tuple[float, int]]` | `[]` | List of `(bucket_upper_ms, count)` pairs. |

Note: `model_config = {"frozen": False}` — these fields are mutable; `record_request()`
modifies them in place.

---

#### `GenAIMetrics.record_request()`

```python
def record_request(
    self,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    error: bool = False,
) -> None:
```

Update counters for one completed request. Increments `request_count`, adds tokens to
`token_count`, conditionally increments `error_count`, and records latency in the histogram.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `input_tokens` | `int` | Input token count for this request. |
| `output_tokens` | `int` | Output token count for this request. |
| `latency_ms` | `float` | Request latency in milliseconds. |
| `error` | `bool` | Whether this request was an error. |

**Histogram buckets (ms):** `10, 50, 100, 250, 500, 1000, 2500, 5000, +Inf`

A latency is placed in the first bucket whose upper bound is >= the measured value.

---

## Module: `aumai_otel_genai.cli`

The CLI is installed as the `aumai-otel-genai` command.

### `aumai-otel-genai instrument`

Set up OTel instrumentation for an LLM provider and optionally emit a demo span.

```bash
aumai-otel-genai instrument \
  --provider openai|anthropic|cohere|google|mistral|custom \
  [--exporter console|memory] \
  [--demo]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | required | LLM provider name |
| `--exporter` | `console` | Span exporter: `console` (stdout) or `memory` (in-process) |
| `--demo` | false | Emit a test span to verify the setup |

---

### `aumai-otel-genai metrics`

Load a JSONL file of usage events and render aggregated metrics.

```bash
aumai-otel-genai metrics \
  [--usage PATH_TO_JSONL] \
  [--format prometheus|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--usage` | None | Path to JSONL file. Each line: `{"provider": "...", "model": "...", "input_tokens": N, "output_tokens": N, "latency_ms": N, "error": bool}` |
| `--format` | `prometheus` | Output format |

---

## Exceptions

| Exception | When Raised |
|-----------|-------------|
| Re-raised from inside `create_span()` block | Any exception raised by the user inside the span context; span is marked ERROR before re-raise. |
| `pydantic.ValidationError` | Constructing `GenAISpanAttributes` or `GenAIMetrics` with invalid field types. |

---

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `_LIBRARY_NAME` | `"aumai.otel-genai"` | OTel tracer instrumentation scope name |
| `_LIBRARY_VERSION` | `"0.1.0"` | OTel tracer instrumentation scope version |
| Schema version attribute | `"gen_ai.opentelemetry.schema_version"` | Injected by `GenAISpanProcessor.on_end()` |
| Schema version value | `"1.25.0"` | OTel GenAI semantic conventions version |
