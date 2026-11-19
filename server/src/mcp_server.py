"""
BEn PDF text tools for Claude (or any MCP client), over stdio.

Gives an agent the text of a PDF page by page without it reading every page
image itself. Born-digital pages come from the embedded text layer; scanned
pages are read by a local vision model in Ollama (Qwen3-VL), optionally region
by region as found by one of BEn's YOLO layout models. Everything runs on this
machine.

The agent is the reviewer: prepare_extraction processes one or two sample pages
and returns each page image next to the text BEn proposes for it. The agent
compares them and calls approve_extraction; only then does the whole document
run. So the agent pays for one or two page images per document, not for all.

Register once for every Claude Code session:
    claude mcp add --scope user ben-pdf -- py <path>/server/src/mcp_server.py

Needs Ollama running for scanned pages; the BEn server itself is not needed.
"""

import json
import logging
import os
import sys
import time

# Run from server/src whatever the client's working directory: BEn's modules are
# imported from here and its data folder ("data") is relative to it.
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

# stdout carries the MCP protocol: every log line must go to stderr.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

try:  # MCP SDK 2.x renamed FastMCP to MCPServer; same decorator API
    from mcp.server.mcpserver import MCPServer as FastMCP, Image  # noqa: E402
except ImportError:
    from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

import fitz  # noqa: E402

from services import pdf_text_service as pts  # noqa: E402

mcp = FastMCP(
    "ben-pdf",
    instructions=(
        "Text of PDFs, page by page, made locally by BEn. Workflow: "
        "1) prepare_extraction(path) decides per page between the embedded text layer and local "
        "OCR (Qwen3-VL in Ollama), runs one or two sample pages and returns each page image with "
        "the proposed text. 2) You review: compare image and text closely (diacritics š ṣ ṭ ḫ, "
        "macrons, subscripts, superscript footnote numbers and determinatives, brackets, reading "
        "order, missing or invented lines). Use view_page to zoom into a region. 3) If it is good, "
        "approve_extraction(plan_id, notes); if not, call prepare_extraction again with other "
        "settings (mode='ocr', layout='columns' or 'yolo:<model>', another model, a prompt), or "
        "stop and tell the user. 4) Poll job_status, then read_pages with a range (up to ~60k "
        "characters per call) or read document.txt in out_dir. Embedded text is exact; OCR text "
        "from a small local model is a draft even after approval."
    ),
)


def _sample_blocks(plan: "pts.Plan", samples):
    """MCP content: for every sample page its image (OCR regions drawn and numbered) and text."""
    blocks = []
    with fitz.open(plan.path) as doc:
        for s in samples:
            n = s["page"]
            regions = None
            if s.get("regions"):
                regions = [{"rect": fitz.Rect(r["rect"]), "label": r["label"]} for r in s["regions"]]
            blocks.append(Image(data=pts.page_preview(doc[n - 1], regions), format="jpeg"))
            head = f"=== page {n}: proposed text ({s.get('method', s.get('status'))}) ==="
            if regions and len(regions) > 1:
                head += "\nregions in reading order: " + "; ".join(
                    f"{i} {r['label']}" for i, r in enumerate(regions, 1))
            if s.get("warnings"):
                head += "\nwarnings: " + " | ".join(s["warnings"])
            blocks.append(head + "\n" + (s.get("text") if s.get("status") == "done" else f"FAILED: {s.get('error')}"))
    return blocks


@mcp.tool()
def inspect_pdf(path: str) -> dict:
    """Check every page of a PDF: does it have a trustworthy embedded text layer, or does it
    need OCR (scan, invisible OCR layer, font without Unicode mapping, garbled text)?
    Fast (well under a second for a 50-page article). Returns page ranges per route."""
    return pts.inspect_pdf(path)


@mcp.tool()
def prepare_extraction(
    path: str,
    pages: str = "all",
    mode: str = "auto",
    layout: str = "page",
    model: str = "",
    dpi: int = pts.DEFAULT_DPI,
    prompt: str = pts.DEFAULT_PROMPT,
    sample_pages: str = "",
    out_dir: str = "",
):
    """Make an extraction plan and run it on sample pages for your review. Returns the plan,
    then for each sample page its image and the text BEn proposes. Nothing else is processed
    until you call approve_extraction.

    pages: "all", or ranges like "1-5,9".
    mode: "auto" (embedded text where trustworthy, OCR elsewhere), "embedded", or "ocr".
    layout (OCR pages only): "page" whole page; "columns" split at the column gutter (two-
      column journals; a running header gets cut); "yolo:<model>" OCR region by region in
      reading order, regions from a BEn YOLO model (see list_models; "yolo:" = active model).
    model: Ollama vision model for OCR pages; empty = best installed local Qwen3-VL.
    dpi: render resolution for OCR (300 usual).
    prompt: BEn prompt key ("exact_copy", "plain", "dictionary", "ebl_atf", ...) or raw text.
    sample_pages: pages to sample, e.g. "12" or "3,17"; empty = BEn picks the hardest
      embedded page (most diacritics and warnings) and a middle OCR page.
    out_dir: empty = BEn's data/pdf_text/<pdf name>.
    An OCR sample takes 20-90 s on the local GPU; embedded samples are instant.
    """
    plan = pts.make_plan(path=path, pages=pages, mode=mode, model=model or None, dpi=dpi,
                         layout=layout, prompt=prompt, out_dir=out_dir or None)
    samples = plan.run_samples(sample_pages or None)
    routes = {}
    for n in plan.pages:
        routes.setdefault(plan.route(n), []).append(n)
    head = {
        "plan_id": plan.id,
        "pdf": plan.path,
        "page_count": plan.page_count,
        "routes": {k: pts._ranges(v) for k, v in routes.items()},
        "settings": plan.settings(),
        "sample_pages": [s["page"] for s in samples],
        "next": "Compare each image with its text. Good: approve_extraction(plan_id, notes). "
                "Not good: prepare_extraction again with other settings.",
    }
    return [json.dumps(head, ensure_ascii=False, indent=1)] + _sample_blocks(plan, samples)


