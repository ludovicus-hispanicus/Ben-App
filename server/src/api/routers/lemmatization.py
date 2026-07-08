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


class AiWordSuggestRequest(BaseModel):
    """Per-word contextual AI suggestion. The client composes the full prompt
    (editable in the UI) and sends it as-is.

    `provider` selects the LLM backend ("gemini", "anthropic", or "openai");
    `model` overrides the default model id; `apiKey` is the user's saved key
    (sourced from the same localStorage entries CuReD uses), and falls back
    to environment variables when omitted."""
    prompt: str
    provider: Optional[str] = None
    model: Optional[str] = None
    apiKey: Optional[str] = None


class AiSuggestAllRequest(BaseModel):
    """Bulk AI lemmatization request. Reuses the same provider/model/apiKey
    fields as the per-word path so the user's saved keys are honoured.
    Server overwrites the existing lemmatization with the AI result (the
    user reviews and corrects each suggestion from the panel).

    `extra_instruction` is an optional editable directive from the production
    AI panel — appended to the system prompt so the user can steer behaviour
    (e.g., "Be conservative on broken signs", "Prefer verbs in the G-stem")."""
    provider: Optional[str] = None
    model: Optional[str] = None
    apiKey: Optional[str] = None
    extra_instruction: Optional[str] = None


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

@router.post("/{production_id}/ai-suggest-all", response_model=TextLemmatization)
async def ai_suggest_all(production_id: int, request: AiSuggestAllRequest):
    """Bulk AI lemmatization for an entire production text.

    Sends the ATF, current ORACC suggestions, dictionary candidates, and the
    user's translation to the chosen LLM. Returned assignments are tagged
    with is_suggestion=True / suggestion_source="ai" so the panel can render
    them in the AI color and the user can confirm or correct each one.

    The result OVERWRITES any existing lemmatization (per the v1 design:
    one bulk AI pass, then the human reviews). The previous lemmatization's
    ORACC priors are still surfaced to the model before the overwrite, so
    they aren't lost as context — just no longer authoritative."""
    try:
        from handlers.production_texts_handler import production_texts_handler
        from services.lemmatization_ai_service import LemmatizationAiService

        prod_text = production_texts_handler.get_by_id(production_id)
        if not prod_text:
            raise HTTPException(status_code=404, detail="Production text not found")
        if not prod_text.content or not prod_text.content.strip():
            raise HTTPException(status_code=400, detail="Production text has no transliteration content")

        existing_lem = lemmatization_handler.get_lemmatization(production_id)

        ai_service = LemmatizationAiService()
        try:
            result = await ai_service.suggest(
                atf_text=prod_text.content,
                production_id=production_id,
                tokenizer=lemmatization_handler._tokenizer,
                dictionary=lemmatization_handler._dictionary,
                translation_content=prod_text.translation_content or "",
                existing_lemmatization=existing_lem,
                provider=request.provider,
                model=request.model,
                api_key=request.apiKey,
                extra_instruction=request.extra_instruction,
            )
        except RuntimeError as parse_err:
            # JSON parse / truncation failure inside _parse_response. Do NOT
            # save anything — the user's existing lemmatization stays intact.
            logger.error(f"AI bulk lemmatization parse failure: {parse_err}")
            raise HTTPException(status_code=502, detail=str(parse_err))

        # Guard: if the AI returned valid JSON but every assignment is empty,
        # saving would wipe whatever the user had before with nothing useful
        # in return. Refuse the save and surface a clear error instead.
        ai_assignment_count = sum(
            1
            for line in result.lines
            for tok in line.tokens
            if tok.unique_lemma
        )
        if ai_assignment_count == 0:
            raise HTTPException(
                status_code=502,
                detail=(
                    "The AI returned a parseable response but produced zero lemma "
                    "assignments. Your previous lemmatization was NOT overwritten. "
                    "Try a more capable model (e.g., Claude Sonnet or Gemini Pro)."
                ),
            )

        # Preserve human-confirmed assignments: copy them from the prior
        # lemmatization back onto the AI result so the AI's overwrite cannot
        # silently replace lemmas the user has already accepted. A token
        # counts as confirmed when it has a non-empty unique_lemma AND
        # is_suggestion is False AND is_cleared is False (cleared means
        # the user actively rejected a lemma here — that "no" is also a
        # decision the AI shouldn't override). Suggestions, empty rows,
        # and tokens that only carry ORACC metadata are NOT preserved.
        preserved = 0
        if existing_lem and existing_lem.lines:
            # Match by line_number when both sides have it; fall back to
            # position so re-tokenized lines (which may produce empty
            # line_number) still align.
            existing_by_ln = {
                ln.line_number: ln for ln in existing_lem.lines if ln.line_number
            }
            for i, new_line in enumerate(result.lines):
                old_line = existing_by_ln.get(new_line.line_number)
                if old_line is None and i < len(existing_lem.lines):
                    old_line = existing_lem.lines[i]
                if old_line is None:
                    continue
                # Match tokens by position within the line — both sides come
                # from the same tokenizer pass over the same ATF, so the
                # ordering is stable for the line-length they share.
                pair_count = min(len(old_line.tokens), len(new_line.tokens))
                for ti in range(pair_count):
                    old_tok = old_line.tokens[ti]
                    new_tok = new_line.tokens[ti]
                    is_human_confirmed = (
                        bool(old_tok.unique_lemma)
                        and not old_tok.is_suggestion
                        and not old_tok.is_cleared
                    )
                    is_human_cleared = (
                        not old_tok.unique_lemma
                        and old_tok.is_cleared
                    )
                    if is_human_confirmed:
                        new_tok.unique_lemma = list(old_tok.unique_lemma)
                        new_tok.is_suggestion = False
                        new_tok.suggestion_source = ""
                        new_tok.is_cleared = False
                        # Keep ORACC metadata on the assignment so the panel
                        # can still surface it next to the confirmed lemma.
                        new_tok.oracc_guideword = old_tok.oracc_guideword
                        new_tok.oracc_citation = old_tok.oracc_citation
                        new_tok.oracc_pos = old_tok.oracc_pos
                        new_tok.ai_responses = dict(old_tok.ai_responses or {})
                        preserved += 1
                    elif is_human_cleared:
                        # User explicitly removed a lemma here — respect that
                        # rejection. Clear whatever the AI proposed and re-set
                        # the cleared flag so auto-assign doesn't refill it.
                        new_tok.unique_lemma = []
                        new_tok.is_suggestion = False
                        new_tok.suggestion_source = ""
                        new_tok.is_cleared = True
                        preserved += 1
        if preserved:
            logger.info(
                f"AI bulk lemmatization: preserved {preserved} human-confirmed/cleared "
                f"assignments through the AI overwrite"
            )

        saved = lemmatization_handler.save_lemmatization(result)
        return saved
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=501, detail="AI lemmatization service not available")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bulk AI lemmatization failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-word-suggest")
async def ai_word_suggest(request: AiWordSuggestRequest):
    """Per-word AI hint: takes the full prompt the user composed in the UI
    (sentence + translation + question) and returns Gemini's freeform
    response. The result is informational only — it is NOT applied as a
    lemma assignment."""
    try:
        from services.lemmatization_ai_service import LemmatizationAiService
        ai_service = LemmatizationAiService()
        text = await ai_service.ask_about_word(
            request.prompt,
            provider=request.provider,
            model=request.model,
            api_key=request.apiKey,
        )
        return {"response": text}
    except ImportError:
        raise HTTPException(status_code=501, detail="AI lemmatization service not available")
    except ValueError as e:
        # Missing API key, etc.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"AI word suggestion failed: {e}")
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
