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

Results live in BEn: every page is stored as a CuReD text (page image + lines)
in the dataset "PDF extractions/<pdf name>", where people see and correct it,
and agents read the text back from BEn (list_documents, read_pages), so they
get the corrected version and never extract a PDF twice. Storage goes through
the BEn server's API (started headless if it is not running).

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
        "stop and tell the user. 4) Poll job_status; the pages are stored in BEn (CuReD dataset "
        "'PDF extractions/<pdf name>'), where people can correct them. 5) Read them from BEn with "
        "read_pages (current version incl. corrections; up to ~60k characters per call). Before "
        "extracting a PDF, check list_documents: if it is already in BEn, just read it. Embedded "
        "text is exact; OCR text from a small local model is a draft even after approval."
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
def approve_extraction(plan_id: str, notes: str = "", overwrite: bool = False, wait_seconds: int = 20,
                       ben_dataset: str = "PDF extractions") -> dict:
    """Approve a plan whose sample pages you checked, and run it on all its pages locally.
    Every page is stored in BEn as a CuReD text (page image + text lines) in the dataset
    <ben_dataset>/<pdf name>, where people can see and correct it; read it back with
    read_pages. Pages someone worked on in BEn are never read again or replaced, not even
    with overwrite: curated/reviewed, labelled "proofread", or with lines that differ from
    what this tool stored. job_status lists them under ben.left_unchanged_corrected.
    notes: what you checked and found (stored with the approval and on every page in BEn).
    overwrite: redo pages finished earlier with the same settings (otherwise skipped, so an
      interrupted run can simply be approved again).
    ben_dataset: parent dataset in BEn; empty = do not store in BEn (files only).
    Waits up to wait_seconds (embedded-only PDFs usually finish), then poll job_status."""
    plan = pts.get_plan(plan_id)
    if not plan:
        return {"error": f"no plan {plan_id} in this session; run prepare_extraction"}
    plan.approved = {"approved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "notes": notes}
    job = pts.start_job(plan, overwrite=overwrite, ben_parent=ben_dataset or None)
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
NL = chr(10)


def _ben():
    from services.ben_store import BenStore
    store = BenStore()
    store.ensure_running()
    return store


@mcp.tool()
def list_documents(ben_dataset: str = "PDF extractions") -> dict:
    """PDFs whose text is stored in BEn (one dataset each under <ben_dataset>), with page
    counts and how many pages people have corrected there. Check here before extracting a
    PDF again: if it is listed, read it with read_pages."""
    return {"parent": ben_dataset, "documents": _ben().documents(ben_dataset)}


@mcp.tool()
def read_pages(document: str, pages: str = "all", ben_dataset: str = "PDF extractions") -> dict:
    """Text of a PDF's pages as stored in BEn: the current version, including corrections
    people made in BEn. document: the PDF's path or file name, its dataset name (see
    list_documents), or the dataset id. pages: "all", "4-20", "7".
    Each page comes under a header naming how it was made (embedded text layer, or OCR =
    draft) and whether a person has corrected it in BEn. Stops at about 60,000 characters;
    "next_page" then says where to continue."""
    store = _ben()
    from services.ben_store import BenStore
    if document.strip().isdigit():
        dataset_id = int(document)
    else:
        name = os.path.splitext(os.path.basename(document.replace("\\", "/")))[0]
        found = next((d for d in store.documents(ben_dataset) if d["name"] in (name, document)), None)
        if not found:
            return {"error": f"{document!r} is not in BEn under {ben_dataset!r}; see list_documents, "
                             f"or extract it with prepare_extraction + approve_extraction"}
        dataset_id = found["dataset_id"]
    by_page = {}
    for t in store.texts(dataset_id):
        meta = next((m for m in t.get("metadata") or [] if m.get("source") == "ben-pdf"), {})
        pub = BenStore.publication(t) or ""
        n = meta.get("page") or (int(pub.rsplit("/p", 1)[1]) if "/p" in pub and pub.rsplit("/p", 1)[1].isdigit() else None)
        if n:
            by_page[int(n)] = (t, meta)
    count = max(by_page) if by_page else 0
    parts, size, next_page, missing, notes = [], 0, None, [], {}
    for n in pts.parse_pages(pages, count):
        if n not in by_page or not by_page[n][0].get("latest_transliteration_id"):
            missing.append(n)
            continue
        t, meta = by_page[n]
        text = NL.join(store.lines(t["text_id"], t["latest_transliteration_id"]))
        if parts and size + len(text) > MAX_READ_CHARS:
            next_page = n
            break
        how = "embedded text layer" if "pdf-embedded" in (t.get("labels") or []) else f"OCR draft ({meta.get('method', 'ocr')})"
        if BenStore.corrected(t):
            how += "; corrected in BEn"
        parts.append(f"=== page {n} ({how}) ==={NL}{text}{NL}")
        size += len(text)
        if meta.get("warnings") and not BenStore.corrected(t):
            notes[n] = meta["warnings"]
    return {"dataset_id": dataset_id, "text": NL.join(parts), "next_page": next_page,
            "not_in_ben": pts._ranges(missing), "warnings": notes}


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
