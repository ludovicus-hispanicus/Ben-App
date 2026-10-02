"""Provider-batch adapter interface.

These adapters drive the providers' *asynchronous Batch APIs* (Gemini, Claude,
OpenAI, Grok) — submit a whole job, walk away, collect results within ~24h at
50% of the synchronous price. They are deliberately kept OUT of the per-image
``OCRFactory`` / ``BaseOcrClient`` path, which serves the live/synchronous
recognition flow. The batch lifecycle is fundamentally different (submit →
poll → collect), so it gets its own small interface.

One request == one image (or one tile). Each request carries a stable
``custom_id`` so results can be mapped back to a filename (and merged across
tiles) at collection time. This sidesteps all the multi-image-per-call
machinery (identity sentinels, merge-failure redistribution) that the live
batch path needs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


@dataclass
class BatchRequest:
    """A single image to OCR within a batch."""
    custom_id: str          # stable id, e.g. "page001.png::t0" (filename::tile-index)
    image_base64: str
    width: int
    height: int
    prompt: str             # already resolved (plain text) by the caller
    media_type: str = "image/png"


class BatchState(str, Enum):
    """Provider-agnostic lifecycle state."""
    PENDING = "pending"     # accepted / queued / validating
    RUNNING = "running"     # actively processing
    DONE = "done"           # finished — results available (incl. partial success)
    FAILED = "failed"       # whole job failed / expired
    CANCELLED = "cancelled"


@dataclass
class BatchResult:
    """One image's result, keyed by the request's custom_id."""
    custom_id: str
    lines: List[str] = field(default_factory=list)
    error: Optional[str] = None
    # Billed tokens (output includes hidden reasoning). Set on failed results too:
    # a truncated response is still charged.
    input_tokens: int = 0
    output_tokens: int = 0


def text_to_lines(text: str) -> List[str]:
    """Split a raw model response into non-empty, stripped lines.

    Mirrors the parsing the synchronous single-image clients do, so batch
    output and live output are normalised identically before persistence.
    """
    if not text:
        return []
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


class ProviderBatchAdapter(ABC):
    """Common surface for all provider batch adapters.

    Implementations must be cheap to construct (no network in ``__init__``)
    and must not hold long-lived threads — the handler's poller drives them.
    """

    provider: str = "base"

    #: How long to ask the provider to keep the job open. Only OpenAI/Grok
    #: expose this knob; others ignore it.
    completion_window: str = "24h"

    #: Per-request output cap. Whole dictionary pages can be long, so this is
    #: higher than the live single-image default (2048).
    max_tokens: int = 4096

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError(f"API key is required for {self.provider} batch jobs.")
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def submit(self, requests: List[BatchRequest], label: str = "") -> str:
        """Submit all requests as one batch. Returns the provider batch id.

        ``label`` (BEn job id + source name) is attached where the provider
        supports it, so the batch is recognisable in ``list_batches``.
        """

    @abstractmethod
    def poll(self, batch_id: str) -> BatchState:
        """Return the current lifecycle state of a submitted batch."""

    @abstractmethod
    def collect(self, batch_id: str) -> List[BatchResult]:
        """Fetch results for a DONE batch. One BatchResult per custom_id.

        Missing or errored requests are returned with ``error`` set and empty
        ``lines`` rather than omitted, so the caller can account for every id.
        """

    @abstractmethod
    def cancel(self, batch_id: str) -> None:
        """Best-effort cancel of an in-flight batch."""

    def wire_id(self, custom_id: str) -> str:
        """The id actually sent to the provider for ``custom_id``. Identity by
        default; adapters whose API restricts id characters/length override it."""
        return custom_id

    def list_batches(self, limit: int = 50) -> List[dict]:
        """Recent batches on the provider account, newest first — used to recover
        jobs whose local record was lost. Each entry:
        ``{"id", "state" (BatchState value), "status" (raw), "created", "label", "model", "request_count"}``.
        """
        raise NotImplementedError(f"{self.provider} does not support listing batches")

    def cleanup(self, batch_id: str) -> None:
        """Delete any provider-side artefacts (uploaded input/output files).

        Default no-op; providers that upload files override this. Always
        best-effort — must never raise.
        """
        return None
