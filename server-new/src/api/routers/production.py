"""
Production Texts API Router (New CuReD - Curation Tool)

This router handles the scholarly curation workflow:
- Group training data by identifier (Museum number, P-number, Publication)
- Merge parts into production texts
- Edit and manage curated texts
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from entities.production_text import IdentifierType, SourceTextReference, UploadedImage
from handlers.production_texts_handler import production_texts_handler
from common.global_handlers import global_new_text_handler
import logging


router = APIRouter(
    prefix="/api/v1/production",
    tags=["production"],
    responses={404: {"description": "Not found"}}
)


# ==========================================
# DTOs
# ==========================================

class GroupedTextDto(BaseModel):
    identifier: str
    identifier_type: str
    parts: List[dict]  # List of parts with their info
    has_production_text: bool
    production_id: Optional[int] = None


class CreateProductionTextDto(BaseModel):
    identifier: str
    identifier_type: str  # "museum", "p_number", "publication"
    source_text_ids: List[int]  # text_ids from training data
    initial_content: Optional[str] = ""


class UpdateProductionContentDto(BaseModel):
    content: str
    translation_content: Optional[str] = None


class SourceTextInfo(BaseModel):
    text_id: int
    transliteration_id: int
    part: str
    lines: List[str]
    image_name: str


# ==========================================
# Endpoints
# ==========================================

@router.get("/grouped")
async def get_grouped_training_data():
    """
    Get all training data grouped by identifier (Museum number, P-number, Publication).
    This is the main view for the CuReD dashboard.
    """
    from api.dto.text import NewTextPreviewDto

    # Get all texts from training data
    texts = global_new_text_handler.list_texts()

    # Group by museum_id, p_number, and publication_id
    grouped = {}

    for text in texts:
        # Determine the primary identifier
        identifiers = text.text_identifiers

        # Try museum first, then p_number, then publication
        if identifiers.museum and identifiers.museum.get_value():
            key = identifiers.museum.get_value()
            id_type = "museum"
        elif identifiers.p_number and identifiers.p_number.get_value():
            key = identifiers.p_number.get_value()
            id_type = "p_number"
        elif identifiers.publication and identifiers.publication.get_value():
            key = identifiers.publication.get_value()
            id_type = "publication"
        else:
            key = f"unknown_{text.text_id}"
            id_type = "unknown"

        if key not in grouped:
            grouped[key] = {
                "identifier": key,
                "identifier_type": id_type,
                "parts": [],
                "has_production_text": False,
                "production_id": None,
                "is_exported": False
            }

        grouped[key]["parts"].append({
            "text_id": text.text_id,
            "part": text.part or "",
            "transliteration_id": text.latest_transliteration_id,
            "is_curated": text.is_curated,
            "lines_count": text.lines_count,
            "last_modified": text.last_modified,
            "labels": text.labels if hasattr(text, 'labels') and text.labels else ([text.label] if text.label else []),
            "label": text.label or "",
            "project_id": text.project_id
        })

    # Check which groups have production texts (single bulk load instead of per-group queries)
    all_prod_texts = production_texts_handler.get_all()
    prod_lookup = {(pt.identifier, pt.identifier_type): pt for pt in all_prod_texts}

    for key, group in grouped.items():
        id_type_str = group["identifier_type"]
        if id_type_str in ("museum", "p_number", "publication"):
            prod_text = prod_lookup.get((key, id_type_str))
            if prod_text:
                group["has_production_text"] = True
                group["production_id"] = prod_text.production_id
                group["is_exported"] = getattr(prod_text, 'is_exported', False)

    # Sort parts within each group by part number
    for group in grouped.values():
        group["parts"].sort(key=lambda x: x.get("part", ""))

    return list(grouped.values())


@router.get("/search/kwic")
async def search_kwic(q: str, limit: int = 200):
    """
    KWIC concordance search across all transliteration lines.
    Returns matching lines with 1 line of context before and after.
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")
    return global_new_text_handler.search_kwic(query=q.strip(), limit=limit)


@router.get("/text/{production_id}")
async def get_production_text(production_id: int):
    """Get a production text by ID."""
    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text:
        raise HTTPException(status_code=404, detail="Production text not found")
    return prod_text


