"""Anthropic (Claude) Message Batches adapter.

Claude's batch API takes requests *inline* in the create call (no file upload),
which makes it the simplest of the four. Images are inline base64, exactly like
the synchronous AnthropicOcrClient.

Docs: https://docs.anthropic.com/en/docs/build-with-claude/batch-processing
"""

import base64
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

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or "claude-haiku-4-5-20251001")
        self.client = anthropic.Anthropic(api_key=api_key)

    def submit(self, requests: List[BatchRequest]) -> str:
        batch_requests = [
            {
                "custom_id": r.custom_id,
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

    def poll(self, batch_id: str) -> BatchState:
        batch = self.client.messages.batches.retrieve(batch_id)
        status = batch.processing_status  # "in_progress" | "canceling" | "ended"
        if status == "ended":
            return BatchState.DONE
        if status == "canceling":
            return BatchState.CANCELLED
        return BatchState.RUNNING

    def collect(self, batch_id: str) -> List[BatchResult]:
        out: List[BatchResult] = []
        for entry in self.client.messages.batches.results(batch_id):
            cid = entry.custom_id
            result = entry.result
            rtype = getattr(result, "type", None)
            if rtype == "succeeded":
                try:
                    text = result.message.content[0].text
                    out.append(BatchResult(custom_id=cid, lines=text_to_lines(text)))
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
