from typing import List, Optional
from pydantic import BaseModel


class AtfToken(BaseModel):
    """A single word/sign token extracted from an ATF line."""
    index: int  # Position within the line (0-based)
    raw: str  # Original ATF text (e.g., "a-na#")
    cleaned: str  # Normalized form for dictionary lookup (strip flags: #?!*)
    is_determinative: bool = False
    is_number: bool = False
    is_damaged: bool = False  # Has # flag
    is_uncertain: bool = False  # Has ? flag
    is_broken: bool = False  # Inside [...]
    is_logogram: bool = False  # All uppercase (e.g., LUGAL)
    is_complex: bool = False  # Has possessive suffix or other bound morpheme
    detected_suffix: str = ""  # The detected suffix (e.g., "šu", "ka", "ia")
    suffix_lemma: str = ""  # Lemma ID for the suffix (e.g., "šū I")
    match_level: str = "none"  # "exact", "suggestion", "none" — confidence of the match
    lemma_candidates: List[str] = []  # Populated by dictionary lookup (lemma IDs)
    morph_analysis: List[dict] = []  # Verb morphological analysis [{lemma_id, stem, tense, person}]
    detected_enclitic: str = ""  # Enclitic particle (e.g., "ma" for -ma)


class AtfLine(BaseModel):
    """A parsed ATF line."""
    line_number: str  # Original ATF line number (e.g., "1.", "1'.")
    raw_text: str  # Full original line text
    tokens: List[AtfToken] = []
    line_type: str = "text"  # "text", "structure", "state", "comment", "parallel", "empty"
    atf_index: int  # 0-based position in the ATF string (line index)


class TokenizedText(BaseModel):
    """Full tokenized ATF document."""
    lines: List[AtfLine]
    content_hash: str  # Hash of source ATF for change detection


class LemmaAssignment(BaseModel):
    """A lemma assigned to a token — matches eBL format."""
    value: str  # The ATF token value (e.g., "a-na")
    unique_lemma: List[str] = []  # eBL lemma IDs (e.g., ["ana I"]) — empty = unlemmatized
    # Suggestion metadata (populated by ORACC import, not by user assignment)
    is_suggestion: bool = False  # True = not yet accepted by user
    suggestion_source: str = ""  # e.g., "atf_import"
    oracc_guideword: str = ""  # English translation from ORACC (e.g., "command")
    oracc_citation: str = ""  # Akkadian citation form from ORACC (e.g., "amātu")
    oracc_pos: str = ""  # ORACC POS tag (e.g., "N", "V", "PRP")


class LineLemmatization(BaseModel):
    """Lemmatization for one ATF line."""
    line_number: str
    tokens: List[LemmaAssignment]


class TextLemmatization(BaseModel):
    """Complete lemmatization for a production text."""
    production_id: int
    content_hash: str  # Hash of ATF text when lemmatization was created
    lines: List[LineLemmatization]
    last_modified: str = ""
    ai_suggested: bool = False  # Whether AI suggestions have been applied


class WordEntry(BaseModel):
    """A dictionary word entry from eBL."""
    word_id: str  # e.g., "šarru I"
    lemma: List[str]  # e.g., ["šarru"]
    homonym: str = ""  # e.g., "I"
    pos: List[str] = []  # Part of speech, e.g., ["N"]
    guide_word: str = ""  # Short English gloss, e.g., "king"
    roots: List[str] = []
    forms: List[str] = []  # Known variant writings
    origin: str = ""  # Source: CDA, EBL, etc.


class DictionaryStatus(BaseModel):
    """Status of the local dictionary."""
    downloaded: bool = False
    word_count: int = 0
    last_updated: str = ""
    index_size: int = 0  # Number of form entries in the lookup index
    sign_count: int = 0  # Number of sign files on disk
    logogram_count: int = 0  # Number of entries in the logogram index