@router.get("/text/{production_id}/sources")
async def get_production_sources(production_id: int):
    """
    Get the source texts (parts) for a production text with their content.

    Returns:
        - sources: transliteration parts (with images)
        - translations: translation texts (text only, no images)

    Translations are automatically synced - any text with the same identifier
    and label="translation" will be included automatically.
    """
    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text:
        raise HTTPException(status_code=404, detail="Production text not found")

    logging.info(f"Loading sources for production {production_id}, {len(prod_text.source_texts)} source refs")

    # Get current source text_ids for reference
    current_text_ids = {ref.text_id for ref in prod_text.source_texts}

    # Auto-sync: Find all texts with the same identifier (including translations)
    all_texts = global_new_text_handler.list_texts()
    identifier = prod_text.identifier

    # Find all matching texts (translations and any new parts)
    matching_texts = []
    for text in all_texts:
        identifiers = text.text_identifiers
        museum_val = identifiers.museum.get_value() if identifiers.museum else None
        p_number_val = identifiers.p_number.get_value() if identifiers.p_number else None
        pub_val = identifiers.publication.get_value() if identifiers.publication else None

        matches = (
            (museum_val and museum_val == identifier) or
            (p_number_val and p_number_val == identifier) or
            (pub_val and pub_val == identifier)
        )

        if matches:
            matching_texts.append(text)

    logging.info(f"Found {len(matching_texts)} texts with identifier '{identifier}'")

    sources = []
    translations = []

    # Process all matching texts (both stored and auto-discovered)
    for text in matching_texts:
        full_text = global_new_text_handler.get_by_text_id(text.text_id)
        if not full_text or not full_text.transliterations:
            continue

        # Get the latest CuReD transliteration
        cured_trans = [t for t in full_text.transliterations if t.source == "cured"]
        if not cured_trans:
            continue

        trans = cured_trans[-1]
        if not trans.edit_history:
            continue

        latest_edit = trans.edit_history[-1]
        label = getattr(full_text, 'label', '') or ''
        part = getattr(full_text, 'part', '') or ''

        if label == 'translation':
            # Translation: include text only (no image)
            translations.append({
                "text_id": text.text_id,
                "transliteration_id": trans.transliteration_id,
                "part": part,
                "lines": latest_edit.lines,
                "label": label
            })
            logging.info(f"  Translation {text.text_id}: part='{part}', {len(latest_edit.lines)} lines")
        else:
            # Regular transliteration: include with image
            sources.append({
                "text_id": text.text_id,
                "transliteration_id": trans.transliteration_id,
                "part": part,
                "lines": latest_edit.lines,
                "image_name": trans.image_name,
                "label": label
            })
            logging.info(f"  Source {text.text_id}: part='{part}', {len(latest_edit.lines)} lines")

    # Sort sources by part
    sources.sort(key=lambda x: x.get("part", ""))
    translations.sort(key=lambda x: x.get("part", ""))

    logging.info(f"Returning {len(sources)} sources and {len(translations)} translations")
    return {
        "sources": sources,
        "translations": translations
    }