@mcp.tool()
def view_page(path: str, page: int, region: str = ""):
    """Image of a PDF page for checking, or a zoom into part of it. region: "x0,y0,x1,y1" as
    fractions of the page (e.g. "0,0.5,0.5,1" = bottom-left quarter); empty = whole page."""
    with fitz.open(path) as doc:
        p = doc[page - 1]
        clip = None
        if region:
            x0, y0, x1, y1 = [float(v) for v in region.split(",")]
            r = p.rect
            clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
        return Image(data=pts.page_preview(p, clip=clip), format="jpeg")


@mcp.tool()
def approve_extraction(plan_id: str, notes: str = "", overwrite: bool = False, wait_seconds: int = 20) -> dict:
    """Approve a plan whose sample pages you checked, and run it on all its pages locally.
    notes: what you checked and found (kept in manifest.json with the approval).
    overwrite: redo pages finished earlier with the same settings (otherwise skipped, so an
      interrupted run can simply be approved again).
    Writes page_0001.txt ..., document.txt and manifest.json to out_dir. Waits up to
    wait_seconds (embedded-only PDFs usually finish), then poll job_status."""
    plan = pts.get_plan(plan_id)
    if not plan:
        return {"error": f"no plan {plan_id} in this session; run prepare_extraction"}
    plan.approved = {"approved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "notes": notes}
    job = pts.start_job(plan, overwrite=overwrite)
    deadline = time.time() + max(0, wait_seconds)
    while job.status in ("pending", "running") and time.time() < deadline:
        time.sleep(0.5)
    return job.summary()


@mcp.tool()
def job_status(job_id: str) -> dict:
    """Progress of an approved extraction: pages done, method per page, failures, warnings."""
    job = pts.get_job(job_id)
    if not job:
        return {"error": f"no job {job_id} in this session; the results stay in its out_dir (manifest.json)"}
    return job.summary()


@mcp.tool()
def cancel_job(job_id: str) -> dict:
    """Stop an extraction after the page it is on. Finished pages are kept."""
    job = pts.get_job(job_id)
    if not job:
        return {"error": f"no job {job_id}"}
    job.cancelled = True
    return {"job_id": job_id, "status": "cancelling"}


MAX_READ_CHARS = 60_000  # about 15k tokens per call


@mcp.tool()
def read_pages(out_dir: str, pages: str = "all") -> dict:
    """Text of extracted pages ("all", "4-20", "7"), each under a header naming how it was
    obtained (embedded or ocr:<model>). Stops at about 60,000 characters; "next_page" then
    says where to continue. Reading document.txt in out_dir directly works as well."""
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    parts, size, next_page, missing, warnings = [], 0, None, [], {}
    for n in pts.parse_pages(pages, manifest.get("page_count", 0)):
        entry = manifest["pages"].get(str(n))
        if not entry or entry.get("status") != "done":
            missing.append(n)
            continue
        with open(os.path.join(out_dir, f"page_{n:04d}.txt"), encoding="utf-8") as f:
            text = f.read().rstrip()
        if parts and size + len(text) > MAX_READ_CHARS:
            next_page = n
            break
        parts.append(f"=== page {n} ({entry['method']}) ===\n{text}\n")
        size += len(text)
        if entry.get("warnings"):
            warnings[n] = entry["warnings"]
    return {"text": "\n".join(parts), "next_page": next_page, "not_extracted": pts._ranges(missing),
            "warnings": warnings}


@mcp.tool()
def list_models() -> dict:
    """OCR models (vision models in the local Ollama) and layout models (BEn's trained YOLO
    models with their region classes) usable in prepare_extraction."""
    from services.ollama_ocr_service import list_vision_models
    ocr = list_vision_models()
    out = {
        "ollama_available": ocr.get("ollama_available"),
        "ocr_models": [{k: m.get(k) for k in ("name", "cloud", "parameter_size", "size_gb")} for m in ocr.get("models", [])],
        "ocr_default": pts.default_ocr_model() if ocr.get("ollama_available") else None,
    }
    try:
        from clients.yolo_training_client import yolo_training_client
        active = (yolo_training_client.get_active_model() or {}).get("model_name")
        out["layout_models"] = [
            {"layout": f"yolo:{m['model_id']}", "classes": [c["name"] for c in m.get("classes", [])],
             "trained_on": m.get("dataset_name"), "mAP50": round((m.get("metrics") or {}).get("mAP50", 0), 3),
             "active": m["model_id"] == active}
            for m in yolo_training_client.list_models().get("models", [])]
    except Exception as e:
        out["layout_models_error"] = str(e)
    return out


if __name__ == "__main__":
    mcp.run()
