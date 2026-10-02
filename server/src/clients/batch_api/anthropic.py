"""Anthropic (Claude) Message Batches adapter.

Claude's batch API takes requests *inline* in the create call (no file upload),
which makes it the simplest of the four. Images are inline base64, exactly like
the synchronous AnthropicOcrClient.

Docs: https://docs.anthropic.com/en/docs/build-with-claude/batch-processing
"""

import base64
import hashlib
import logging
from typing import List

import anthropic

from .base import BatchRequest, BatchResult, BatchState, ProviderBatchAdapter, text_to_lines

logger = logging.getLogger(__name__)


def _sniff_media_type(image_base64: str) -> str:
    """Detect the real media type — Claude rejects mismatched declarations."""
    try:
        header = base64.b64decode(image_base64[:24], validate=False)
    except Exception:
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"GIF8"):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class AnthropicBatchAdapter(ProviderBatchAdapter):
    provider = "anthropic"
    # Thinking counts toward max_tokens, and Opus 5.5 always thinks: 4096 truncates.
    max_tokens = 16000

    # Claude only accepts custom_ids matching ^[a-zA-Z0-9_-]{1,64}$, but ours are
    # "<filename>::t<tile>" (e.g. "01_'A_08.jpg::t0"). Base64url fits that alphabet
    # and is reversible, so results still carry the filename (needed for recovery).
    # Names too long for 64 chars fall back to a hash, looked up via wire_id().
    def wire_id(self, custom_id: str) -> str:
        b64 = base64.urlsafe_b64encode(custom_id.encode("utf-8")).decode("ascii").rstrip("=")
        if len(b64) < 64:
            return "b" + b64
        return "h" + hashlib.sha256(custom_id.encode("utf-8")).hexdigest()[:63]

    @staticmethod
    def _from_wire_id(wire: str) -> str:
        if wire.startswith("b"):
            try:
                b64 = wire[1:]
                return base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8")
            except Exception:
                pass
        return wire

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or "claude-haiku-4-5-20251001")
        self.client = anthropic.Anthropic(api_key=api_key)

    def submit(self, requests: List[BatchRequest], label: str = "") -> str:
        # Message Batches have no name/metadata field; label is unused here.
        batch_requests = [
            {
                "custom_id": self.wire_id(r.custom_id),
                "params": {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": r.media_type or _sniff_media_type(r.image_base64),
                                        "data": r.image_base64,
                                    },
                                },
                                {"type": "text", "text": r.prompt},
                            ],
                        }
                    ],
                },
            }
            for r in requests
        ]
        batch = self.client.messages.batches.create(requests=batch_requests)
        logger.info(f"Anthropic batch submitted: {batch.id} ({len(requests)} requests)")
        return batch.id

    @staticmethod
    def _state_of(status: str) -> BatchState:
        # "in_progress" | "canceling" | "ended"
        if status == "ended":
            return BatchState.DONE
        if status == "canceling":
            return BatchState.CANCELLED
        return BatchState.RUNNING

    def poll(self, batch_id: str) -> BatchState:
        return self._state_of(self.client.messages.batches.retrieve(batch_id).processing_status)

    def list_batches(self, limit: int = 50) -> List[dict]:
        out: List[dict] = []
        for b in self.client.messages.batches.list(limit=min(limit, 100)):
            rc = b.request_counts
            out.append({
                "id": b.id,
                "state": self._state_of(b.processing_status).value,
                "status": b.processing_status,
                "created": b.created_at.isoformat() if b.created_at else "",
                "label": "",
                "model": "",
                "request_count": sum(getattr(rc, k, 0) or 0 for k in ("processing", "succeeded", "errored", "canceled", "expired")),
            })
            if len(out) >= limit:
                break
        return out

    def collect(self, batch_id: str) -> List[BatchResult]:
        out: List[BatchResult] = []
        for entry in self.client.messages.batches.results(batch_id):
            cid = self._from_wire_id(entry.custom_id)
            result = entry.result
            rtype = getattr(result, "type", None)
            if rtype == "succeeded":
                usage = getattr(result.message, "usage", None)
                tokens = {
                    "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                    "output_tokens": getattr(usage, "output_tokens", 0) or 0,
                }
                if getattr(result.message, "stop_reason", None) == "max_tokens":
                    out.append(BatchResult(custom_id=cid, error="incomplete response (stop_reason=max_tokens)", **tokens))
                    continue
                try:
                    text = "".join(b.text for b in result.message.content if b.type == "text")
                    out.append(BatchResult(custom_id=cid, lines=text_to_lines(text), **tokens))
                except Exception as e:
                    out.append(BatchResult(custom_id=cid, error=f"parse error: {e}"))
            else:
                # errored | canceled | expired
                detail = getattr(getattr(result, "error", None), "message", None) or rtype
                out.append(BatchResult(custom_id=cid, error=str(detail)))
        return out

    def cancel(self, batch_id: str) -> None:
        try:
            self.client.messages.batches.cancel(batch_id)
        except Exception as e:
            logger.warning(f"Anthropic batch cancel failed for {batch_id}: {e}")
