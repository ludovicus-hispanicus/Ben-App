from typing import List, Optional, Any, Dict

from pydantic import BaseModel

from entities.dimensions import Dimensions


class CuredResultDto(BaseModel):
    dimensions: List[Dimensions]
    lines: List[str] = None
    # TEI validation results (populated when prompt is tei_lex0)
    validation_results: Optional[List[Dict[str, Any]]] = None
