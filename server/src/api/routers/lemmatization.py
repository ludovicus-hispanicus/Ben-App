"""
Lemmatization API Router

Endpoints for ATF tokenization, dictionary management,
lemmatization CRUD, AI suggestions, and eBL export.
"""

import re
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from entities.lemmatization import (
    TokenizedText, TextLemmatization, LineLemmatization, LemmaAssignment,
    WordEntry, DictionaryStatus
)
from handlers.lemmatization_handler import lemmatization_handler
from handlers.ebl_handler import EblHandler
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/lemmatization",
    tags=["lemmatization"],
    responses={404: {"description": "Not found"}}
)

# Shared eBL handler instance for dictionary download and export
_ebl_handler = EblHandler()


# ==========================================
# DTOs
# ==========================================

class TokenizeRequest(BaseModel):
    atf_text: str


class SaveLemmatizationRequest(BaseModel):
    production_id: int
    content_hash: str
    lines: List[LineLemmatization]
    ai_suggested: bool = False


class AiSuggestRequest(BaseModel):
    atf_text: str
    production_id: Optional[int] = None


class ExportEblRequest(BaseModel):
    fragment_number: str


class WordSearchRequest(BaseModel):
    query: str
    limit: int = 20


# ==========================================
# Tokenization
# ==========================================

