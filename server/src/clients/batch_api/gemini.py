"""Gemini Batch Mode adapter.

Unlike the other three providers, we drive Gemini via **inline requests**
(``batches.create(src=[InlinedRequest, ...])``) rather than an uploaded JSONL
file. This lets the ``google-genai`` SDK own the wire serialization (we never
hand-write the request JSON / worry about field casing), and avoids the File
API upload+cleanup dance.

The tradeoff is that inline batches have a payload ceiling, so a large folder
is split across several Gemini batch jobs. We join their job names with ``|``
into a single id string so the handler keeps treating ``provider_batch_id`` as
one opaque token; poll/collect/cancel/cleanup fan back out over the parts.

Each request's ``metadata={"key": custom_id}`` is echoed back on the response,
which is how results map to filenames/tiles.

Docs: https://ai.google.dev/gemini-api/docs/batch-api
"""

import base64
import logging
from typing import List

from google import genai
from google.genai import types

from .base import BatchRequest, BatchResult, BatchState, ProviderBatchAdapter, text_to_lines

logger = logging.getLogger(__name__)

_ID_SEP = "|"
# Conservative inline-batch chunking: cap by request count and total base64 bytes.
_MAX_REQUESTS_PER_BATCH = 50
_MAX_BYTES_PER_BATCH = 15 * 1024 * 1024  # ~15 MB of base64 image data


class GeminiBatchAdapter(ProviderBatchAdapter):
    provider = "gemini"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or "gemini-3.1-pro-preview")
        self.client = genai.Client(api_key=api_key)

    # ── submit ──────────────────────────────────────────────────────────
    def _chunk(self, requests: List[BatchRequest]) -> List[List[BatchRequest]]:
        chunks, cur, cur_bytes = [], [], 0
        for r in requests:
            rb = len(r.image_base64)
            if cur and (len(cur) >= _MAX_REQUESTS_PER_BATCH or cur_bytes + rb > _MAX_BYTES_PER_BATCH):
                chunks.append(cur)
                cur, cur_bytes = [], 0
            cur.append(r)
            cur_bytes += rb
        if cur:
            chunks.append(cur)
        return chunks

    def _to_inlined(self, r: BatchRequest) -> types.InlinedRequest:
        return types.InlinedRequest(
            model=self.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=r.prompt),
                        types.Part(inline_data=types.Blob(
                            mime_type=r.media_type or "image/png",
                            data=base64.b64decode(r.image_base64),
                        )),
                    ],
                )
            ],
            config=types.GenerateContentConfig(max_output_tokens=self.max_tokens),
            metadata={"key": r.custom_id},
        )

    def submit(self, requests: List[BatchRequest]) -> str:
        names: List[str] = []
        try:
            for chunk in self._chunk(requests):
                job = self.client.batches.create(
                    model=self.model,
                    src=[self._to_inlined(r) for r in chunk],
                    config=types.CreateBatchJobConfig(display_name="ben-batch-ocr"),
                )
                names.append(job.name)
            logger.info(f"Gemini batch submitted: {len(names)} job(s), {len(requests)} requests")
            return _ID_SEP.join(names)
        except Exception:
            # Roll back any jobs already created so we don't orphan them.
            for n in names:
                try:
                    self.client.batches.cancel(name=n)
                except Exception:
                    pass
            raise

    # ── poll ────────────────────────────────────────────────────────────
    @staticmethod
    def _state_of(job) -> BatchState:
        s = getattr(job.state, "name", str(job.state))
        if s in ("JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"):
            return BatchState.DONE
        if s in ("JOB_STATE_FAILED", "JOB_STATE_EXPIRED"):
            return BatchState.FAILED
        if s == "JOB_STATE_CANCELLED":
            return BatchState.CANCELLED
        return BatchState.RUNNING

    def poll(self, batch_id: str) -> BatchState:
        states = [self._state_of(self.client.batches.get(name=n)) for n in batch_id.split(_ID_SEP)]
        # Aggregate: any still running -> RUNNING; else any failed -> FAILED;
        # else any cancelled -> CANCELLED; else all DONE.
        if any(st == BatchState.RUNNING for st in states):
            return BatchState.RUNNING
        if any(st == BatchState.FAILED for st in states):
            return BatchState.FAILED
        if any(st == BatchState.CANCELLED for st in states):
            return BatchState.CANCELLED
        return BatchState.DONE

    # ── collect ─────────────────────────────────────────────────────────
    @staticmethod
    def _text_of(response) -> str:
        # Prefer the SDK convenience accessor; fall back to walking candidates.
        try:
            t = response.text
            if t:
                return t
        except Exception:
            pass
        try:
            parts = response.candidates[0].content.parts
            return "".join(getattr(p, "text", "") or "" for p in parts)
        except Exception:
            return ""

    def collect(self, batch_id: str) -> List[BatchResult]:
        out: List[BatchResult] = []
        for n in batch_id.split(_ID_SEP):
            job = self.client.batches.get(name=n)
            dest = getattr(job, "dest", None)
            responses = getattr(dest, "inlined_responses", None) or []
            for ir in responses:
                cid = (getattr(ir, "metadata", None) or {}).get("key", "")
                if getattr(ir, "error", None):
                    out.append(BatchResult(custom_id=cid, error=str(ir.error)))
                    continue
                resp = getattr(ir, "response", None)
                if resp is None:
                    out.append(BatchResult(custom_id=cid, error="no response"))
                    continue
                out.append(BatchResult(custom_id=cid, lines=text_to_lines(self._text_of(resp))))
        return out

    # ── cancel / cleanup ────────────────────────────────────────────────
    def cancel(self, batch_id: str) -> None:
        for n in batch_id.split(_ID_SEP):
            try:
                self.client.batches.cancel(name=n)
            except Exception as e:
                logger.warning(f"Gemini batch cancel failed for {n}: {e}")

    def cleanup(self, batch_id: str) -> None:
        # Inline jobs carry no uploaded files; delete the batch job records.
        for n in batch_id.split(_ID_SEP):
            try:
                self.client.batches.delete(name=n)
            except Exception:
                pass
