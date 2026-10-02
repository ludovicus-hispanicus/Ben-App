"""OpenAI-compatible batch adapter (OpenAI + xAI/Grok).

Both OpenAI and xAI expose the same batch surface: upload a JSONL file
(``purpose="batch"``), create a batch over ``/v1/chat/completions``, poll, then
download the output JSONL. Grok just points the same ``openai`` SDK at
``https://api.x.ai/v1``.

Image input is inline as a base64 data URL — identical wire format to the
synchronous OpenAIOcrClient / GrokOcrClient.

Docs: https://platform.openai.com/docs/guides/batch
      https://docs.x.ai/developers/advanced-api-usage/batch-api
"""

import io
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from openai import OpenAI

from ..openai_client import openai_token_params
from .base import BatchRequest, BatchResult, BatchState, ProviderBatchAdapter, text_to_lines

logger = logging.getLogger(__name__)

_ENDPOINT = "/v1/chat/completions"


class OpenAICompatBatchAdapter(ProviderBatchAdapter):
    provider = "openai"
    base_url: Optional[str] = None  # None => OpenAI default; subclasses override
    supports_metadata = True  # OpenAI batch ``metadata``; unverified on xAI, so Grok opts out

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or "gpt-4o")
        kwargs = {"api_key": api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self.client = OpenAI(**kwargs)

    def _build_jsonl(self, requests: List[BatchRequest]) -> bytes:
        lines = []
        for r in requests:
            lines.append(json.dumps({
                "custom_id": r.custom_id,
                "method": "POST",
                "url": _ENDPOINT,
                "body": {
                    "model": self.model,
                    **self._token_params(),
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": r.prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{r.media_type or 'image/png'};base64,{r.image_base64}"
                                    },
                                },
                            ],
                        }
                    ],
                },
            }))
        return ("\n".join(lines)).encode("utf-8")

    def _token_params(self) -> dict:
        return openai_token_params(self.model, self.max_tokens)

    def submit(self, requests: List[BatchRequest], label: str = "") -> str:
        jsonl = self._build_jsonl(requests)
        upload = self.client.files.create(
            file=("batch_requests.jsonl", io.BytesIO(jsonl)),
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=upload.id,
            endpoint=_ENDPOINT,
            completion_window=self.completion_window,
            **({"metadata": {"ben_label": label[:512]}} if label and self.supports_metadata else {}),
        )
        logger.info(f"{self.provider} batch submitted: {batch.id} ({len(requests)} requests, input_file={upload.id})")
        return batch.id

    @staticmethod
    def _state_of(status: str) -> BatchState:
        if status == "completed":
            return BatchState.DONE
        if status in ("failed", "expired"):
            return BatchState.FAILED
        if status in ("cancelling", "cancelled", "canceled"):
            return BatchState.CANCELLED
        # validating | in_progress | finalizing
        return BatchState.RUNNING

    def poll(self, batch_id: str) -> BatchState:
        return self._state_of(self.client.batches.retrieve(batch_id).status)

    def list_batches(self, limit: int = 50) -> List[dict]:
        out: List[dict] = []
        for b in self.client.batches.list(limit=min(limit, 100)):
            counts = getattr(b, "request_counts", None)
            out.append({
                "id": b.id,
                "state": self._state_of(b.status).value,
                "status": b.status,
                "created": datetime.fromtimestamp(b.created_at, tz=timezone.utc).isoformat() if b.created_at else "",
                "label": (getattr(b, "metadata", None) or {}).get("ben_label", ""),
                "model": getattr(b, "model", "") or "",
                "request_count": getattr(counts, "total", None),
            })
            if len(out) >= limit:
                break
        return out

    def collect(self, batch_id: str) -> List[BatchResult]:
        batch = self.client.batches.retrieve(batch_id)
        out: List[BatchResult] = []

        if batch.output_file_id:
            text = self.client.files.content(batch.output_file_id).text
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                cid = ""
                try:
                    obj = json.loads(line)
                    cid = obj.get("custom_id", "")
                    err = obj.get("error")
                    if err:
                        out.append(BatchResult(custom_id=cid, error=str(err)))
                        continue
                    body = (obj.get("response") or {}).get("body") or {}
                    usage = body.get("usage") or {}
                    # completion_tokens already includes reasoning tokens
                    tokens = {
                        "input_tokens": usage.get("prompt_tokens", 0) or 0,
                        "output_tokens": usage.get("completion_tokens", 0) or 0,
                    }
                    choice = body["choices"][0]
                    if choice.get("finish_reason") not in (None, "stop"):
                        out.append(BatchResult(custom_id=cid, error=f"incomplete response (finish_reason={choice['finish_reason']})", **tokens))
                        continue
                    content = choice["message"]["content"] or ""
                    out.append(BatchResult(custom_id=cid, lines=text_to_lines(content), **tokens))
                except Exception as e:
                    out.append(BatchResult(custom_id=cid, error=f"parse error: {e}"))

        # Pick up per-request errors from the error file too
        if getattr(batch, "error_file_id", None):
            try:
                etext = self.client.files.content(batch.error_file_id).text
                for line in etext.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    out.append(BatchResult(
                        custom_id=obj.get("custom_id", ""),
                        error=str(obj.get("error") or obj.get("response") or "errored"),
                    ))
            except Exception as e:
                logger.warning(f"{self.provider} batch {batch_id}: could not read error file: {e}")

        return out

    def cancel(self, batch_id: str) -> None:
        try:
            self.client.batches.cancel(batch_id)
        except Exception as e:
            logger.warning(f"{self.provider} batch cancel failed for {batch_id}: {e}")

    def cleanup(self, batch_id: str) -> None:
        try:
            batch = self.client.batches.retrieve(batch_id)
            for fid in (batch.input_file_id, batch.output_file_id, getattr(batch, "error_file_id", None)):
                if fid:
                    try:
                        self.client.files.delete(fid)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"{self.provider} batch cleanup failed for {batch_id}: {e}")


class OpenAIBatchAdapter(OpenAICompatBatchAdapter):
    provider = "openai"
    base_url = None


class GrokBatchAdapter(OpenAICompatBatchAdapter):
    """xAI Grok — OpenAI-compatible batch surface at api.x.ai.

    NOTE: xAI's Batch API launched Feb 2026 and is OpenAI-compatible, but the
    files+batches surface should be validated against a live key on first use
    (this is the one provider whose batch endpoints we couldn't introspect
    locally). If xAI diverges, swap to the official ``xai-sdk`` here.
    """
    provider = "grok"
    base_url = "https://api.x.ai/v1"
    supports_metadata = False

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or "grok-4-1-fast-non-reasoning")

    def _token_params(self) -> dict:
        return {"max_tokens": self.max_tokens}
