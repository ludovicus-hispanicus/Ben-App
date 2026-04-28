"""
Lemmatization Handler

Orchestrates ATF tokenization, dictionary lookups, AI suggestions,
lemmatization persistence, and eBL export.
"""

import datetime
import logging
import re
from typing import Dict, Any, List, Optional

from entities.lemmatization import (
    TokenizedText, TextLemmatization, LineLemmatization, LemmaAssignment,
    WordEntry, DictionaryStatus
)
from mongo.local_db_client import LocalDBClient as MongoClient
from services.atf_tokenizer import AtfTokenizer
from services.dictionary_service import DictionaryService

logger = logging.getLogger(__name__)


class LemmatizationHandler:
    """Handler for lemmatization workflows."""

    COLLECTION_NAME = "lemmatizations"

    # Possessive suffix → eBL lemma ID mapping
    # These are the independent pronoun lemma IDs used in eBL for bound suffixes
    SUFFIX_LEMMA_MAP = {
        'šunu': 'šunu I',    # 3mp "their"
        'šina': 'šina I',    # 3fp "their"
        'kunu': 'kunu I',    # 2mp "your (pl)"
        'kina': 'kina I',    # 2fp "your (pl)"
        'šu': 'šū I',        # 3ms "his"
        'ša': 'šī I',        # 3fs "her"
        'ka': 'kâši I',      # 2ms "your"
        'ki': 'kâši I',      # 2fs "your"
        'ni': 'niāti I',     # 1cp "our"
        'ja': 'yâši I',      # 1cs "my"
        'ia': 'yâši I',      # 1cs "my"
        'i': 'yâši I',       # 1cs "my" (bound form)
    }

    def __init__(self):
        self._collection = MongoClient.get_db().lemmatizations
        self._tokenizer = AtfTokenizer()
        self._dictionary = DictionaryService()

    # ── Tokenization ──

    def tokenize(self, atf_text: str) -> TokenizedText:
        """Tokenize ATF text and populate lemma candidates from dictionary."""
        result = self._tokenizer.tokenize(atf_text)

        # Enrich tokens with dictionary candidates
        for line in result.lines:
            if line.line_type != "text":
                continue
            for token in line.tokens:
                if token.is_determinative or token.is_number:
                    continue
                # Skip ATF punctuation (/, //, etc.)
                if token.cleaned.strip('/') == '':
                    token.match_level = "skip"
                    continue

                if token.is_logogram:
                    # Strip brackets/flags from raw but keep digits (sign indices)
                    raw_clean = re.sub(r'[\[\]()<>°\\#?!*]', '', token.raw)
                    # Strip determinatives
                    raw_clean = re.sub(r'\{[^}]+\}', '', raw_clean)

                    # Try logogram index with the full raw form
                    candidates = self._dictionary.lookup_logogram(raw_clean)
                    if not candidates:
                        # Extract uppercase logogram part, stripping phonetic complements
                        logo_part = re.sub(r'[-.]?[a-zšṣṭḫāēīūâêîûĝ][a-zšṣṭḫāēīūâêîûĝ₀₁₂₃₄₅₆₇₈₉ₓ0-9]*', '', raw_clean)
                        logo_part = logo_part.rstrip('-.')
                        if logo_part and logo_part != raw_clean:
                            candidates = self._dictionary.lookup_logogram(logo_part)
                    if candidates:
                        token.match_level = "exact"
                    else:
                        # Fall back to word dictionary
                        candidates, level = self._dictionary.lookup_with_level(token.cleaned)
                        token.match_level = level
                else:
                    candidates, level = self._dictionary.lookup_with_level(token.cleaned)
                    token.match_level = level

                    # If no match, try stripping enclitic -ma
                    if not candidates:
                        stripped, enclitic = self._strip_enclitic(token.cleaned)
                        if enclitic:
                            candidates, level = self._dictionary.lookup_with_level(stripped)
                            if candidates:
                                token.match_level = level
                                token.detected_enclitic = enclitic

                    # If still no match, try stripping ventive -am/-nim
                    if not candidates:
                        stripped, ventive = self._strip_ventive(token.cleaned)
                        if ventive:
                            candidates, level = self._dictionary.lookup_with_level(stripped)
                            if candidates:
                                token.match_level = level
                                token.detected_enclitic = ventive  # reuse enclitic field for display

                token.lemma_candidates = candidates

                # Proper names (PN, DN, TN, etc.) should never be auto-assigned
                if candidates and token.match_level == "exact":
                    if self._dictionary.has_only_proper_names(candidates):
                        token.match_level = "suggestion"

                # Add morphological analysis if available (verb conjugator)
                # Skip for exact function words (ina, ana, šumma, etc.)
                cleaned_for_morph = token.cleaned
                if token.detected_enclitic:
                    cleaned_for_morph, _ = self._strip_enclitic(token.cleaned)
                joined_check = self._dictionary._join_syllables(cleaned_for_morph.lower())
                is_function_word = joined_check in self._dictionary.EXACT_LEMMAS

                if not is_function_word and not token.is_logogram:
                    # Try verb conjugator first
                    verb_morph = self._dictionary.get_morph_analysis(cleaned_for_morph)
                    if verb_morph:
                        token.morph_analysis = verb_morph
                        # If dictionary found candidates AND conjugator also has analyses,
                        # add conjugator lemmas and mark ambiguous (user must decide)
                        if candidates and token.match_level in ("exact", "suggestion"):
                            conj_lemmas = list(dict.fromkeys(
                                m['lemma_id'] for m in verb_morph
                                if m['lemma_id'] not in candidates
                            ))
                            if conj_lemmas:
                                # Re-rank: common words before proper names
                                token.lemma_candidates = self._dictionary._rank_candidates(
                                    candidates + conj_lemmas, cleaned_for_morph)
                                token.match_level = "ambiguous"

                    # Add nominal morphology for candidates that don't have verb morph
                    if candidates:
                        nominal = self._dictionary.get_nominal_morph(cleaned_for_morph, candidates)
                        if nominal:
                            case_labels = {
                                'nom': 'Nominative', 'gen': 'Genitive', 'acc': 'Accusative',
                                'obl': 'Oblique', 'cstr': 'St. constructus',
                            }
                            number_labels = {
                                'sg': 'Sg.', 'fs': 'Sg.f.', 'fp': 'Pl.f.',
                                'mp': 'Pl.m.', 'du': 'Du.',
                            }
                            pos_labels = {
                                'N': 'Subst.', 'AJ': 'Adj.', 'V': 'Verb',
                                'PRP': 'Prep.', 'PN': 'PN', 'DN': 'DN', 'GN': 'GN',
                                'REL': 'Rel.', 'SBJ': 'Subj.', 'PP': 'Pron.',
                                'MOD': 'Mod.', 'CNJ': 'Conj.', 'AV': 'Adv.',
                            }
                            case_str = case_labels.get(nominal.get('case', ''), '')
                            num_str = number_labels.get(nominal.get('number', ''), '')

                            # Add nominal morph for candidates that don't already have verb morph
                            verb_lemma_ids = {m['lemma_id'] for m in (verb_morph or [])}
                            for cid in candidates:
                                if cid not in verb_lemma_ids:
                                    pos = self._dictionary.infer_pos(cid)
                                    pos_label = pos_labels.get(pos, pos)
                                    token.morph_analysis.append({
                                        'lemma_id': cid,
                                        'root': '',
                                        'stem': pos_label,
                                        'tense': f"{num_str} {case_str}".strip(),
                                        'person': '',
                                        'form': cleaned_for_morph,
                                    })

                # Detect possessive suffixes → mark as complex
                # Works for both Akkadian words (ilišu) and logograms (KIRI₄-ša)
                self._detect_possessive_suffix(token)

        return result

    def _strip_enclitic(self, form: str) -> tuple:
        """Strip enclitic -ma from end of a form. Returns (stripped_form, enclitic) or (form, '')."""
        # Join syllables first to check
        joined = self._dictionary._join_syllables(form.lower())
        for enc in self._dictionary.ENCLITICS:
            if joined.endswith(enc) and len(joined) > len(enc) + 1:
                return form.rsplit(enc, 1)[0].rstrip('-'), enc
            # Also check hyphenated form: la-bi-iš-ma → strip -ma syllable
            if form.lower().endswith('-' + enc):
                return form[:-(len(enc) + 1)], enc
            if form.lower().endswith(enc) and len(form) > len(enc) + 1:
                return form[:-len(enc)], enc
        return form, ''

    def _strip_ventive(self, form: str) -> tuple:
        """Strip ventive -am/-nim from end of a verb form.
        Returns (stripped_joined_form, ventive_label) or ('', '').
        Returns the JOINED form (not hyphenated) since that's what lookup needs."""
        joined = self._dictionary._join_syllables(form.lower())
        for vent in self._dictionary.VERBAL_SUFFIXES:
            if joined.endswith(vent) and len(joined) > len(vent) + 2:
                stripped = joined[:-len(vent)]
                return stripped, f"-{vent} (ventive)"
        return '', ''

    def _detect_possessive_suffix(self, token) -> None:
        """Check if a token has a possessive suffix.
        Works for both Akkadian words (ilišu) and logograms (KIRI₄-ša).
        If detected, marks the token as complex with suffix lemma."""
        if not token.lemma_candidates:
            return

        if token.is_logogram:
            # For logograms: check if the raw form ends with a lowercase suffix
            # e.g., KIRI₄-ša → suffix is "ša"
            raw_clean = re.sub(r'[\[\]()<>°\\#?!*]', '', token.raw)
            # Extract trailing lowercase part after the last uppercase/digit section
            match = re.search(r'[-.]([a-zšṣṭḫāēīūâêîû][a-zšṣṭḫāēīūâêîû₀₁₂₃₄₅₆₇₈₉ₓ0-9]*)$', raw_clean)
            if match:
                suffix_text = match.group(1).translate(self._dictionary.VOWEL_NORMALIZE)
                # Check if it's a known possessive suffix
                for suffix, suffix_lemma_id in self.SUFFIX_LEMMA_MAP.items():
                    norm_suffix = suffix.translate(self._dictionary.VOWEL_NORMALIZE)
                    if suffix_text == norm_suffix:
                        token.is_complex = True
                        token.detected_suffix = suffix
                        token.suffix_lemma = suffix_lemma_id
                        return
            return

        # For Akkadian words: join syllables and check for suffix
        joined = self._dictionary._join_syllables(token.cleaned.lower())
        normalized = joined.translate(self._dictionary.VOWEL_NORMALIZE)

        # If the morph analysis already explains the ending as a case ending,
        # don't reinterpret as possessive UNLESS it's a clear multi-char suffix (šu, ša, ka, etc.)
        if token.morph_analysis and not token.is_complex:
            has_case_morph = any(
                any(c in m.get('tense', '') for c in ('Genitive', 'Accusative', 'Nominative', 'Construct'))
                for m in token.morph_analysis
            )
            if has_case_morph:
                # Only proceed if the form ends with a clear possessive suffix (2+ chars)
                has_clear_poss = False
                for suf in self.SUFFIX_LEMMA_MAP:
                    if len(suf) < 2:
                        continue  # Skip single-char i/a — too ambiguous with case endings
                    norm_suf = suf.translate(self._dictionary.VOWEL_NORMALIZE)
                    if normalized.endswith(norm_suf) and len(normalized) > len(norm_suf) + 2:
                        has_clear_poss = True
                        break
                if not has_clear_poss:
                    return

        # Check if the form ends with a known possessive suffix
        for suffix, suffix_lemma_id in self.SUFFIX_LEMMA_MAP.items():
            norm_suffix = suffix.translate(self._dictionary.VOWEL_NORMALIZE)
            if not normalized.endswith(norm_suffix) or len(normalized) <= len(norm_suffix) + 1:
                continue

            stem = normalized[:len(normalized) - len(norm_suffix)]

            # Verify that the base word was found via possessive stripping
            # (i.e., the stem alone or stem+u/um is in the index, not the full form)
            full_match = self._dictionary._index.get(normalized, [])
            if full_match:
                # The full form exists as-is in the dictionary — not a possessive form
                continue

            # Check if stem or stem+nominative is a real word
            found_base = False
            stems_to_check = [stem]
            if stem and stem[-1] in 'iau':
                stems_to_check.append(stem[:-1])

            for s in stems_to_check:
                for ending in ['um', 'u', '']:
                    if self._dictionary._index.get(s + ending, []):
                        found_base = True
                        break
                if found_base:
                    break

            if found_base:
                token.is_complex = True
                token.detected_suffix = suffix
                token.suffix_lemma = suffix_lemma_id
                return

    # ── Dictionary ──

    def get_dictionary_status(self) -> DictionaryStatus:
        """Get dictionary download status."""
        status = self._dictionary.get_status()
        if self._dictionary.is_downloading:
            progress = self._dictionary.download_progress
            # Attach progress info (not in the model, returned separately)
            return status
        return status

    async def download_dictionary(self, api_url: str, access_token: str) -> Dict[str, Any]:
        """Trigger dictionary download from eBL."""
        return await self._dictionary.download_dictionary(api_url, access_token)

    def lookup_word(self, form: str) -> List[WordEntry]:
        """Look up a form in the dictionary, returning full word entries."""
        lemma_ids = self._dictionary.lookup(form)
        entries = []
        for lid in lemma_ids:
            entry = self._dictionary.get_word_entry(lid)
            if entry:
                entries.append(entry)
        return entries

    def get_word_entry(self, word_id: str) -> Optional[WordEntry]:
        """Get a single word entry by ID."""
        return self._dictionary.get_word_entry(word_id)

    def search_words(self, query: str, limit: int = 20) -> List[WordEntry]:
        """Search dictionary words."""
        return self._dictionary.search_words(query, limit)

    # ── Lemmatization CRUD ──

    def get_lemmatization(self, production_id: int) -> Optional[TextLemmatization]:
        """Get saved lemmatization for a production text."""
        data = self._collection.find_one({"production_id": int(production_id)})
        if data:
            return TextLemmatization.parse_obj(data)
        return None

    def save_lemmatization(self, lemmatization: TextLemmatization) -> TextLemmatization:
        """Save or update lemmatization for a production text."""
        lemmatization.last_modified = datetime.datetime.utcnow().isoformat()

        existing = self._collection.find_one({"production_id": lemmatization.production_id})
        data = lemmatization.dict()

        if existing:
            self._collection.update_one(
                {"production_id": lemmatization.production_id},
                {"$set": data}
            )
        else:
            self._collection.insert_one(data)

        logger.info(f"Saved lemmatization for production_id={lemmatization.production_id}, "
                     f"{len(lemmatization.lines)} lines")
        return lemmatization

    def delete_lemmatization(self, production_id: int) -> bool:
        """Delete lemmatization for a production text."""
        result = self._collection.delete_one({"production_id": int(production_id)})
        return result > 0 if isinstance(result, int) else bool(result)

    # ── eBL Export ──

    def format_for_ebl(self, lemmatization: TextLemmatization) -> List[List[Dict[str, Any]]]:
        """
        Convert TextLemmatization to eBL's expected format.
        Each token: {"value": "šum-ma", "uniqueLemma": ["šumma I"]}
        """
        ebl_lines = []
        for line in lemmatization.lines:
            ebl_tokens = []
            for token in line.tokens:
                ebl_tokens.append({
                    "value": token.value,
                    "uniqueLemma": token.unique_lemma if token.unique_lemma else []
                })
            ebl_lines.append(ebl_tokens)
        return ebl_lines

    async def export_to_ebl(self, production_id: int, fragment_number: str,
                             ebl_handler) -> Dict[str, Any]:
        """Export lemmatization to eBL via POST /fragments/{number}/lemmatization."""
        lemmatization = self.get_lemmatization(production_id)
        if not lemmatization:
            return {"success": False, "error": "No lemmatization found for this text"}

        # Strip part suffix for eBL API (e.g., "MS.2225-0" -> "MS.2225")
        clean_fragment = fragment_number
        if '-' in fragment_number:
            parts = fragment_number.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                clean_fragment = parts[0]

        try:
            # Fetch the fragment to get the exact line structure
            fragment = await ebl_handler._make_request("GET", f"/fragments/{clean_fragment}")
            frag_lines = fragment.get('text', {}).get('lines', [])

            # Build lemmatization matching the fragment's exact structure.
            # Each line must have the same number of tokens as the fragment.
            # We match our lemma assignments by token value.
            our_lemma_data = self.format_for_ebl(lemmatization)
            our_line_idx = 0

            ebl_lemmatization = []
            for frag_line in frag_lines:
                if frag_line.get('type') == 'TextLine':
                    frag_tokens = frag_line.get('content', [])
                    our_tokens = our_lemma_data[our_line_idx] if our_line_idx < len(our_lemma_data) else []
                    our_line_idx += 1

                    # Build token map from our data: value -> uniqueLemma
                    our_map = {}
                    for t in our_tokens:
                        our_map[t['value']] = t.get('uniqueLemma', [])

                    # Match each fragment token
                    # Word tokens get uniqueLemma, non-Word tokens (Dividers) get value only
                    WORD_TYPES = {'Word', 'AkkadianWord', 'LoneDeterminative'}
                    line_tokens = []
                    for ft in frag_tokens:
                        fval = ft.get('value', '')
                        ft_type = ft.get('type', '')
                        is_lemmatizable = ft.get('lemmatizable', False)

                        if ft_type in WORD_TYPES:
                            if is_lemmatizable and fval in our_map and our_map[fval]:
                                line_tokens.append({
                                    "value": fval,
                                    "uniqueLemma": our_map[fval]
                                })
                            else:
                                line_tokens.append({
                                    "value": fval,
                                    "uniqueLemma": []
                                })
                        else:
                            # Dividers and other non-Word types: value only, no uniqueLemma
                            line_tokens.append({"value": fval})
                    ebl_lemmatization.append(line_tokens)
                else:
                    ebl_lemmatization.append([])

            logger.info(f"eBL lemmatization: {len(ebl_lemmatization)} lines ({our_line_idx} text lines matched)")

            # Log first few lines of payload for debugging
            import json as _json
            for i, line in enumerate(ebl_lemmatization[:5]):
                if line:
                    logger.info(f"  payload line {i}: {_json.dumps(line, ensure_ascii=False)[:200]}")

            endpoint = f"/fragments/{clean_fragment}/lemmatization"
            result = await ebl_handler._make_request(
                "POST", endpoint,
                data={"lemmatization": ebl_lemmatization}
            )
            logger.info(f"Lemmatization exported to eBL for fragment {clean_fragment}")
            return {
                "success": True,
                "message": f"Lemmatization exported to eBL for {clean_fragment}",
                "fragment_url": f"https://www.ebl.lmu.de/fragmentarium/{clean_fragment}"
            }
        except Exception as e:
            logger.error(f"eBL lemmatization export failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
lemmatization_handler = LemmatizationHandler()