@router.post("/tokenize", response_model=TokenizedText)
async def tokenize(request: TokenizeRequest):
    """Tokenize ATF text and return structured tokens with dictionary suggestions."""
    try:
        result = lemmatization_handler.tokenize(request.atf_text)
        return result
    except Exception as e:
        logger.error(f"Tokenization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Dictionary
# ==========================================

@router.get("/dictionary/status", response_model=DictionaryStatus)
async def dictionary_status():
    """Get local dictionary status."""
    return lemmatization_handler.get_dictionary_status()


@router.post("/dictionary/download")
async def dictionary_download():
    """Download/refresh the eBL dictionary. Public — uses eBL token if available."""
    _ebl_handler._load_config()
    api_url = _ebl_handler.api_url or "https://www.ebl.lmu.de/api"

    access_token = ""
    if _ebl_handler.is_configured:
        try:
            await _ebl_handler.ensure_valid_token()
            access_token = _ebl_handler.access_token or ""
        except Exception:
            access_token = ""

    result = await lemmatization_handler.download_dictionary(api_url, access_token)
    return result


@router.api_route("/dictionary/rebuild-index", methods=["GET", "POST"])
async def dictionary_rebuild_index():
    """Rebuild the dictionary lookup index from local files (no download needed)."""
    result = lemmatization_handler._dictionary.rebuild_index()
    return result


@router.get("/dictionary/download/progress")
async def dictionary_download_progress():
    """Get dictionary download progress."""
    service = lemmatization_handler._dictionary
    return {
        "downloading": service.is_downloading,
        "progress": service.download_progress["progress"],
        "total": service.download_progress["total"]
    }


@router.api_route("/signs/download", methods=["GET", "POST"])
async def signs_download():
    """Download the eBL signs database (no auth needed)."""
    result = await lemmatization_handler._dictionary.download_signs()
    return result


@router.api_route("/signs/rebuild-index", methods=["GET", "POST"])
async def signs_rebuild_index():
    """Rebuild the logogram index from local sign files."""
    result = lemmatization_handler._dictionary.rebuild_logogram_index()
    return result


@router.get("/signs/lookup/{logogram:path}")
async def signs_lookup(logogram: str):
    """Look up a logogram and return Akkadian lemma IDs."""
    lemma_ids = lemmatization_handler._dictionary.lookup_logogram(logogram)
    if not lemma_ids:
        return {"logogram": logogram, "lemma_ids": [], "entries": []}
    entries = []
    for lid in lemma_ids:
        entry = lemmatization_handler.get_word_entry(lid)
        if entry:
            entries.append(entry.dict())
    return {"logogram": logogram, "lemma_ids": lemma_ids, "entries": entries}


@router.get("/dictionary/lookup/{form}")
async def dictionary_lookup(form: str):
    """Look up a form in the dictionary."""
    entries = lemmatization_handler.lookup_word(form)
    return [e.dict() for e in entries]


@router.get("/dictionary/word/{word_id:path}")
async def dictionary_word(word_id: str):
    """Get a full word entry by ID."""
    entry = lemmatization_handler.get_word_entry(word_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Word '{word_id}' not found")
    return entry.dict()


@router.post("/dictionary/search")
async def dictionary_search(request: WordSearchRequest):
    """Search dictionary words."""
    entries = lemmatization_handler.search_words(request.query, request.limit)
    return [e.dict() for e in entries]


# ==========================================
# Lemmatization CRUD
# ==========================================

@router.get("/{production_id}")
async def get_lemmatization(production_id: int):
    """Get saved lemmatization for a production text."""
    result = lemmatization_handler.get_lemmatization(production_id)
    if not result:
        raise HTTPException(status_code=404, detail="No lemmatization found")
    return result.dict()


@router.put("/{production_id}")
async def save_lemmatization(production_id: int, request: SaveLemmatizationRequest):
    """Save or update lemmatization for a production text."""
    lemmatization = TextLemmatization(
        production_id=production_id,
        content_hash=request.content_hash,
        lines=request.lines,
        ai_suggested=request.ai_suggested
    )
    result = lemmatization_handler.save_lemmatization(lemmatization)
    return result.dict()


class CustomMappingRequest(BaseModel):
    form: str       # The ATF token form (e.g., "i-ba-aš-ši")
    lemma_id: str   # The lemma to assign (e.g., "bašû I")


@router.post("/dictionary/custom-mapping")
async def add_custom_mapping(request: CustomMappingRequest):
    """Store a user-defined form→lemma mapping for future lookups."""
    lemmatization_handler._dictionary.add_custom_mapping(request.form, request.lemma_id)
    return {"success": True, "form": request.form, "lemma_id": request.lemma_id}


@router.delete("/{production_id}")
async def delete_lemmatization(production_id: int):
    """Delete lemmatization for a production text."""
    success = lemmatization_handler.delete_lemmatization(production_id)
    if not success:
        raise HTTPException(status_code=404, detail="No lemmatization found to delete")
    return {"success": True}


# ==========================================
# AI Suggestions
# ==========================================

@router.post("/{production_id}/ai-suggest")
async def ai_suggest(production_id: int, request: AiSuggestRequest):
    """Get AI-powered lemma suggestions for a text."""
    try:
        from services.lemmatization_ai_service import LemmatizationAiService
        ai_service = LemmatizationAiService()
        result = await ai_service.suggest(
            atf_text=request.atf_text,
            production_id=production_id,
            tokenizer=lemmatization_handler._tokenizer,
            dictionary=lemmatization_handler._dictionary
        )
        return result.dict()
    except ImportError:
        raise HTTPException(status_code=501, detail="AI lemmatization service not available")
    except Exception as e:
        logger.error(f"AI suggestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Re-resolve old ORACC format entries
# ==========================================

# Regex to detect old-format ORACC entries: "lemma (guideword) [POS]"
# POS can have apostrophes (e.g., 'CN, V'N, PRP'SBJ) and quotes in citation
_ORACC_OLD_FORMAT_RE = re.compile(r'^"?(.+?)"?\s+\(([^)]*)\)\s+\[([A-Z\x27]+)\]$')


@router.post("/{production_id}/re-align")
async def re_align_lemmatization(production_id: int):
    """
    Re-align lemmatization assignments to tokens using content-aware matching.

    When the original import used pure positional matching, lem entries may be
    assigned to wrong tokens (e.g., šumma I on {mul}UDU.IDIM instead of DIŠ).
    This re-shuffles by verifying each (lem, token) pair and skipping mismatches.
    Also re-resolves any old-format entries.

    Works on ALL assignments that have a unique_lemma (not just suggestions).
    """
    lem = lemmatization_handler.get_lemmatization(production_id)
    if not lem:
        raise HTTPException(status_code=404, detail="No lemmatization found")

    from handlers.production_texts_handler import production_texts_handler
    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text or not prod_text.content:
        raise HTTPException(status_code=404, detail="No production text content found")

    dictionary = lemmatization_handler._dictionary
    from services.oracc_atf_import_service import oracc_import_service

    text_lines = oracc_import_service._extract_text_lines(prod_text.content)

    realigned = 0
    re_resolved = 0

    for line_idx, lem_line in enumerate(lem.lines):
        if line_idx >= len(text_lines):
            break

        _, line_content = text_lines[line_idx]
        tokens = oracc_import_service._extract_tokens(line_content)

        # Extract non-empty lem entries (preserving order, skipping empty ones)
        lem_queue = []
        for tok in lem_line.tokens:
            if tok.unique_lemma:
                # Re-resolve old format entries while we're at it
                entry_val = tok.unique_lemma[0]
                old_match = _ORACC_OLD_FORMAT_RE.match(entry_val)
                if old_match and dictionary._loaded:
                    citation = old_match.group(1).strip()
                    guideword = old_match.group(2).strip()
                    pos = old_match.group(3).strip()
                    ebl_id = dictionary.resolve_oracc_lemma(citation, guideword, pos)
                    if ebl_id:
                        re_resolved += 1
                        lem_queue.append({
                            'ebl_id': ebl_id,
                            'unique_lemma': [ebl_id],
                            'oracc_citation': citation,
                            'oracc_guideword': guideword,
                            'oracc_pos': pos,
                            'is_suggestion': tok.is_suggestion,
                            'suggestion_source': tok.suggestion_source or 'atf_import',
                        })
                        continue

                lem_queue.append({
                    'ebl_id': entry_val if '(' not in entry_val else None,
                    'unique_lemma': tok.unique_lemma,
                    'oracc_citation': tok.oracc_citation,
                    'oracc_guideword': tok.oracc_guideword,
                    'oracc_pos': tok.oracc_pos,
                    'is_suggestion': tok.is_suggestion,
                    'suggestion_source': tok.suggestion_source,
                })

        # Re-align: walk through tokens, consuming lem_queue entries
        new_assignments = []
        q_idx = 0

        for i, token in enumerate(tokens):
            if q_idx >= len(lem_queue):
                new_assignments.append(LemmaAssignment(value=token, unique_lemma=[]))
                continue

            entry = lem_queue[q_idx]
            ebl_id = entry['ebl_id']

            # Check compatibility between this token and this lem entry
            compatible = True
            if ebl_id and dictionary._loaded:
                compatible = oracc_import_service._is_compatible(token, ebl_id, dictionary)

            if not compatible:
                # Look ahead: does the NEXT token match this lem entry?
                if i + 1 < len(tokens):
                    next_tok = tokens[i + 1]
                    if oracc_import_service._is_compatible(next_tok, ebl_id, dictionary):
                        # Skip current token (it's a standalone determinative or extra token)
                        new_assignments.append(LemmaAssignment(value=token, unique_lemma=[]))
                        realigned += 1
                        continue

            # Assign this lem entry to this token
            new_assignments.append(LemmaAssignment(
                value=token,
                unique_lemma=entry['unique_lemma'],
                is_suggestion=entry.get('is_suggestion', True),
                suggestion_source=entry.get('suggestion_source', 'atf_import'),
                oracc_guideword=entry.get('oracc_guideword', ''),
                oracc_citation=entry.get('oracc_citation', ''),
                oracc_pos=entry.get('oracc_pos', ''),
            ))
            q_idx += 1

        lem_line.tokens = new_assignments

    lemmatization_handler.save_lemmatization(lem)

    return {
        "production_id": production_id,
        "realigned": realigned,
        "re_resolved": re_resolved,
    }


@router.post("/{production_id}/re-resolve")
async def re_resolve_oracc_lemmas(production_id: int):
    """
    Re-resolve old-format ORACC lemma entries using the English-first dictionary lookup.

    Old format: "uhharamma (delay) [V]" — stored when initial import couldn't resolve.
    New logic tries English guideword first (e.g., "delay"), then Akkadian fallback.
    Only updates tokens that match the old format; leaves accepted assignments untouched.
    """
    lem = lemmatization_handler.get_lemmatization(production_id)
    if not lem:
        raise HTTPException(status_code=404, detail="No lemmatization found")

    dictionary = lemmatization_handler._dictionary
    if not dictionary._loaded:
        raise HTTPException(status_code=400, detail="Dictionary not loaded")

    resolved_count = 0
    total_old = 0

    for line in lem.lines:
        for token in line.tokens:
            if not token.unique_lemma:
                continue

            # Check if any entry matches old ORACC format
            new_lemmas = []
            changed = False
            for entry in token.unique_lemma:
                match = _ORACC_OLD_FORMAT_RE.match(entry)
                if match:
                    total_old += 1
                    citation = match.group(1).strip()
                    guideword = match.group(2).strip()
                    pos = match.group(3).strip()

                    # Re-resolve using English-first lookup
                    ebl_id = dictionary.resolve_oracc_lemma(citation, guideword, pos)
                    if ebl_id:
                        new_lemmas.append(ebl_id)
                        resolved_count += 1
                        changed = True

                        # Store suggestion metadata
                        token.is_suggestion = True
                        token.suggestion_source = "atf_import"
                        token.oracc_guideword = guideword
                        token.oracc_citation = citation
                        token.oracc_pos = pos
                    else:
                        # Still unresolved — keep old format
                        new_lemmas.append(entry)
                        token.is_suggestion = True
                        token.suggestion_source = "atf_import"
                        token.oracc_guideword = guideword
                        token.oracc_citation = citation
                        token.oracc_pos = pos
                else:
                    new_lemmas.append(entry)

            if changed:
                token.unique_lemma = new_lemmas

    # Save updated lemmatization
    if resolved_count > 0 or total_old > 0:
        lemmatization_handler.save_lemmatization(lem)

    logger.info(f"Re-resolved {resolved_count}/{total_old} old ORACC entries for production {production_id}")
    return {
        "production_id": production_id,
        "total_old_format": total_old,
        "resolved": resolved_count,
        "still_unresolved": total_old - resolved_count,
    }


# ==========================================
# eBL Export
# ==========================================

@router.post("/{production_id}/export-ebl")
async def export_ebl(production_id: int, request: ExportEblRequest):
    """Export lemmatization to eBL."""
    _ebl_handler._load_config()
    if not _ebl_handler.is_configured:
        raise HTTPException(status_code=400, detail="eBL is not configured")

    result = await lemmatization_handler.export_to_ebl(
        production_id=production_id,
        fragment_number=request.fragment_number,
        ebl_handler=_ebl_handler
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Export failed"))

    return result
