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
from typing import List, Optional

from openai import OpenAI

from .base import BatchRequest, BatchResult, BatchState, ProviderBatchAdapter, text_to_lines

logger = logging.getLogger(__name__)

_ENDPOINT = "/v1/chat/completions"


class OpenAICompatBatchAdapter(ProviderBatchAdapter):
    provider = "openai"
    base_url: Optional[str] = None  # None => OpenAI default; subclasses override

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
                    "max_tokens": self.max_tokens,
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

    def submit(self, requests: List[BatchRequest]) -> str:
        jsonl = self._build_jsonl(requests)
        upload = self.client.files.create(
            file=("batch_requests.jsonl", io.BytesIO(jsonl)),
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=upload.id,
            endpoint=_ENDPOINT,
            completion_window=self.completion_window,
        )
        logger.info(f"{self.provider} batch submitted: {batch.id} ({len(requests)} requests, input_file={upload.id})")
        return batch.id

    def poll(self, batch_id: str) -> BatchState:
        batch = self.client.batches.retrieve(batch_id)
        status = batch.status
        if status == "completed":
            return BatchState.DONE
        if status in ("failed", "expired"):
            return BatchState.FAILED
        if status in ("cancelling", "cancelled", "canceled"):
            return BatchState.CANCELLED
        # validating | in_progress | finalizing
        return BatchState.RUNNING

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
                    content = body["choices"][0]["message"]["content"] or ""
                    out.append(BatchResult(custom_id=cid, lines=text_to_lines(content)))
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

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or "grok-4-1-fast-non-reasoning")
