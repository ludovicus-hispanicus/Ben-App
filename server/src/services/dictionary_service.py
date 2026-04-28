"""
eBL Dictionary Service

Downloads and indexes the eBL dictionary for local lemma lookups.
The dictionary is stored as local JSON files and loaded into memory
for fast token-to-lemma matching.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import httpx

from entities.lemmatization import WordEntry, DictionaryStatus

logger = logging.getLogger(__name__)

# Subscript digits for normalization
SUBSCRIPT_MAP = str.maketrans('₀₁₂₃₄₅₆₇₈₉ₓ', '0123456789x')


class DictionaryService:
    """Manages the local eBL dictionary for lemma lookups."""

    def __init__(self):
        self.data_dir = Path(os.environ.get("STORAGE_PATH", "data")) / "dictionary"
        self.words_dir = self.data_dir / "words"
        self.signs_dir = self.data_dir / "signs"
        self.index_path = self.data_dir / "words_index.json"
        self.english_index_path = self.data_dir / "english_index.json"
        self.logogram_index_path = self.data_dir / "logogram_index.json"
        self.meta_path = self.data_dir / "dictionary_meta.json"

        # In-memory index: cleaned_form -> [lemma_id, ...]
        self._index: Dict[str, List[str]] = {}
        # English guide word index: english_word -> [lemma_id, ...]
        self._english_index: Dict[str, List[str]] = {}
        # Logogram index: normalized_logogram -> [lemma_id, ...]
        self._logogram_index: Dict[str, List[str]] = {}
        # User-defined custom mappings: form -> lemma_id (for unmatched words)
        self._custom_index: Dict[str, List[str]] = {}
        self._custom_index_path = self.data_dir / "custom_index.json"
        self._loaded = False

        # Download progress tracking
        self._downloading = False
        self._download_progress = 0
        self._download_total = 0

        # Verb conjugator for form recognition
        self._conjugator = None

        self._ensure_dirs()
        self._load_index()
        self._load_english_index()
        self._load_logogram_index()
        self._load_custom_index()
        self._build_conjugator()

    def _ensure_dirs(self):
        """Create dictionary directories if needed."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.words_dir.mkdir(parents=True, exist_ok=True)
        self.signs_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self):
        """Load the lookup index from disk into memory."""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
                self._loaded = True
                logger.info(f"Dictionary index loaded: {len(self._index)} form entries")
            except Exception as e:
                logger.error(f"Failed to load dictionary index: {e}")
                self._index = {}

    def _load_english_index(self):
        """Load the English guide word index from disk."""
        if self.english_index_path.exists():
            try:
                with open(self.english_index_path, 'r', encoding='utf-8') as f:
                    self._english_index = json.load(f)
                logger.info(f"English index loaded: {len(self._english_index)} entries")
            except Exception as e:
                logger.error(f"Failed to load English index: {e}")
                self._english_index = {}

    def _load_logogram_index(self):
        """Load the logogram index from disk into memory."""
        if self.logogram_index_path.exists():
            try:
                with open(self.logogram_index_path, 'r', encoding='utf-8') as f:
                    self._logogram_index = json.load(f)
                logger.info(f"Logogram index loaded: {len(self._logogram_index)} entries")
            except Exception as e:
                logger.error(f"Failed to load logogram index: {e}")
                self._logogram_index = {}

    def _load_custom_index(self):
        """Load user-defined custom form→lemma mappings."""
        if self._custom_index_path.exists():
            try:
                with open(self._custom_index_path, 'r', encoding='utf-8') as f:
                    self._custom_index = json.load(f)
                logger.info(f"Custom index loaded: {len(self._custom_index)} entries")
            except Exception as e:
                logger.error(f"Failed to load custom index: {e}")
                self._custom_index = {}

    def add_custom_mapping(self, form: str, lemma_id: str) -> None:
        """Store a user-defined form→lemma mapping for future lookups."""
        normalized = self._join_syllables(form.lower()).translate(self.VOWEL_NORMALIZE)
        if normalized not in self._custom_index:
            self._custom_index[normalized] = []
        if lemma_id not in self._custom_index[normalized]:
            self._custom_index[normalized].append(lemma_id)
            self._save_custom_index()
            logger.info(f"Custom mapping added: '{form}' ({normalized}) → {lemma_id}")

    def _save_custom_index(self):
        """Persist custom index to disk."""
        try:
            with open(self._custom_index_path, 'w', encoding='utf-8') as f:
                json.dump(self._custom_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save custom index: {e}")

    def _build_conjugator(self):
        """Build the verb conjugator reverse index from downloaded verb entries."""
        try:
            from services.akkadian_conjugator import AkkadianConjugator
            import glob

            word_files = list(self.words_dir.glob('*.json'))
            if not word_files:
                return

            verb_entries = []
            for fpath in word_files:
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    if 'V' in entry.get('pos', []):
                        verb_entries.append(entry)
                except Exception:
                    continue

            if not verb_entries:
                return

            self._conjugator = AkkadianConjugator()
            count = self._conjugator.build_reverse_index(verb_entries)
            logger.info(f"Conjugator: {len(verb_entries)} verbs, {self._conjugator.index_size} unique forms")
        except Exception as e:
            logger.warning(f"Failed to build conjugator: {e}")
            self._conjugator = None

    def lookup_logogram(self, logogram: str) -> List[str]:
        """Look up a logogram (e.g., LUGAL, E₂.GAL) and return Akkadian lemma IDs."""
        if not self._logogram_index:
            return []

        # Normalize: dots and hyphens are interchangeable, strip subscripts, uppercase
        normalized = self._normalize_logogram(logogram)

        candidates = self._logogram_index.get(normalized, [])
        if candidates:
            return candidates

        # Try with dots replaced by hyphens and vice versa
        alt = normalized.replace('.', '-')
        candidates = self._logogram_index.get(alt, [])
        if candidates:
            return candidates

        alt = normalized.replace('-', '.')
        candidates = self._logogram_index.get(alt, [])
        if candidates:
            return candidates

        return []

    @staticmethod
    def _normalize_logogram(logogram: str) -> str:
        """Normalize a logogram for index lookup."""
        # Translate subscript digits to regular digits
        normalized = logogram.translate(SUBSCRIPT_MAP)
        # Lowercase for consistent matching
        normalized = normalized.lower().strip()
        # Normalize separators: treat . and - the same
        normalized = normalized.replace('.', '-')
        return normalized

    async def download_signs(self) -> Dict[str, Any]:
        """Download the eBL signs database (no auth required)."""
        logger.info("Downloading signs from eBL...")
        api_url = "https://www.ebl.lmu.de/api"

        try:
            # Step 1: Get all sign names
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(f"{api_url}/signs/all")
                if response.status_code != 200:
                    raise ValueError(f"Failed to fetch sign list: {response.status_code}")
                sign_names = response.json()

            logger.info(f"Found {len(sign_names)} signs to download")
            logogram_index: Dict[str, List[str]] = {}
            sign_count = 0

            # Step 2: Download each sign
            batch_size = 10
            for i in range(0, len(sign_names), batch_size):
                batch = sign_names[i:i + batch_size]
                tasks = [self._download_sign(api_url, name) for name in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for name, result in zip(batch, results):
                    if isinstance(result, Exception) or result is None:
                        continue

                    # Save sign to disk
                    safe_name = self._safe_filename(name)
                    path = self.signs_dir / f"{safe_name}.json"
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=1)

                    # Index logograms from this sign
                    self._index_sign_logograms(logogram_index, result)
                    sign_count += 1

                if i + batch_size < len(sign_names):
                    await asyncio.sleep(0.1)

                if (i // batch_size) % 50 == 0:
                    logger.info(f"Signs download progress: {min(i + batch_size, len(sign_names))}/{len(sign_names)}")

            # Step 3: Save logogram index
            with open(self.logogram_index_path, 'w', encoding='utf-8') as f:
                json.dump(logogram_index, f, ensure_ascii=False)

            self._logogram_index = logogram_index

            logger.info(f"Signs download complete: {sign_count} signs, {len(logogram_index)} logogram entries")
            return {"status": "complete", "sign_count": sign_count, "logogram_entries": len(logogram_index)}

        except Exception as e:
            logger.error(f"Signs download failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _download_sign(self, api_url: str, sign_name: str) -> Optional[Dict]:
        """Download a single sign entry (no auth needed)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # URL-encode the sign name
                url = f"{api_url}/signs/{sign_name}"
                response = await client.get(url)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    await asyncio.sleep(2)
                    response = await client.get(url)
                    if response.status_code == 200:
                        return response.json()
                return None
        except Exception as e:
            logger.warning(f"Error downloading sign '{sign_name}': {e}")
            return None

    def _index_sign_logograms(self, index: Dict[str, List[str]], sign_data: Dict):
        """Extract logograms from a sign entry and add to the index."""
        logograms = sign_data.get("logograms", [])
        for logo in logograms:
            if not isinstance(logo, dict):
                continue

            atf = logo.get("atf", "")
            word_ids = logo.get("wordId", [])

            if not atf or not word_ids:
                continue

            if not isinstance(word_ids, list):
                word_ids = [word_ids]

            # Normalize the ATF logogram form
            normalized = self._normalize_logogram(atf)

            # Also index without determinative prefixes
            # e.g., {munus}LUGAL -> index both "munus-lugal" and "lugal"
            stripped = re.sub(r'\{[^}]+\}', '', atf).strip()
            normalized_stripped = self._normalize_logogram(stripped)

            for wid in word_ids:
                if not isinstance(wid, str) or not wid:
                    continue
                # Index the full form
                index.setdefault(normalized, [])
                if wid not in index[normalized]:
                    index[normalized].append(wid)
                # Index without determinative
                if normalized_stripped and normalized_stripped != normalized:
                    index.setdefault(normalized_stripped, [])
                    if wid not in index[normalized_stripped]:
                        index[normalized_stripped].append(wid)

    def rebuild_logogram_index(self) -> Dict[str, Any]:
        """Rebuild the logogram index from existing sign files on disk."""
        logger.info("Rebuilding logogram index from local sign files...")
        index: Dict[str, List[str]] = {}
        sign_count = 0

        for path in self.signs_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._index_sign_logograms(index, data)
                sign_count += 1
            except Exception as e:
                logger.warning(f"Failed to index sign {path.name}: {e}")

        with open(self.logogram_index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False)

        self._logogram_index = index
        logger.info(f"Logogram index rebuilt: {sign_count} signs, {len(index)} entries")
        return {"status": "complete", "sign_count": sign_count, "logogram_entries": len(index)}

    def rebuild_index(self) -> Dict[str, Any]:
        """Rebuild the lookup index from existing word files on disk (no download needed)."""
        logger.info("Rebuilding dictionary index from local word files...")
        index: Dict[str, List[str]] = {}
        english_index: Dict[str, List[str]] = {}
        word_count = 0

        for path in self.words_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                word_id = data.get("_id", path.stem)
                self._index_word(index, word_id, data)
                self._index_english(english_index, word_id, data)
                word_count += 1
            except Exception as e:
                logger.warning(f"Failed to index {path.name}: {e}")

        # Save Akkadian index
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False)

        # Save English index
        with open(self.english_index_path, 'w', encoding='utf-8') as f:
            json.dump(english_index, f, ensure_ascii=False)

        self._index = index
        self._english_index = english_index
        self._loaded = True

        # Update metadata
        self._save_meta({
            "last_updated": datetime.utcnow().isoformat(),
            "word_count": word_count,
            "index_size": len(index),
            "english_index_size": len(english_index)
        })

        logger.info(f"Index rebuilt: {word_count} words, {len(index)} Akkadian entries, {len(english_index)} English entries")
        return {"status": "complete", "word_count": word_count, "index_size": len(index)}

    def get_morph_analysis(self, form: str) -> List[dict]:
        """Get morphological analysis for a verb form from the conjugator."""
        if not self._conjugator or not self._conjugator.is_built:
            return []
        # Normalize: join syllables, strip long vowels
        joined = self._join_syllables(form.lower())
        normalized = joined.translate(self.VOWEL_NORMALIZE)
        analyses = self._conjugator.lookup(normalized)
        if not analyses:
            no_hyphens = form.lower().replace('-', '').translate(self.VOWEL_NORMALIZE)
            if no_hyphens != normalized:
                analyses = self._conjugator.lookup(no_hyphens)
        # Try gemination variants (e.g., itanagrar → ittanagrar)
        if not analyses:
            vowels = set('aeiuāēīū')
            for i in range(1, len(normalized)):
                if normalized[i] not in vowels and (i == 0 or normalized[i-1] in vowels):
                    doubled = normalized[:i] + normalized[i] + normalized[i:]
                    analyses = self._conjugator.lookup(doubled)
                    if analyses:
                        break
        return [
            {
                "lemma_id": a.lemma_id,
                "root": a.root,
                "stem": a.stem,
                "tense": a.tense,
                "person": a.person,
                "form": a.form,
            }
            for a in analyses
        ]

    def get_nominal_morph(self, cleaned_form: str, candidates: List[str] = None) -> Optional[dict]:
        """Analyze nominal morphology: infer case, number, state from the form.
        Returns dict with 'ending', 'case', 'number', etc. or None."""
        joined = self._join_syllables(cleaned_form.lower())
        normalized = joined.translate(self.VOWEL_NORMALIZE)

        # Check case endings
        for ending in self.CASE_ENDINGS:
            ne = ending.translate(self.VOWEL_NORMALIZE)
            if normalized.endswith(ne) and len(normalized) > len(ne) + 1:
                grammar = self.ENDING_GRAMMAR.get(ending)
                if grammar:
                    return {
                        'ending': ending,
                        **grammar,
                    }

        # Check construct state (VC swap: lumun → lumnu)
        if len(normalized) >= 3 and candidates:
            vowels = set('aeiuāēīū')
            last2 = normalized[-2:]
            if last2[0] in vowels and last2[1] not in vowels:
                swapped = normalized[:-2] + last2[1] + last2[0]
                for de in ['', 'um', 'u']:
                    if self._index.get(swapped + de, []):
                        return {
                            'ending': '',
                            'case': 'cstr',
                            'number': 'sg',
                            'state': 'construct',
                        }

        return None

    def infer_pos(self, word_id: str) -> str:
        """Infer POS from lemma form and eBL entry data."""
        entry = self._load_word_entry_raw(word_id)
        if not entry:
            return ''

        pos = entry.get('pos', [])
        if pos:
            return pos[0]

        lemma = entry.get('lemma', [''])[0] if entry.get('lemma') else ''
        gw = entry.get('guideWord', '').lower()
        meaning = entry.get('meaning', '').lower()
        amp = entry.get('amplifiedMeanings', [])

        # Proper names (capitalized lemma)
        if lemma and lemma[0].isupper():
            if any(w in gw for w in ('god', 'deity', 'divine')):
                return 'DN'
            if any(w in gw for w in ('city', 'town', 'country', 'land', 'river', 'mountain')):
                return 'GN'
            return 'PN'

        # Verb: has G/D/Š/N stem entries, or lemma is CaCāCu pattern
        if any(a.get('key') in ('G', 'D', 'Š', 'N', 'Gt', 'Dt', 'Št') for a in amp):
            return 'V'

        # Prepositions, conjunctions — match whole guide word only (short function words)
        prep_words = {'in', 'to', 'from', 'with', 'upon', 'before', 'after', 'until',
                      'on', 'at', 'for', 'by', 'against', 'over', 'under', 'between'}
        if gw in prep_words and len(lemma) <= 6:
            return 'PRP'

        # Adjective: meaning starts with adjective patterns, or
        # lemma form matches typical adj patterns (CaCCu, CaCiCu)
        adj_indicators = {'good', 'bad', 'big', 'small', 'strong', 'weak',
                          'old', 'new', 'great', 'holy', 'pure', 'evil', 'true', 'false',
                          'thick', 'thin', 'wide', 'narrow', 'long', 'short',
                          'heavy', 'light', 'sweet', 'bitter', 'black', 'white', 'red',
                          'full', 'empty', 'torn', 'broken', 'whole', 'complete',
                          'firm', 'straight', 'crooked', 'clean', 'dirty',
                          'very bad', 'beautiful', 'ugly', 'high', 'low', 'deep'}
        if gw in adj_indicators:
            return 'AJ'
        # Verbal adjective / participle entries (often end in pattern like CaCiC)
        if meaning and ('"(a ' in meaning or '"(an ' in meaning):
            return 'AJ'

        # Default: noun (substantive)
        return 'N'

    def _load_word_entry_raw(self, word_id: str) -> Optional[dict]:
        """Load raw JSON word entry by ID."""
        safe_name = word_id.replace(' ', '_').replace('/', '_')
        path = self.words_dir / f"{safe_name}.json"
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def resolve_oracc_lemma(self, lemma: str, guideword: str, pos: str) -> Optional[str]:
        """Resolve an ORACC lemma citation form to an eBL lemma ID.

        Uses English guideword as the PRIMARY lookup key (avoids mismatch
        with conjugated Akkadian verb forms that don't match eBL citation
        forms). Falls back to Akkadian citation form if English fails.

        Args:
            lemma: ORACC citation form (e.g., "ina", "amātu", "Nergal")
            guideword: ORACC guide word (e.g., "by", "command", "1")
            pos: ORACC POS tag (e.g., "PRP", "N", "DN")

        Returns:
            eBL lemma ID (e.g., "ina I", "awātu I") or None if not resolved.
        """
        if not self._loaded or not lemma:
            return None

        candidates = []

        # 1. Try English guideword FIRST — avoids conjugation mismatches
        if guideword and guideword not in ('1', '2', '3'):
            gw_lower = guideword.lower().strip('() ')
            # Exact match
            eng_candidates = self._english_index.get(gw_lower, [])
            if not eng_candidates:
                # Try each word in multi-word guidewords (e.g., "be destroyed" → try "destroyed")
                for word in gw_lower.split():
                    eng_candidates = self._english_index.get(word, [])
                    if eng_candidates:
                        break
            if not eng_candidates:
                # Partial match: find index keys that start with the guideword or vice versa
                for eng_key, lemma_ids in self._english_index.items():
                    if eng_key.startswith(gw_lower) or gw_lower.startswith(eng_key):
                        eng_candidates = lemma_ids
                        break
            if eng_candidates:
                candidates = eng_candidates

        # 2. Fallback: Akkadian citation form lookup
        if not candidates:
            normalized = self._normalize_form(lemma)
            if normalized:
                candidates = self._index.get(normalized, [])

        # 2b. If citation looks like a logogram (uppercase, possibly with subscripts),
        #     try logogram index — preserves subscript semantics (ŠA₃≠ŠA)
        if not candidates:
            stripped = re.sub(r'[(){}\[\]]', '', lemma).strip()
            alpha_part = re.sub(r'[₀-₉ₓ0-9.\-]', '', stripped)
            if alpha_part and alpha_part == alpha_part.upper() and alpha_part.isalpha():
                candidates = self.lookup_logogram(stripped)

        # 3. If English found candidates AND Akkadian/logogram also has some, prefer intersection
        if candidates and guideword and guideword not in ('1', '2', '3'):
            normalized = self._normalize_form(lemma)
            if normalized:
                akk_candidates = self._index.get(normalized, [])
                if akk_candidates:
                    both = [c for c in candidates if c in set(akk_candidates)]
                    if both:
                        candidates = both

        if not candidates:
            return None

        # Single candidate — use it directly
        if len(candidates) == 1:
            return candidates[0]

        # Multiple candidates — disambiguate using guide word and POS
        best = None
        best_score = -1
        for cid in candidates:
            score = 0
            entry_data = self._load_word_entry_raw(cid)
            if not entry_data:
                continue

            # Match guide word
            ebl_gw = (entry_data.get("guideWord", "") or "").lower().strip('() ')
            if guideword and ebl_gw:
                gw_lower = guideword.lower().strip('() ')
                if gw_lower == ebl_gw:
                    score += 10
                elif gw_lower in ebl_gw or ebl_gw in gw_lower:
                    score += 5

            # Match POS
            ebl_pos = entry_data.get("pos", [])
            if pos and ebl_pos:
                oracc_to_ebl_pos = {
                    'N': 'N', 'V': 'V', 'AJ': 'AJ', 'AV': 'AV',
                    'PRP': 'PRP', 'CNJ': 'CNJ', 'MOD': 'MOD',
                    'PN': 'PN', 'DN': 'DN', 'GN': 'GN', 'TN': 'TN',
                    'SBJ': 'SBJ', 'REL': 'REL', 'PP': 'PP',
                    'QP': 'QP', 'DP': 'DP', 'IP': 'IP', 'XP': 'XP',
                }
                mapped_pos = oracc_to_ebl_pos.get(pos, pos)
                if mapped_pos in ebl_pos:
                    score += 3

            if score > best_score:
                best_score = score
                best = cid

        return best

    def get_status(self) -> DictionaryStatus:
        """Get dictionary download status."""
        meta = self._load_meta()
        sign_count = sum(1 for _ in self.signs_dir.glob("*.json")) if self.signs_dir.exists() else 0
        return DictionaryStatus(
            downloaded=bool(meta.get("word_count", 0) > 0),
            word_count=meta.get("word_count", 0),
            last_updated=meta.get("last_updated", ""),
            index_size=len(self._index),
            sign_count=sign_count,
            logogram_count=len(self._logogram_index),
        )

    def _load_meta(self) -> Dict[str, Any]:
        """Load dictionary metadata."""
        if self.meta_path.exists():
            try:
                with open(self.meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_meta(self, meta: Dict[str, Any]):
        """Save dictionary metadata."""
        with open(self.meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)

    # Akkadian long vowel → short vowel mapping
    VOWEL_NORMALIZE = str.maketrans('āēīūâêîû', 'aeiuaeiu')

    # Unambiguous function words: when these appear as standalone tokens,
    # return only the specified lemma (no other candidates).
    # Key is the joined/normalized form, value is the lemma ID list.
    EXACT_LEMMAS = {
        'ina': ['ina I'],           # in, on, by
        'ana': ['ana I'],           # to, for
        'ša': ['ša I'],             # of, which, that (relative)
        'u': ['u I'],               # and
        'ul': ['ul I'],             # not
        'la': ['lā I'],             # not (prohibitive)
        'ma': ['ma I'],             # and (enclitic)
        'šu': ['šū I'],             # he (independent pronoun)
        'ši': ['šī I'],             # she
        'ki': ['kī I'],             # like, when
        'šum-ma': ['šumma I'],      # if
        'šumma': ['šumma I'],
        'kima': ['kīma I'],         # like, as
        'ki-ma': ['kīma I'],
        'aššum': ['aššum I'],       # because, concerning
        'adi': ['adi I'],           # until, as far as
        'eli': ['eli I'],           # upon, over, against
        'itti': ['itti I'],         # with
        'ištu': ['ištu I'],         # from, since
        'ultu': ['ultu I'],         # from (NB)
        'balu': ['balu I'],         # without
        'ašar': ['ašar I'],         # where
    }

    # Akkadian case/mimation endings to strip, longest first
    CASE_ENDINGS = [
        'ātim', 'ātum', 'ātam',  # feminine plural oblique/nom/acc
        'ūtim', 'ūtum', 'ūtam',  # abstract plural
        'ānī', 'ēnī',            # dual oblique
        'ātī', 'āti',            # feminine plural construct/bound
        'ātu', 'āta',            # feminine plural
        'tim', 'tum', 'tam',     # feminine singular with mimation
        'šum', 'šim', 'šam',     # -š + mimation (possessive)
        'ūm', 'īm', 'ām',       # plural oblique with mimation
        'im', 'um', 'am',        # singular oblique/nom/acc with mimation
        'āt',                     # feminine plural construct
        'tī', 'ti', 'tu', 'ta',  # feminine endings
        'ūt',                     # abstract construct
        'ī', 'ū', 'ā',          # long vowel endings (plural/genitive)
        'i', 'u', 'a',           # short vowel endings (case vowels)
    ]

    # Grammatical info for each ending (for morph analysis)
    ENDING_GRAMMAR = {
        # Feminine plural
        'ātim': {'case': 'gen', 'number': 'fp', 'mimation': True},
        'ātum': {'case': 'nom', 'number': 'fp', 'mimation': True},
        'ātam': {'case': 'acc', 'number': 'fp', 'mimation': True},
        'ūtim': {'case': 'gen', 'number': 'fp', 'mimation': True},
        'ūtum': {'case': 'nom', 'number': 'fp', 'mimation': True},
        'ūtam': {'case': 'acc', 'number': 'fp', 'mimation': True},
        # Dual
        'ānī': {'case': 'obl', 'number': 'du'},
        'ēnī': {'case': 'obl', 'number': 'du'},
        # Feminine plural construct
        'ātī': {'case': 'gen', 'number': 'fp', 'state': 'bound'},
        'āti': {'case': 'gen', 'number': 'fp', 'state': 'bound'},
        'ātu': {'case': 'nom', 'number': 'fp'},
        'āta': {'case': 'acc', 'number': 'fp'},
        'āt': {'case': 'cstr', 'number': 'fp', 'state': 'construct'},
        # Feminine singular
        'tim': {'case': 'gen', 'number': 'fs', 'mimation': True},
        'tum': {'case': 'nom', 'number': 'fs', 'mimation': True},
        'tam': {'case': 'acc', 'number': 'fs', 'mimation': True},
        'tī': {'case': 'gen', 'number': 'fs'},
        'ti': {'case': 'gen', 'number': 'fs'},
        'tu': {'case': 'nom', 'number': 'fs'},
        'ta': {'case': 'acc', 'number': 'fs'},
        # Singular with mimation
        'im': {'case': 'gen', 'number': 'sg', 'mimation': True},
        'um': {'case': 'nom', 'number': 'sg', 'mimation': True},
        'am': {'case': 'acc', 'number': 'sg', 'mimation': True},
        # Plural long vowels
        'ī': {'case': 'gen', 'number': 'mp'},
        'ū': {'case': 'nom', 'number': 'mp'},
        'ā': {'case': 'obl', 'number': 'mp'},
        # Singular short vowels
        'i': {'case': 'gen', 'number': 'sg'},
        'u': {'case': 'nom', 'number': 'sg'},
        'a': {'case': 'acc', 'number': 'sg'},
        # Abstract/construct
        'ūt': {'case': 'cstr', 'number': 'sg', 'state': 'construct'},
    }

    # Akkadian possessive (pronominal) suffixes, longest first
    # These attach after the case vowel: ilī-šu (his god), bēl-ka (your lord)
    POSSESSIVE_SUFFIXES = [
        'šunu', 'šina',          # 3mp, 3fp "their"
        'kunu', 'kina',          # 2mp, 2fp "your (pl)"
        'šu', 'ša',              # 3ms, 3fs "his/her"
        'ka', 'ki',              # 2ms, 2fs "your"
        'ni',                     # 1cp "our"
        'ja', 'ia',              # 1cs "my"
        'i',                      # 1cs "my" (after consonant: bēl-ī)
    ]

    # Akkadian enclitics that can be appended to any word
    ENCLITICS = ['ma']  # -ma conjunction ("and", "but")

    # Verbal suffixes to strip before lookup
    VERBAL_SUFFIXES = ['am', 'nim']  # -am ventive (singular), -nim ventive (plural)

    def lookup(self, cleaned_form: str) -> List[str]:
        """Look up candidate lemma IDs for a cleaned token form."""
        candidates, _ = self.lookup_with_level(cleaned_form)
        return candidates

    def lookup_with_level(self, cleaned_form: str) -> tuple:
        """Look up candidates and return (candidates, match_level).
        match_level: "exact" = vowel-faithful match, "suggestion" = found via ending/suffix stripping."""
        if not self._loaded:
            return [], "none"

        # Check custom user-defined mappings first
        if self._custom_index:
            custom_norm = self._join_syllables(cleaned_form.lower()).translate(self.VOWEL_NORMALIZE)
            custom = self._custom_index.get(custom_norm, [])
            if custom:
                return custom, "exact"

        # Check unambiguous function words first
        joined_lower = self._join_syllables(cleaned_form.lower())
        exact = self.EXACT_LEMMAS.get(joined_lower)
        if exact:
            return exact, "exact"

        # Try exact match first
        candidates = self._index.get(cleaned_form, [])
        if candidates:
            return self._rank_candidates(candidates, cleaned_form), "exact"

        # Try lowercase
        lower = cleaned_form.lower()
        candidates = self._index.get(lower, [])
        if candidates:
            return self._rank_candidates(candidates, lower), "exact"

        # Try without hyphens (e.g., "a-na" -> "ana")
        no_hyphens = lower.replace('-', '')
        candidates = self._index.get(no_hyphens, [])
        if candidates:
            return self._rank_candidates(candidates, no_hyphens), "exact"

        # ── Akkadian syllabic joining ──
        joined = self._join_syllables(lower)
        if joined != no_hyphens:
            candidates = self._index.get(joined, [])
            if candidates:
                return self._rank_candidates(candidates, joined), "exact"

        # ── Akkadian-aware normalization (long↔short vowels only) ──
        normalized = joined.translate(self.VOWEL_NORMALIZE)
        candidates = self._index.get(normalized, [])
        if candidates:
            return self._rank_candidates(candidates, normalized), "exact"

        normalized_simple = no_hyphens.translate(self.VOWEL_NORMALIZE)
        if normalized_simple != normalized:
            candidates = self._index.get(normalized_simple, [])
            if candidates:
                return self._rank_candidates(candidates, normalized_simple), "exact"

        # ── Ending/suffix stripping ──
        # "exact" if the nominative reconstruction matches (stem+um/u in index)
        # "suggestion" if only a raw stem or other form matches (vowel pattern may differ)

        # Check possessive suffix first if present
        has_possessive = any(
            normalized.endswith(s.translate(self.VOWEL_NORMALIZE))
            for s in self.POSSESSIVE_SUFFIXES
            if len(normalized) > len(s) + 1
        )

        if has_possessive:
            candidates, strip_level = self._lookup_strip_possessive_with_level(normalized)
            if candidates:
                return self._rank_candidates(candidates, normalized), strip_level

        # Strip case endings
        candidates, strip_level = self._lookup_strip_endings_with_level(normalized)
        if candidates:
            return self._rank_candidates(candidates, normalized), strip_level

        if normalized_simple != normalized:
            candidates, strip_level = self._lookup_strip_endings_with_level(normalized_simple)
            if candidates:
                return self._rank_candidates(candidates, normalized_simple), strip_level

        # Possessive on non-joined form
        if not has_possessive:
            candidates, strip_level = self._lookup_strip_possessive_with_level(normalized)
            if candidates:
                return self._rank_candidates(candidates, normalized), strip_level

        if normalized_simple != normalized:
            candidates, strip_level = self._lookup_strip_possessive_with_level(normalized_simple)
            if candidates:
                return self._rank_candidates(candidates, normalized_simple), strip_level

        # Try construct state reconstruction: lumun → lumnu (swap last VC → CV)
        # Akkadian construct forms insert epenthetic vowel: C1uC2C3 → C1uC2uC3
        if len(normalized) >= 3:
            vowels = set('aeiuāēīū')
            last2 = normalized[-2:]
            # If form ends in vowel+consonant (e.g., 'un'), try consonant+vowel (e.g., 'nu')
            if last2[0] in vowels and last2[1] not in vowels:
                swapped = normalized[:-2] + last2[1] + last2[0]
                for de in ['', 'um', 'u']:
                    candidates = self._index.get(swapped + de, [])
                    if candidates:
                        return self._rank_candidates(candidates, swapped), "exact"

        # Last resort: try full normalized form + dictionary endings (e.g., damam + u = damamu → verb)
        for dict_ending in ['u', 'um']:
            candidates = self._index.get(normalized + dict_ending, [])
            if candidates:
                level = "exact" if self._check_vowel_match(normalized, candidates) else "suggestion"
                return self._rank_candidates(candidates, normalized), level

        # ── Gemination: try doubling each consonant (scribal variation) ──
        # e.g., ibissum → ibissûm (double s not written)
        geminated = self._try_gemination_lookup(normalized)
        if geminated:
            return geminated, "suggestion"

        # ── Conjugator lookup (verb forms) ──
        if self._conjugator and self._conjugator.is_built:
            analyses = self._conjugator.lookup(normalized)
            if not analyses and normalized != normalized_simple:
                analyses = self._conjugator.lookup(normalized_simple)
            # Try gemination variants: scribal single→double consonant
            # e.g., itanagrar → ittanagrar (N-stem n-assimilation not written)
            if not analyses:
                analyses = self._try_conjugator_gemination(normalized)
            if analyses:
                seen = set()
                conj_candidates = []
                for a in analyses:
                    if a.lemma_id not in seen:
                        seen.add(a.lemma_id)
                        conj_candidates.append(a.lemma_id)
                return conj_candidates, "suggestion"

        return [], "none"

    def _try_conjugator_gemination(self, form: str) -> list:
        """Try doubling consonants at various positions to find conjugator matches.
        Handles scribal variants where gemination is not written (e.g., itapras for ittapras)."""
        if not self._conjugator:
            return []
        vowels = set('aeiuāēīū')
        for i in range(1, len(form)):
            if form[i] not in vowels and (i == 0 or form[i-1] in vowels):
                # Try doubling this consonant
                doubled = form[:i] + form[i] + form[i:]
                analyses = self._conjugator.lookup(doubled)
                if analyses:
                    return analyses
        return []

    def _try_gemination_lookup(self, form: str) -> List[str]:
        """Try doubling each consonant to find dictionary matches.
        Handles scribal variants where gemination is not written (e.g., ibissum → ibissûm)."""
        vowels = set('aeiuāēīū')
        for i in range(1, len(form)):
            if form[i] not in vowels and (i == 0 or form[i-1] in vowels):
                doubled = form[:i] + form[i] + form[i:]
                # Try direct match
                candidates = self._index.get(doubled, [])
                if candidates:
                    return self._rank_candidates(candidates, doubled)
                # Try with ending stripping
                for de in ['um', 'u', '']:
                    candidates = self._index.get(doubled + de, [])
                    if candidates:
                        return self._rank_candidates(candidates, doubled)
                # Try ending stripping on the doubled form
                candidates, level = self._lookup_strip_endings_with_level(doubled)
                if candidates:
                    return self._rank_candidates(candidates, doubled)
        return []

    # POS categories that are proper names — should always be ranked last
    PROPER_NAME_POS = {'PN', 'DN', 'TN', 'GN', 'RN', 'SN', 'EN', 'WN', 'MN', 'LN', 'CN', 'KN', 'ON'}

    def _rank_candidates(self, candidates: List[str], form: str) -> List[str]:
        """Rank candidates: common words first, proper names last.
        E.g., 'bēlu I' (lord) ranks above 'Bēl I' (divine name)."""
        form_lower = form.lower().translate(self.VOWEL_NORMALIZE)

        def score(word_id: str) -> tuple:
            # Check if it's a proper name (always demoted)
            pos = self.infer_pos(word_id)
            is_proper = 1 if pos in self.PROPER_NAME_POS else 0

            # Extract the base lemma from word_id (e.g., "ina I" -> "ina")
            base = word_id.rsplit(' ', 1)[0].lower().translate(self.VOWEL_NORMALIZE)
            if base == form_lower:
                return (is_proper, 0)  # Best: exact lemma match (but proper names still demoted)
            if form_lower.startswith(base) or base.startswith(form_lower):
                return (is_proper, 1)  # Good: stem match
            return (is_proper, 2)  # Weaker: only matched via attested form

        return sorted(candidates, key=score)

    def has_only_proper_names(self, candidates: List[str]) -> bool:
        """Check if all candidates are proper names (PN, DN, TN, etc.)."""
        if not candidates:
            return False
        return all(self.infer_pos(c) in self.PROPER_NAME_POS for c in candidates)

    @staticmethod
    def _join_syllables(hyphenated: str) -> str:
        """Join ATF syllables following Akkadian reading rules.

        ATF syllable patterns: V, CV, VC, CVC
        When joining, overlapping sounds at syllable boundaries are merged:
          CV-VC  → CVC     (li-ib → lib: shared vowel i)
          VC-CV  → VCCV    (ib-bi → ibbi: shared consonant b)
          CVC-CV → CVCCV   (ip-ru → ipru: no overlap, r≠u)

        Examples:
          li-ib-bi  → lib + bi  → libbi
          ip-ru-us  → ip + ru + us → iprus
          ta-am-gu-ur → tam + gu + ur → tamgur
          a-na → ana
        """
        syllables = hyphenated.split('-')
        if len(syllables) <= 1:
            return hyphenated.replace('-', '')

        VOWELS = set('aeiuāēīūâêîû')

        result = syllables[0]
        for i in range(1, len(syllables)):
            curr = syllables[i]
            if not result or not curr:
                result += curr
                continue

            last_char = result[-1]
            first_char = curr[0]

            # Only merge when a VOWEL is shared at the boundary (CV-VC pattern)
            # e.g., li-ib: last='i'(vowel), first='i'(vowel), same → merge → lib
            # Do NOT merge consonants: ib-bi keeps bb (geminate is real)
            if last_char == first_char and last_char in VOWELS:
                result += curr[1:]
            else:
                result += curr

        return result

    # Vowels for quality comparison (after normalization, same base vowel = exact)
    _VOWEL_QUALITY = {'a': 'a', 'e': 'e', 'i': 'i', 'u': 'u',
                      'ā': 'a', 'ē': 'e', 'ī': 'i', 'ū': 'u',
                      'â': 'a', 'ê': 'e', 'î': 'i', 'û': 'u'}

    def _vowels_match(self, form_vowels: str, dict_vowels: str) -> bool:
        """Check if two vowel sequences have the same quality (ignoring length).
        'a' matches 'ā' (same quality), but 'a' does not match 'i' or 'u'."""
        fv = [self._VOWEL_QUALITY.get(c, c) for c in form_vowels if c in self._VOWEL_QUALITY]
        dv = [self._VOWEL_QUALITY.get(c, c) for c in dict_vowels if c in self._VOWEL_QUALITY]
        return fv == dv

    def _extract_vowels(self, s: str) -> str:
        """Extract vowel characters from a string."""
        return ''.join(c for c in s if c.lower() in self._VOWEL_QUALITY)

    def _check_vowel_match(self, stem: str, candidate_ids: List[str]) -> bool:
        """Check if the stem's vowels match any candidate's citation form vowels."""
        stem_vowels = self._extract_vowels(stem)
        for cid in candidate_ids[:3]:  # Check first few candidates
            # Extract base lemma from ID: "šīpātu I" → "šīpātu"
            base = cid.rsplit(' ', 1)[0]
            base_vowels = self._extract_vowels(base)
            # Compare — the stem may be shorter (bound form), so compare prefix
            if len(stem_vowels) <= len(base_vowels):
                if self._vowels_match(stem_vowels, base_vowels[:len(stem_vowels)]):
                    return True
            elif self._vowels_match(stem_vowels[:len(base_vowels)], base_vowels):
                return True
        return False

    def _lookup_strip_endings(self, form: str) -> List[str]:
        candidates, _ = self._lookup_strip_endings_with_level(form)
        return candidates

    def _lookup_strip_endings_with_level(self, form: str) -> tuple:
        """Try stripping case endings. Returns (candidates, level).
        level = "exact" if nominative reconstruction matches AND vowels match, "suggestion" otherwise."""
        all_matches: List[tuple] = []

        for ending in self.CASE_ENDINGS:
            normalized_ending = ending.translate(self.VOWEL_NORMALIZE)
            if form.endswith(normalized_ending) and len(form) > len(normalized_ending) + 1:
                stem = form[:len(form) - len(normalized_ending)]
                # Nominative reconstruction (stem + um/u)
                for nom_end in ['um', 'u']:
                    candidates = self._index.get(stem + nom_end, [])
                    if candidates:
                        # Check vowel match to determine exact vs suggestion
                        level = "exact" if self._check_vowel_match(stem, candidates) else "suggestion"
                        all_matches.append((0, len(stem), candidates, level))
                # Direct stem match → suggestion
                candidates = self._index.get(stem, [])
                if candidates:
                    all_matches.append((1, len(stem), candidates, "suggestion"))
                # Other dict forms → suggestion
                for dict_ending in ['tu', 'tum', 'atum', 'utum']:
                    candidates = self._index.get(stem + dict_ending, [])
                    if candidates:
                        all_matches.append((2, len(stem), candidates, "suggestion"))

        if all_matches:
            all_matches.sort(key=lambda x: (-x[1], x[0]))
            return all_matches[0][2], all_matches[0][3]
        return [], "none"

    def _lookup_strip_possessive(self, form: str) -> List[str]:
        candidates, _ = self._lookup_strip_possessive_with_level(form)
        return candidates

    def _lookup_strip_possessive_with_level(self, form: str) -> tuple:
        """Try stripping possessive suffixes. Returns (candidates, level).
        level = "exact" if nominative reconstruction matches AND vowels match."""
        all_matches: List[tuple] = []

        for suffix in self.POSSESSIVE_SUFFIXES:
            norm_suffix = suffix.translate(self.VOWEL_NORMALIZE)
            if not form.endswith(norm_suffix) or len(form) <= len(norm_suffix) + 1:
                continue

            stem = form[:len(form) - len(norm_suffix)]

            stems_to_try = [stem]
            if len(stem) > 1 and stem[-1] in 'iau':
                stems_to_try.append(stem[:-1])

            for s in stems_to_try:
                if len(s) < 2:
                    continue

                # Nominative reconstruction
                for nom_end in ['um', 'u']:
                    candidates = self._index.get(s + nom_end, [])
                    if candidates:
                        level = "exact" if self._check_vowel_match(s, candidates) else "suggestion"
                        all_matches.append((0, len(s), candidates, level))

                # Direct stem match → suggestion
                candidates = self._index.get(s, [])
                if candidates:
                    all_matches.append((1, len(s), candidates, "suggestion"))

                # Other endings → suggestion
                for dict_ending in ['tum', 'tu']:
                    candidates = self._index.get(s + dict_ending, [])
                    if candidates:
                        all_matches.append((2, len(s), candidates, "suggestion"))

        if all_matches:
            all_matches.sort(key=lambda x: (x[0], -x[1]))
            return all_matches[0][2], all_matches[0][3]
        return [], "none"

    # Mapping for restoring long vowels stripped during URL encoding/decoding
    _VOWEL_RESTORE = {
        'a': 'ā', 'e': 'ē', 'i': 'ī', 'u': 'ū',
    }

    def get_word_entry(self, word_id: str) -> Optional[WordEntry]:
        """Load a full word entry from disk."""
        safe_name = self._safe_filename(word_id)
        path = self.words_dir / f"{safe_name}.json"
        if not path.exists():
            # Try to find with vowel variations (URL encoding may strip macrons)
            # e.g., "ekallu I" should find "ēkallu_I.json"
            path = self._find_word_file(word_id)
            if not path:
                return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            actual_id = data.get("_id", word_id)
            return self._parse_word_entry(actual_id, data)
        except Exception as e:
            logger.error(f"Failed to load word entry '{word_id}': {e}")
            return None

    def _find_word_file(self, word_id: str) -> Optional[Path]:
        """Try to find a word file even if vowels lost macrons."""
        # Try direct safe filename
        safe = self._safe_filename(word_id)
        path = self.words_dir / f"{safe}.json"
        if path.exists():
            return path

        # Try with macron variants: replace each short vowel with long
        # e.g., "ekallu" → try "ēkallu", "ekallu", "ekāllu", etc.
        base = word_id.rsplit(' ', 1)  # Split "ekallu I" → ["ekallu", "I"]
        if len(base) == 2:
            lemma, homonym = base
        else:
            lemma, homonym = word_id, ""

        # Try each vowel position with macron
        for i, char in enumerate(lemma):
            if char in self._VOWEL_RESTORE:
                variant = lemma[:i] + self._VOWEL_RESTORE[char] + lemma[i+1:]
                vid = f"{variant} {homonym}".strip() if homonym else variant
                safe = self._safe_filename(vid)
                path = self.words_dir / f"{safe}.json"
                if path.exists():
                    return path

        return None

    def search_words(self, query: str, limit: int = 20) -> List[WordEntry]:
        """Smart search with case-based mode detection:
        - ALL CAPS (LUGAL) → search logograms
        - all lowercase (king, šarru) → search Akkadian + English
        - Mixed case (LUGAL-šu) → logogram with phonetic complement, strip lowercase
        """
        stripped = query.strip()
        if not stripped:
            return []

        # Detect search mode from case
        alpha_chars = [c for c in stripped if c.isalpha()]
        if not alpha_chars:
            return self._search_akkadian_english(stripped, limit)

        all_upper = all(c.isupper() for c in alpha_chars)
        all_lower = all(c.islower() for c in alpha_chars)

        if all_upper:
            # ALL CAPS → logogram search
            return self._search_logograms(stripped, limit)
        elif all_lower:
            # all lowercase → Akkadian + English
            return self._search_akkadian_english(stripped, limit)
        else:
            # Mixed case → logogram with phonetic complement
            # Strip lowercase parts: LUGAL-šu → LUGAL, E₂.GAL-lum → E₂.GAL
            logo_part = re.sub(r'[-.]?[a-zšṣṭḫāēīūâêîûĝ][a-zšṣṭḫāēīūâêîûĝ₀₁₂₃₄₅₆₇₈₉ₓ]*', '', stripped)
            logo_part = logo_part.rstrip('-.')
            if logo_part:
                return self._search_logograms(logo_part, limit)
            return self._search_akkadian_english(stripped, limit)

    def _search_logograms(self, query: str, limit: int = 20) -> List[WordEntry]:
        """Search the logogram index."""
        normalized = self._normalize_logogram(query)
        exact_ids = set()
        partial_ids = set()

        # Exact match
        exact_ids.update(self._logogram_index.get(normalized, []))
        # Also try with . replaced by -
        exact_ids.update(self._logogram_index.get(normalized.replace('.', '-'), []))
        exact_ids.update(self._logogram_index.get(normalized.replace('-', '.'), []))

        # Partial match (logogram contains query)
        for logo_key, lemma_ids in self._logogram_index.items():
            if logo_key != normalized and (normalized in logo_key or logo_key.startswith(normalized)):
                partial_ids.update(lemma_ids)
                if len(partial_ids) >= limit * 5:
                    break

        # Load entries: exact matches first, then partial
        results = []
        seen = set()
        for word_id in exact_ids:
            if word_id in seen:
                continue
            entry = self.get_word_entry(word_id)
            if entry:
                results.append(entry)
                seen.add(word_id)

        for word_id in partial_ids:
            if word_id in seen:
                continue
            entry = self.get_word_entry(word_id)
            if entry:
                results.append(entry)
                seen.add(word_id)

        return results[:limit]

    def _search_akkadian_english(self, query: str, limit: int = 20) -> List[WordEntry]:
        """Search Akkadian forms and English guide words."""
        query_lower = query.lower()
        matching_ids_akk = set()
        matching_ids_eng = set()
        max_candidates = 200

        # 1. Search Akkadian form index
        for form, lemma_ids in self._index.items():
            if query_lower in form:
                matching_ids_akk.update(lemma_ids)
                if len(matching_ids_akk) >= max_candidates:
                    break

        # 2. Search English guide word index
        for eng_word, lemma_ids in self._english_index.items():
            if query_lower == eng_word or query_lower in eng_word or eng_word.startswith(query_lower):
                matching_ids_eng.update(lemma_ids)
                if len(matching_ids_eng) >= max_candidates:
                    break

        # Combine all matches and load entries
        all_ids = matching_ids_akk | matching_ids_eng
        results = []
        for word_id in all_ids:
            entry = self.get_word_entry(word_id)
            if entry:
                results.append(entry)

        # Rank: exact English match > exact Akkadian lemma > partial matches
        def sort_key(entry: WordEntry) -> tuple:
            gw = entry.guide_word.lower()
            lemma_str = ' '.join(entry.lemma).lower()
            if gw == query_lower or gw.strip('() ') == query_lower:
                return (0, lemma_str)
            if gw.startswith(query_lower):
                return (1, lemma_str)
            if query_lower in gw.split():
                return (2, lemma_str)
            if lemma_str.startswith(query_lower):
                return (3, lemma_str)
            return (4, lemma_str)

        results.sort(key=sort_key)
        return results[:limit]

    async def download_dictionary(self, api_url: str, access_token: str) -> Dict[str, Any]:
        """Download the full eBL dictionary."""
        if self._downloading:
            return {"status": "already_downloading", "progress": self._download_progress, "total": self._download_total}

        self._downloading = True
        self._download_progress = 0

        try:
            headers = {"Content-Type": "application/json"}
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"

            # Step 1: Get all word IDs
            logger.info("Fetching word ID list from eBL...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(f"{api_url}/words/all", headers=headers)
                if response.status_code != 200:
                    raise ValueError(f"Failed to fetch word list: {response.status_code} {response.text}")
                word_ids = response.json()

            self._download_total = len(word_ids)
            logger.info(f"Found {self._download_total} words to download")

            # Step 2: Download entries in batches
            index: Dict[str, List[str]] = {}
            batch_size = 10
            word_count = 0

            for i in range(0, len(word_ids), batch_size):
                batch = word_ids[i:i + batch_size]
                tasks = [self._download_word(api_url, headers, word_id) for word_id in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for word_id, result in zip(batch, results):
                    if isinstance(result, Exception):
                        logger.warning(f"Failed to download '{word_id}': {result}")
                        continue

                    if result is None:
                        continue

                    # Save full entry to disk
                    safe_name = self._safe_filename(word_id)
                    path = self.words_dir / f"{safe_name}.json"
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=1)

                    # Build index entries from this word
                    self._index_word(index, word_id, result)
                    word_count += 1

                self._download_progress = min(i + batch_size, len(word_ids))

                # Small delay to avoid rate limiting
                if i + batch_size < len(word_ids):
                    await asyncio.sleep(0.2)

                if (i // batch_size) % 50 == 0:
                    logger.info(f"Dictionary download progress: {self._download_progress}/{self._download_total}")

            # Step 3: Save index
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False)

            self._index = index
            self._loaded = True

            # Step 4: Save metadata
            self._save_meta({
                "last_updated": datetime.utcnow().isoformat(),
                "word_count": word_count,
                "index_size": len(index)
            })

            logger.info(f"Dictionary download complete: {word_count} words, {len(index)} index entries")
            return {"status": "complete", "word_count": word_count, "index_size": len(index)}

        except Exception as e:
            logger.error(f"Dictionary download failed: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._downloading = False

    async def _download_word(self, api_url: str, headers: dict, word_id: str) -> Optional[Dict]:
        """Download a single word entry."""
        try:
            # URL-encode the word ID (may contain spaces, special chars)
            encoded_id = httpx.URL(f"{api_url}/words/{word_id}")
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(str(encoded_id), headers=headers)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # Rate limited — wait and retry
                    await asyncio.sleep(2)
                    response = await client.get(str(encoded_id), headers=headers)
                    if response.status_code == 200:
                        return response.json()
                logger.warning(f"Word '{word_id}' returned {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"Error downloading word '{word_id}': {e}")
            return None

    def _index_word(self, index: Dict[str, List[str]], word_id: str, data: Dict):
        """Extract all forms from a word entry and add to the index."""
        # Index the main lemma
        lemma_values = data.get("lemma", [])
        for lemma_val in lemma_values:
            normalized = self._normalize_form(lemma_val)
            if normalized:
                index.setdefault(normalized, [])
                if word_id not in index[normalized]:
                    index[normalized].append(word_id)

        # Index attested forms
        forms = data.get("forms", [])
        for form in forms:
            if not isinstance(form, dict):
                continue
            form_lemmas = form.get("lemma", [])
            if not isinstance(form_lemmas, list):
                form_lemmas = [form_lemmas]
            for form_val in form_lemmas:
                normalized = self._normalize_form(form_val)
                if normalized:
                    index.setdefault(normalized, [])
                    if word_id not in index[normalized]:
                        index[normalized].append(word_id)

        # NOTE: Logograms from word entries are NOT indexed here.
        # They belong in the logogram index (built from signs data) to avoid
        # collisions between logogram names and Akkadian syllabic forms
        # (e.g., logogram DAM = wife/husband vs. Akkadian syllable dam- in damāmu).

    @staticmethod
    def _index_english(index: Dict[str, List[str]], word_id: str, data: Dict):
        """Index English guide words and meanings for bidirectional search."""
        guide_word = data.get("guideWord", "")
        if isinstance(guide_word, str) and guide_word:
            # Split guide word into individual words for partial matching
            # e.g., "to cut off" indexes "to", "cut", "off", "to cut off"
            gw_lower = guide_word.lower().strip('() ')
            # Index the full guide word
            index.setdefault(gw_lower, [])
            if word_id not in index[gw_lower]:
                index[gw_lower].append(word_id)
            # Index individual words (skip very short ones)
            for word in gw_lower.split():
                word = word.strip('(),;.!?')
                if len(word) >= 3:
                    index.setdefault(word, [])
                    if word_id not in index[word]:
                        index[word].append(word_id)

    def _normalize_form(self, form) -> str:
        """Normalize a form string for index lookup."""
        if not form:
            return ""
        # Handle unexpected types (eBL data can have lists in form fields)
        if isinstance(form, list):
            return self._normalize_form(form[0]) if form else ""
        if not isinstance(form, str):
            return str(form)
        # Remove parentheses, brackets often used in citation forms
        cleaned = re.sub(r'[(){}\[\]]', '', form)
        # Translate subscript digits
        cleaned = cleaned.translate(SUBSCRIPT_MAP)
        # Normalize long vowels (ā→a, ī→i, ū→u, ē→e)
        cleaned = cleaned.translate(str.maketrans('āēīūâêîûĀĒĪŪÂÊÎÛ', 'aeiuaeiuAEIUAEIU'))
        # Lowercase
        cleaned = cleaned.lower().strip()
        return cleaned

    def _parse_word_entry(self, word_id: str, data: Dict) -> WordEntry:
        """Parse a raw eBL word entry into our model."""
        forms = []
        for form in data.get("forms", []):
            for lemma_val in form.get("lemma", []):
                forms.append(lemma_val)

        return WordEntry(
            word_id=word_id,
            lemma=data.get("lemma", []),
            homonym=data.get("homonym", ""),
            pos=data.get("pos", []),
            guide_word=data.get("guideWord", ""),
            roots=data.get("roots", []),
            forms=forms,
            origin=", ".join(data["origin"]) if isinstance(data.get("origin"), list) else data.get("origin", "")
        )

    @staticmethod
    def _safe_filename(word_id: str) -> str:
        """Convert a word ID to a safe filename."""
        # Replace problematic characters
        return re.sub(r'[<>:"/\\|?*\s]', '_', word_id)

    @property
    def is_downloading(self) -> bool:
        return self._downloading

    @property
    def download_progress(self) -> Dict[str, int]:
        return {"progress": self._download_progress, "total": self._download_total}