@router.post("/text")
async def create_production_text(request: Request, dto: CreateProductionTextDto):
    """Create a new production text from training data parts."""
    user_id = request.state.user_id

    # Validate identifier type
    try:
        id_type = IdentifierType(dto.identifier_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid identifier type: {dto.identifier_type}")

    # Check if production text already exists
    existing = production_texts_handler.get_by_identifier(dto.identifier, id_type)
    if existing:
        raise HTTPException(status_code=409, detail="Production text already exists for this identifier")

    # Build source text references
    source_refs = []
    source_contents = []

    for text_id in dto.source_text_ids:
        text = global_new_text_handler.get_by_text_id(text_id)
        if not text:
            logging.warning(f"Source text {text_id} not found")
            continue

        # Get the latest CuReD transliteration
        cured_trans = [t for t in text.transliterations if t.source == "cured"]
        if not cured_trans:
            logging.warning(f"No CuReD transliteration found for text {text_id}")
            continue

        trans = cured_trans[-1]  # Get the most recent one
        if not trans.edit_history:
            continue

        latest_edit = trans.edit_history[-1]

        source_refs.append(SourceTextReference(
            text_id=text_id,
            transliteration_id=trans.transliteration_id,
            part=getattr(text, 'part', '') or '',
            image_name=trans.image_name or ''
        ))

        source_contents.append({
            "part": getattr(text, 'part', '') or '',
            "lines": latest_edit.lines
        })

    if not source_refs:
        raise HTTPException(status_code=400, detail="No valid source texts found")

    # Generate initial merged content if not provided
    initial_content = dto.initial_content
    if not initial_content:
        initial_content = production_texts_handler.generate_merged_content(source_contents)

    # Create the production text
    prod_text = production_texts_handler.create(
        identifier=dto.identifier,
        identifier_type=id_type,
        source_texts=source_refs,
        uploader_id=user_id,
        initial_content=initial_content
    )

    return prod_text


@router.put("/text/{production_id}")
async def update_production_text(request: Request, production_id: int, dto: UpdateProductionContentDto):
    """Update the content of a production text."""
    user_id = request.state.user_id

    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text:
        raise HTTPException(status_code=404, detail="Production text not found")

    updated = production_texts_handler.update_content(
        production_id=production_id,
        content=dto.content,
        translation_content=dto.translation_content,
        user_id=user_id
    )

    return updated


@router.post("/text/{production_id}/regenerate")
async def regenerate_production_content(request: Request, production_id: int):
    """Regenerate the production text content from source texts."""
    user_id = request.state.user_id

    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text:
        raise HTTPException(status_code=404, detail="Production text not found")

    # Fetch current source content
    source_contents = []
    for source_ref in prod_text.source_texts:
        text = global_new_text_handler.get_by_text_id(source_ref.text_id)
        if text:
            trans = next(
                (t for t in text.transliterations if t.transliteration_id == source_ref.transliteration_id),
                None
            )
            if trans and trans.edit_history:
                latest_edit = trans.edit_history[-1]
                source_contents.append({
                    "part": source_ref.part,
                    "lines": latest_edit.lines
                })

    # Generate new content
    new_content = production_texts_handler.generate_merged_content(source_contents)

    # Update
    updated = production_texts_handler.update_content(
        production_id=production_id,
        content=new_content,
        user_id=user_id
    )

    return updated


@router.post("/text/{production_id}/sync-sources")
async def sync_production_sources(production_id: int):
    """
    Sync source texts for a production text.
    This adds any new training data parts (like translations) that were added
    after the production text was created.
    """
    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text:
        raise HTTPException(status_code=404, detail="Production text not found")

    # Get all texts from training data with the same identifier
    texts = global_new_text_handler.list_texts()
    identifier = prod_text.identifier
    logging.info(f"Sync sources: Looking for identifier '{identifier}' (type: {prod_text.identifier_type})")

    # Find all matching texts
    matching_texts = []
    for text in texts:
        identifiers = text.text_identifiers

        # Get values for comparison
        museum_val = identifiers.museum.get_value() if identifiers.museum else None
        p_number_val = identifiers.p_number.get_value() if identifiers.p_number else None
        pub_val = identifiers.publication.get_value() if identifiers.publication else None

        matches = (
            (museum_val and museum_val == identifier) or
            (p_number_val and p_number_val == identifier) or
            (pub_val and pub_val == identifier)
        )

        # Log potential matches for debugging
        if museum_val and identifier in str(museum_val):
            logging.info(f"  Text {text.text_id}: museum_val='{museum_val}', label='{text.label}', matches={matches}")

        if matches:
            matching_texts.append(text)

    logging.info(f"Sync sources: Found {len(matching_texts)} matching texts out of {len(texts)} total")

    # Get current source text_ids
    current_text_ids = {ref.text_id for ref in prod_text.source_texts}
    logging.info(f"Sync sources: Current source text_ids: {current_text_ids}")

    # Find new texts to add
    new_source_refs = []
    for text in matching_texts:
        if text.text_id not in current_text_ids:
            # Get the full text to access transliterations
            full_text = global_new_text_handler.get_by_text_id(text.text_id)
            if full_text and full_text.transliterations:
                # Get the latest CuReD transliteration
                cured_trans = [t for t in full_text.transliterations if t.source == "cured"]
                if cured_trans:
                    trans = cured_trans[-1]
                    new_source_refs.append(SourceTextReference(
                        text_id=text.text_id,
                        transliteration_id=trans.transliteration_id,
                        part=getattr(text, 'part', '') or '',
                        image_name=trans.image_name or ''
                    ))

    if new_source_refs:
        # Add new sources to existing list
        updated_sources = list(prod_text.source_texts) + new_source_refs
        production_texts_handler.update_source_texts(production_id, updated_sources)
        logging.info(f"Added {len(new_source_refs)} new source texts to production {production_id}")

    # Return the updated production text
    updated_prod_text = production_texts_handler.get_by_id(production_id)
    return {
        "success": True,
        "added_count": len(new_source_refs),
        "total_sources": len(updated_prod_text.source_texts) if updated_prod_text else 0
    }


@router.delete("/text/{production_id}")
async def delete_production_text(production_id: int):
    """Delete a production text."""
    result = production_texts_handler.delete(production_id)
    if not result:
        raise HTTPException(status_code=404, detail="Production text not found")
    return {"deleted": True}


@router.post("/text/{production_id}/mark-exported")
async def mark_production_exported(production_id: int):
    """Mark a production text as exported to eBL."""
    prod_text = production_texts_handler.get_by_id(production_id)
    if not prod_text:
        raise HTTPException(status_code=404, detail="Production text not found")

    # Update the is_exported flag
    updated = production_texts_handler.mark_exported(production_id, True)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to mark as exported")

    return {"success": True, "is_exported": True}


@router.get("/sources/{identifier}")
async def get_sources_by_identifier(identifier: str):
    """
    Get all training data parts for a given identifier with their content.
    Used when creating a new production text.
    """
    texts = global_new_text_handler.list_texts()

    matching_parts = []
    for text in texts:
        identifiers = text.text_identifiers

        # Check if this text matches the identifier
        matches = (
            (identifiers.museum and identifiers.museum.get_value() == identifier) or
            (identifiers.p_number and identifiers.p_number.get_value() == identifier) or
            (identifiers.publication and identifiers.publication.get_value() == identifier)
        )

        if matches:
            # Get the full text to access transliterations (list_texts returns preview DTOs)
            full_text = global_new_text_handler.get_by_text_id(text.text_id)

            lines = []
            image_name = ""
            if full_text and full_text.transliterations:
                latest_trans = full_text.transliterations[-1]
                if latest_trans.edit_history:
                    lines = latest_trans.edit_history[-1].lines
                image_name = latest_trans.image_name or ""

            matching_parts.append({
                "text_id": text.text_id,
                "part": text.part or "",
                "transliteration_id": text.latest_transliteration_id,
                "lines": lines,
                "image_name": image_name,
                "is_curated": text.is_curated,
                "lines_count": text.lines_count,
                "last_modified": text.last_modified,
                "labels": text.labels if hasattr(text, 'labels') and text.labels else ([text.label] if text.label else []),
                "label": text.label or ""
            })

    # Sort by part
    matching_parts.sort(key=lambda x: x.get("part", ""))

    return matching_parts


# ==========================================
# Image Upload Endpoints
# ==========================================

@router.post("/text/{production_id}/image")
async def upload_production_image(
    production_id: int,
    file: UploadFile = File(...),
    label: str = Form(...)
):
    """Upload an image (copy/photo) to a production text."""
    # Validate file type
    if file.content_type not in ["image/png", "image/jpeg"]:
        raise HTTPException(status_code=400, detail="Only PNG and JPEG images are supported")

    # Read file data
    image_data = await file.read()

    # Add image to production text
    uploaded_image = production_texts_handler.add_uploaded_image(
        production_id=production_id,
        image_data=image_data,
        original_filename=file.filename or "unknown.png",
        label=label
    )

    if not uploaded_image:
        raise HTTPException(status_code=404, detail="Production text not found")

    return uploaded_image


@router.get("/text/{production_id}/image/{image_id}")
async def get_production_image(production_id: int, image_id: str):
    """Get an uploaded image from a production text."""
    image_path = production_texts_handler.get_uploaded_image_path(production_id, image_id)

    if not image_path:
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(image_path, media_type="image/png")


@router.delete("/text/{production_id}/image/{image_id}")
async def delete_production_image(production_id: int, image_id: str):
    """Delete an uploaded image from a production text."""
    result = production_texts_handler.delete_uploaded_image(production_id, image_id)

    if not result:
        raise HTTPException(status_code=404, detail="Image not found")

    return {"deleted": True}
