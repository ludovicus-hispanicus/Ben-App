"""
Akkadian Verb Conjugator — productive rule-based generation of verbal forms.

Given root consonants (C1, C2, C3) + vowel class, generates all conjugated forms
for all stems (G, D, Š, N, Gt, Dt, Št, Ntn, etc.) and builds a reverse index
mapping surface forms back to lemma + morphological analysis.

Templates based on Huehnergard's Grammar of Akkadian and eAkkadian (DigitalPasts).
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MorphAnalysis:
    """Morphological analysis of a conjugated form."""
    lemma_id: str           # e.g. "parāsu I"
    root: str               # e.g. "prs"
    stem: str               # G, D, Š, N, Gt, Dt, Št, Ntn...
    tense: str              # pret, dur, perf, imp, inf, ptcp, stat, vadj
    person: str             # 3cs, 2ms, 2fs, 1cs, 3mp, 3fp, 2cp, 1cp, or "" for non-finite
    form: str               # the surface form


# ── Person affixes ──

# G-type prefixes (G, Gt, Gtn, N, Nt, Ntn)
G_PREFIXES = {
    '3cs': 'i', '3mp': 'i', '3fp': 'i',
    '2ms': 'ta', '2fs': 'ta', '2cp': 'ta',
    '1cs': 'a', '1cp': 'ni',
}

# D/Š-type prefixes (D, Dt, Dtn, Š, Št, Štn)
DS_PREFIXES = {
    '3cs': 'u', '3mp': 'u', '3fp': 'u',
    '2ms': 'tu', '2fs': 'tu', '2cp': 'tu',
    '1cs': 'u', '1cp': 'nu',
}

# Suffixes for finite forms
PERSON_SUFFIXES = {
    '3cs': '', '2ms': '', '1cs': '',
    '2fs': 'ī', '3mp': 'ū', '3fp': 'ā',
    '2cp': 'ā', '1cp': '',
}

# Stative suffixes
STATIVE_SUFFIXES = {
    '3ms': '', '3fs': 'at', '2ms': 'āta', '2fs': 'āti',
    '1cs': 'āku', '3mp': 'ū', '3fp': 'ā',
    '2mp': 'ātunu', '2fp': 'ātina', '1cp': 'ānu',
}

# Imperative persons
IMP_SUFFIXES = {
    '2ms': '', '2fs': 'ī', '2cp': 'ā',
}

# Vowel classes: maps class name -> (preterite_vowel, durative_vowel)
VOWEL_CLASSES = {
    'a/u': ('u', 'a'),
    'a_u': ('u', 'a'),
    'i/i': ('i', 'i'),
    'i':   ('i', 'i'),
    'u/u': ('u', 'u'),
    'u':   ('u', 'u'),
    'a/a': ('a', 'a'),
    'a':   ('a', 'a'),
}

# Finite persons for full paradigm
FINITE_PERSONS = ['3cs', '2ms', '2fs', '1cs', '3mp', '3fp', '2cp', '1cp']
STATIVE_PERSONS = ['3ms', '3fs', '2ms', '2fs', '1cs', '3mp', '3fp', '1cp']
IMP_PERSONS = ['2ms', '2fs', '2cp']


class AkkadianConjugator:
    """Generates Akkadian verbal forms from root + vowel class using morphological templates."""

    def __init__(self):
        self._reverse_index: Dict[str, List[MorphAnalysis]] = {}
        self._built = False

    # ── G-Stem templates ──

    def _g_preterite(self, c1: str, c2: str, c3: str, v_pret: str) -> Dict[str, str]:
        """G Preterite: prefix + C1C2vC3"""
        stem = f"{c1}{c2}{v_pret}{c3}"
        return self._apply_g_prefixes(stem)

    def _g_durative(self, c1: str, c2: str, c3: str, v_dur: str) -> Dict[str, str]:
        """G Durative/Present: prefix + C1aC2C2aC3"""
        stem = f"{c1}a{c2}{c2}a{c3}"
        return self._apply_g_prefixes(stem)

    def _g_perfect(self, c1: str, c2: str, c3: str, v_pret: str) -> Dict[str, str]:
        """G Perfect: prefix + C1taC2aC3"""
        stem = f"{c1}ta{c2}a{c3}"
        return self._apply_g_prefixes(stem)

    def _g_imperative(self, c1: str, c2: str, c3: str, v_pret: str) -> Dict[str, str]:
        """G Imperative: C1vC2vC3 (a/u class: purus)"""
        forms = {}
        for person, suffix in IMP_SUFFIXES.items():
            if person == '2ms':
                form = f"{c1}{v_pret}{c2}{v_pret}{c3}"
            elif person == '2fs':
                # Remove second theme vowel, add suffix: pursi
                form = f"{c1}{v_pret}{c2}{c3}{suffix}"
            else:  # 2cp
                form = f"{c1}{v_pret}{c2}{c3}{suffix}"
            forms[person] = form
        return forms

    def _g_infinitive(self, c1: str, c2: str, c3: str) -> str:
        """G Infinitive: C1arāC3um"""
        return f"{c1}a{c2}ā{c3}um"

    def _g_participle(self, c1: str, c2: str, c3: str) -> str:
        """G Participle: C1āC2iC3um"""
        return f"{c1}ā{c2}i{c3}um"

    def _g_verbal_adj(self, c1: str, c2: str, c3: str, v_pret: str) -> str:
        """G Verbal Adjective: C1aC2C3um (paris-type)"""
        return f"{c1}a{c2}i{c3}um"

    # Stative suffixes that cause the theme vowel to drop (consonant-initial)
    STATIVE_DROP_SUFFIXES = {'3fs', '2ms', '2fs', '1cs', '2mp', '2fp', '1cp'}

    def _g_stative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """G Stative: 3ms paris, 3fs parsat (theme vowel drops before consonantal suffix)"""
        forms = {}
        for person, suffix in STATIVE_SUFFIXES.items():
            if person in self.STATIVE_DROP_SUFFIXES:
                # Theme vowel drops: paris → pars + at
                forms[person] = f"{c1}a{c2}{c3}{suffix}"
            else:
                # No suffix or vowel-only suffix: keep full base
                forms[person] = f"{c1}a{c2}i{c3}{suffix}"
        return forms

    # ── D-Stem templates ──

    def _d_preterite(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """D Preterite: uprefix + C1aC2C2iC3"""
        stem = f"{c1}a{c2}{c2}i{c3}"
        return self._apply_ds_prefixes(stem)

    def _d_durative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """D Durative: uprefix + C1aC2C2aC3"""
        stem = f"{c1}a{c2}{c2}a{c3}"
        return self._apply_ds_prefixes(stem)

    def _d_perfect(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """D Perfect: uprefix + C1taC2C2iC3"""
        stem = f"{c1}ta{c2}{c2}i{c3}"
        return self._apply_ds_prefixes(stem)

    def _d_imperative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """D Imperative: C1uC2C2iC3"""
        forms = {}
        for person, suffix in IMP_SUFFIXES.items():
            if person == '2ms':
                form = f"{c1}u{c2}{c2}i{c3}"
            else:
                form = f"{c1}u{c2}{c2}i{c3}{suffix}"
            forms[person] = form
        return forms

    def _d_infinitive(self, c1: str, c2: str, c3: str) -> str:
        """D Infinitive: C1uC2C2uC3um"""
        return f"{c1}u{c2}{c2}u{c3}um"

    def _d_stative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """D Stative: 3ms purrus, 3fs purrusat"""
        forms = {}
        for person, suffix in STATIVE_SUFFIXES.items():
            if person in self.STATIVE_DROP_SUFFIXES:
                forms[person] = f"{c1}u{c2}{c2}{c3}{suffix}"
            else:
                forms[person] = f"{c1}u{c2}{c2}u{c3}{suffix}"
        return forms

    # ── Š-Stem templates ──

    def _sh_preterite(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Š Preterite: uprefix + šaC1C2iC3"""
        stem = f"ša{c1}{c2}i{c3}"
        return self._apply_ds_prefixes(stem)

    def _sh_durative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Š Durative: uprefix + šaC1C2aC3"""
        stem = f"ša{c1}{c2}a{c3}"
        return self._apply_ds_prefixes(stem)

    def _sh_perfect(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Š Perfect: uprefix + štaC1C2iC3"""
        stem = f"šta{c1}{c2}i{c3}"
        return self._apply_ds_prefixes(stem)

    def _sh_imperative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Š Imperative: šuC1C2iC3"""
        forms = {}
        for person, suffix in IMP_SUFFIXES.items():
            if person == '2ms':
                form = f"šu{c1}{c2}i{c3}"
            else:
                form = f"šu{c1}{c2}i{c3}{suffix}"
            forms[person] = form
        return forms

    def _sh_infinitive(self, c1: str, c2: str, c3: str) -> str:
        """Š Infinitive: šuC1C2uC3um"""
        return f"šu{c1}{c2}u{c3}um"

    def _sh_stative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Š Stative: 3ms šuprus, 3fs šuprusat"""
        forms = {}
        for person, suffix in STATIVE_SUFFIXES.items():
            if person in self.STATIVE_DROP_SUFFIXES:
                forms[person] = f"šu{c1}{c2}{c3}{suffix}"
            else:
                forms[person] = f"šu{c1}{c2}u{c3}{suffix}"
        return forms

    # ── N-Stem templates ──

    def _n_preterite(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """N Preterite: prefix + nC1aC2iC3 (n assimilates to C1)"""
        stem = f"n{c1}a{c2}i{c3}"
        return self._apply_g_prefixes(stem)

    def _n_durative(self, c1: str, c2: str, c3: str, v_dur: str) -> Dict[str, str]:
        """N Durative: prefix + nC1aC2C2aC3 (n assimilates)"""
        stem = f"n{c1}a{c2}{c2}a{c3}"
        return self._apply_g_prefixes(stem)

    def _n_perfect(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """N Perfect: prefix + ntaC1C2aC3 (nt → tt often)"""
        stem = f"nta{c1}{c2}a{c3}"
        return self._apply_g_prefixes(stem)

    def _n_imperative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """N Imperative: naC1C2iC3"""
        forms = {}
        for person, suffix in IMP_SUFFIXES.items():
            if person == '2ms':
                form = f"na{c1}{c2}i{c3}"
            else:
                form = f"na{c1}{c2}i{c3}{suffix}"
            forms[person] = form
        return forms

    def _n_infinitive(self, c1: str, c2: str, c3: str) -> str:
        """N Infinitive: naC1C2uC3um"""
        return f"na{c1}{c2}u{c3}um"

    def _n_stative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """N Stative: 3ms naprus, 3fs naprusat"""
        forms = {}
        for person, suffix in STATIVE_SUFFIXES.items():
            if person in self.STATIVE_DROP_SUFFIXES:
                forms[person] = f"na{c1}{c2}{c3}{suffix}"
            else:
                forms[person] = f"na{c1}{c2}u{c3}{suffix}"
        return forms

    # ── Gt-Stem templates ──

    def _gt_preterite(self, c1: str, c2: str, c3: str, v_pret: str) -> Dict[str, str]:
        """Gt Preterite: prefix + C1taC2vC3"""
        stem = f"{c1}ta{c2}{v_pret}{c3}"
        return self._apply_g_prefixes(stem)

    def _gt_durative(self, c1: str, c2: str, c3: str, v_dur: str) -> Dict[str, str]:
        """Gt Durative: prefix + C1taC2C2aC3"""
        stem = f"{c1}ta{c2}{c2}a{c3}"
        return self._apply_g_prefixes(stem)

    def _gt_perfect(self, c1: str, c2: str, c3: str, v_pret: str) -> Dict[str, str]:
        """Gt Perfect: prefix + C1tatC2vC3"""
        stem = f"{c1}tat{c2}{v_pret}{c3}"
        return self._apply_g_prefixes(stem)

    def _gt_infinitive(self, c1: str, c2: str, c3: str) -> str:
        """Gt Infinitive: C1itC2uC3um"""
        return f"{c1}it{c2}u{c3}um"

    # ── Dt-Stem templates ──

    def _dt_preterite(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Dt Preterite: uprefix + C1taC2C2iC3"""
        stem = f"{c1}ta{c2}{c2}i{c3}"
        return self._apply_ds_prefixes(stem)

    def _dt_durative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Dt Durative: uprefix + C1taC2C2aC3"""
        stem = f"{c1}ta{c2}{c2}a{c3}"
        return self._apply_ds_prefixes(stem)

    # ── Št-Stem templates ──

    def _sht_preterite(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Št Preterite: uprefix + štaC1C2iC3"""
        stem = f"šta{c1}{c2}i{c3}"
        return self._apply_ds_prefixes(stem)

    def _sht_durative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Št Durative: uprefix + štaC1C2aC3"""
        stem = f"šta{c1}{c2}a{c3}"
        return self._apply_ds_prefixes(stem)

    # ── III-weak verb templates (C3 = ʾ/w/y, contracts with following vowel) ──
    # banû "to build" (root bny): G pret ibni, dur ibanni, perf ibtani, stat bani

    def _g_iiiweak_preterite(self, c1: str, c2: str, v_pret: str) -> Dict[str, str]:
        """G Preterite III-weak: prefix + C1C2V (contracted)
        a/u class: ibni (i), i class: ibni (i), u class: ibnu (but usually i)"""
        forms = {}
        # The preterite vowel merges with the weak C3: always ends in long vowel
        for person, prefix in G_PREFIXES.items():
            suffix = PERSON_SUFFIXES[person]
            if suffix in ('ū', 'ā'):
                # 3mp/3fp/2cp: ibnū, ibniā → ibnû, ibniā
                stem = f"{c1}{c2}{v_pret}"
                forms[person] = prefix + stem + suffix
            elif suffix == 'ī':
                # 2fs: tabnī
                stem = f"{c1}{c2}"
                forms[person] = prefix + stem + 'ī'
            else:
                # 3cs/2ms/1cs/1cp: ibni
                stem = f"{c1}{c2}i"
                forms[person] = prefix + stem
        return forms

    def _g_iiiweak_durative(self, c1: str, c2: str) -> Dict[str, str]:
        """G Durative III-weak: prefix + C1aC2C2V (doubled C2 + contracted vowel)
        ibanni, ibannu"""
        forms = {}
        for person, prefix in G_PREFIXES.items():
            suffix = PERSON_SUFFIXES[person]
            if suffix in ('ū', 'ā'):
                stem = f"{c1}a{c2}{c2}"
                forms[person] = prefix + stem + suffix
            elif suffix == 'ī':
                stem = f"{c1}a{c2}{c2}"
                forms[person] = prefix + stem + 'ī'
            else:
                stem = f"{c1}a{c2}{c2}i"
                forms[person] = prefix + stem
        return forms

    def _g_iiiweak_perfect(self, c1: str, c2: str) -> Dict[str, str]:
        """G Perfect III-weak: prefix + C1taC2V (contracted)
        ibtani"""
        forms = {}
        for person, prefix in G_PREFIXES.items():
            suffix = PERSON_SUFFIXES[person]
            if suffix in ('ū', 'ā'):
                stem = f"{c1}ta{c2}"
                forms[person] = prefix + stem + suffix
            elif suffix == 'ī':
                stem = f"{c1}ta{c2}"
                forms[person] = prefix + stem + 'ī'
            else:
                stem = f"{c1}ta{c2}i"
                forms[person] = prefix + stem
        return forms

    def _g_iiiweak_imperative(self, c1: str, c2: str) -> Dict[str, str]:
        """G Imperative III-weak: biní (2ms), binī (2fs), biniā (2cp)"""
        return {
            '2ms': f"{c1}i{c2}i",
            '2fs': f"{c1}i{c2}ī",
            '2cp': f"{c1}i{c2}iā",
        }

    def _g_iiiweak_stative(self, c1: str, c2: str) -> Dict[str, str]:
        """G Stative III-weak: bani (3ms), baniāt (3fs), etc."""
        base = f"{c1}a{c2}i"
        forms = {}
        for person, suffix in STATIVE_SUFFIXES.items():
            forms[person] = base + suffix
        return forms

    def _g_iiiweak_infinitive(self, c1: str, c2: str) -> str:
        """G Infinitive III-weak: banûm"""
        return f"{c1}a{c2}ûm"

    def _g_iiiweak_participle(self, c1: str, c2: str) -> str:
        """G Participle III-weak: bānûm"""
        return f"{c1}ā{c2}ûm"

    # ── Ntn-Stem templates ──

    def _ntn_preterite(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Ntn Preterite: prefix + ntaC1C2iC3 (like N perfect but iterative)"""
        stem = f"nta{c1}{c2}i{c3}"
        return self._apply_g_prefixes(stem)

    def _ntn_durative(self, c1: str, c2: str, c3: str) -> Dict[str, str]:
        """Ntn Durative: prefix + ntanaC1C2aC3"""
        stem = f"ntana{c1}{c2}a{c3}"
        return self._apply_g_prefixes(stem)

    # ── Helper: apply prefixes ──

    def _apply_g_prefixes(self, stem: str) -> Dict[str, str]:
        forms = {}
        for person, prefix in G_PREFIXES.items():
            suffix = PERSON_SUFFIXES[person]
            forms[person] = prefix + stem + suffix
        return forms

    def _apply_ds_prefixes(self, stem: str) -> Dict[str, str]:
        forms = {}
        for person, prefix in DS_PREFIXES.items():
            suffix = PERSON_SUFFIXES[person]
            forms[person] = prefix + stem + suffix
        return forms

    # ── Phonological rules ──

    def _apply_phonology(self, form: str) -> List[str]:
        """Apply Akkadian phonological rules, returning all surface variants."""
        variants = [form]
        result = set()

        for v in variants:
            v = self._n_assimilation(v)
            v = self._t_assimilation(v)
            v = self._vowel_syncope(v)
            result.add(v)
            # Also add without mimation
            if v.endswith('um'):
                result.add(v[:-2])
            elif v.endswith('im'):
                result.add(v[:-2])
            elif v.endswith('am'):
                result.add(v[:-2])

        return list(result)

    def _n_assimilation(self, form: str) -> str:
        """N-stem: n assimilates to following consonant.
        inparis → ipparis, inparras → ipparras"""
        # n before consonant (not a vowel) → double the consonant
        def _assimilate(m):
            next_char = m.group(1)
            if next_char not in 'aeiuāēīū':
                return next_char + next_char
            return 'n' + next_char
        return re.sub(r'n([a-zšṣṭʾ])', _assimilate, form)

    def _t_assimilation(self, form: str) -> str:
        """t-infix assimilation rules:
        - After d/ṭ: dt → tt, ṭt → ṭṭ
        - After s/ṣ: st → st (or ss in some dialects)
        - After z: zt → zd or zt
        """
        form = form.replace('dt', 'tt')
        form = form.replace('ṭt', 'ṭṭ')
        # t after sibilants: metathesis st → ts (sometimes ss)
        return form

    def _vowel_syncope(self, form: str) -> str:
        """Short unstressed vowels between single consonants can syncopate.
        This is context-dependent; we apply conservatively."""
        # Don't syncopate — too aggressive without stress info
        return form

    # ── Root extraction ──

    # Weak radicals that mark III-weak verbs
    WEAK_RADICALS = {'ʾ', 'y', 'w'}

    @staticmethod
    def extract_root_consonants(root_str: str) -> Optional[Tuple[str, str, str]]:
        """Extract C1, C2, C3 from eBL root notation like 'prs', ''bt', 'škn', 'bny', 'mlʾ'.
        Returns (c1, c2, c3) where c3 may be empty for III-weak verbs."""
        if not root_str:
            return None

        # Normalize aleph
        clean = root_str.replace("'", "ʾ")

        # Extract consonants (skip vowels)
        consonants = []
        i = 0
        while i < len(clean):
            ch = clean[i]
            if ch in 'aeiuāēīū':
                i += 1
                continue
            consonants.append(ch)
            i += 1

        if len(consonants) >= 3:
            c1, c2, c3 = consonants[0], consonants[1], consonants[2]
            # Mark III-weak: if C3 is aleph/y/w, set to empty for weak templates
            if c3 in AkkadianConjugator.WEAK_RADICALS:
                return (c1, c2, '')
            return (c1, c2, c3)
        elif len(consonants) == 2:
            # Could be II-weak (C1_C3) or III-weak written without C3
            return (consonants[0], consonants[1], '')
        return None

    @staticmethod
    def extract_vowel_class(amplified_meanings: list) -> str:
        """Extract vowel class from eBL amplifiedMeanings field."""
        for am in amplified_meanings:
            if am.get('key') == 'G':
                vowels = am.get('vowels', [])
                if vowels:
                    vals = vowels[0].get('value', [])
                    if len(vals) >= 2:
                        return f"{vals[0]}/{vals[1]}"
                    elif len(vals) == 1:
                        return f"{vals[0]}/{vals[0]}"
                # Try parsing from meaning text
                meaning = am.get('meaning', '')
                m = re.search(r'\*([aiu])/([aiu])\*', meaning)
                if m:
                    return f"{m.group(1)}/{m.group(2)}"
                m = re.search(r'\(([aiu])/([aiu])\)', meaning)
                if m:
                    return f"{m.group(1)}/{m.group(2)}"
        return 'a/u'  # default

    # ── Full conjugation ──

    def conjugate(self, lemma_id: str, root: str, vowel_class: str = 'a/u',
                  stems: Optional[List[str]] = None) -> List[MorphAnalysis]:
        """Generate all forms for a verb.

        Args:
            lemma_id: e.g. "parāsu I"
            root: e.g. "prs"
            vowel_class: e.g. "a/u", "i/i", "u/u"
            stems: list of stems to generate (default: all available from eBL data)

        Returns:
            List of MorphAnalysis objects.
        """
        parsed = self.extract_root_consonants(root)
        if not parsed:
            return []

        c1, c2, c3 = parsed

        # Detect verb type
        is_iii_weak = (c2 and not c3)

        if not c2:
            # II-weak — not handled yet
            return []

        vc = VOWEL_CLASSES.get(vowel_class, VOWEL_CLASSES.get('a/u'))
        v_pret, v_dur = vc

        if stems is None:
            stems = ['G', 'D', 'Š', 'N']

        results = []

        for stem in stems:
            if is_iii_weak:
                forms = self._generate_stem_iii_weak(stem, c1, c2, v_pret, v_dur)
            else:
                forms = self._generate_stem(stem, c1, c2, c3, v_pret, v_dur)
            for (tense, person), raw_form in forms.items():
                for surface in self._apply_phonology(raw_form):
                    results.append(MorphAnalysis(
                        lemma_id=lemma_id,
                        root=root,
                        stem=stem,
                        tense=tense,
                        person=person,
                        form=surface,
                    ))

        return results

    def _generate_stem(self, stem: str, c1: str, c2: str, c3: str,
                       v_pret: str, v_dur: str) -> Dict[Tuple[str, str], str]:
        """Generate all forms for a single stem."""
        forms: Dict[Tuple[str, str], str] = {}

        if stem == 'G':
            for p, f in self._g_preterite(c1, c2, c3, v_pret).items():
                forms[('pret', p)] = f
            for p, f in self._g_durative(c1, c2, c3, v_dur).items():
                forms[('dur', p)] = f
            for p, f in self._g_perfect(c1, c2, c3, v_pret).items():
                forms[('perf', p)] = f
            for p, f in self._g_imperative(c1, c2, c3, v_pret).items():
                forms[('imp', p)] = f
            for p, f in self._g_stative(c1, c2, c3).items():
                forms[('stat', p)] = f
            forms[('inf', '')] = self._g_infinitive(c1, c2, c3)
            forms[('ptcp', '')] = self._g_participle(c1, c2, c3)
            forms[('vadj', '')] = self._g_verbal_adj(c1, c2, c3, v_pret)

        elif stem == 'D':
            for p, f in self._d_preterite(c1, c2, c3).items():
                forms[('pret', p)] = f
            for p, f in self._d_durative(c1, c2, c3).items():
                forms[('dur', p)] = f
            for p, f in self._d_perfect(c1, c2, c3).items():
                forms[('perf', p)] = f
            for p, f in self._d_imperative(c1, c2, c3).items():
                forms[('imp', p)] = f
            for p, f in self._d_stative(c1, c2, c3).items():
                forms[('stat', p)] = f
            forms[('inf', '')] = self._d_infinitive(c1, c2, c3)

        elif stem == 'Š':
            for p, f in self._sh_preterite(c1, c2, c3).items():
                forms[('pret', p)] = f
            for p, f in self._sh_durative(c1, c2, c3).items():
                forms[('dur', p)] = f
            for p, f in self._sh_perfect(c1, c2, c3).items():
                forms[('perf', p)] = f
            for p, f in self._sh_imperative(c1, c2, c3).items():
                forms[('imp', p)] = f
            for p, f in self._sh_stative(c1, c2, c3).items():
                forms[('stat', p)] = f
            forms[('inf', '')] = self._sh_infinitive(c1, c2, c3)

        elif stem == 'N':
            for p, f in self._n_preterite(c1, c2, c3).items():
                forms[('pret', p)] = f
            for p, f in self._n_durative(c1, c2, c3, v_dur).items():
                forms[('dur', p)] = f
            for p, f in self._n_perfect(c1, c2, c3).items():
                forms[('perf', p)] = f
            for p, f in self._n_imperative(c1, c2, c3).items():
                forms[('imp', p)] = f
            for p, f in self._n_stative(c1, c2, c3).items():
                forms[('stat', p)] = f
            forms[('inf', '')] = self._n_infinitive(c1, c2, c3)

        elif stem == 'Gt':
            for p, f in self._gt_preterite(c1, c2, c3, v_pret).items():
                forms[('pret', p)] = f
            for p, f in self._gt_durative(c1, c2, c3, v_dur).items():
                forms[('dur', p)] = f
            for p, f in self._gt_perfect(c1, c2, c3, v_pret).items():
                forms[('perf', p)] = f
            forms[('inf', '')] = self._gt_infinitive(c1, c2, c3)

        elif stem == 'Dt':
            for p, f in self._dt_preterite(c1, c2, c3).items():
                forms[('pret', p)] = f
            for p, f in self._dt_durative(c1, c2, c3).items():
                forms[('dur', p)] = f

        elif stem == 'Št':
            for p, f in self._sht_preterite(c1, c2, c3).items():
                forms[('pret', p)] = f
            for p, f in self._sht_durative(c1, c2, c3).items():
                forms[('dur', p)] = f

        elif stem == 'Ntn':
            for p, f in self._ntn_preterite(c1, c2, c3).items():
                forms[('pret', p)] = f
            for p, f in self._ntn_durative(c1, c2, c3).items():
                forms[('dur', p)] = f

        return forms

    def _generate_stem_iii_weak(self, stem: str, c1: str, c2: str,
                                v_pret: str, v_dur: str) -> Dict[Tuple[str, str], str]:
        """Generate forms for III-weak verbs (G-stem only for now)."""
        forms: Dict[Tuple[str, str], str] = {}

        if stem == 'G':
            for p, f in self._g_iiiweak_preterite(c1, c2, v_pret).items():
                forms[('pret', p)] = f
            for p, f in self._g_iiiweak_durative(c1, c2).items():
                forms[('dur', p)] = f
            for p, f in self._g_iiiweak_perfect(c1, c2).items():
                forms[('perf', p)] = f
            for p, f in self._g_iiiweak_imperative(c1, c2).items():
                forms[('imp', p)] = f
            for p, f in self._g_iiiweak_stative(c1, c2).items():
                forms[('stat', p)] = f
            forms[('inf', '')] = self._g_iiiweak_infinitive(c1, c2)
            forms[('ptcp', '')] = self._g_iiiweak_participle(c1, c2)

        # D/Š/N III-weak: use strong templates with empty C3 (forms end in vowel)
        # Not fully accurate but gives reasonable approximations
        elif stem in ('D', 'Š', 'N'):
            # Skip for now — these need special handling
            pass

        return forms

    # ── Reverse index ──

    def build_reverse_index(self, verb_entries: List[dict]) -> int:
        """Build reverse index from eBL verb entries.

        Args:
            verb_entries: list of raw eBL word JSON objects with pos=["V"]

        Returns:
            Number of forms indexed.
        """
        self._reverse_index.clear()
        count = 0

        for entry in verb_entries:
            lemma_id = entry.get('_id', '')
            roots = entry.get('roots', [])
            amp = entry.get('amplifiedMeanings', [])

            if not roots:
                continue

            vowel_class = self.extract_vowel_class(amp)

            # Determine which stems are attested
            attested_stems = []
            for am in amp:
                key = am.get('key', '')
                if key in ('G', 'D', 'Š', 'N', 'Gt', 'Dt', 'Št', 'Ntn'):
                    attested_stems.append(key)

            if not attested_stems:
                attested_stems = ['G']

            # Conjugate with ALL root variants (e.g., lapātu has roots ['lbt', 'lpt'])
            analyses = []
            for root in roots:
                analyses.extend(self.conjugate(lemma_id, root, vowel_class, attested_stems))

            # Finite tenses that can take ventive -am
            VENTIVE_TENSES = {'pret', 'dur', 'perf', 'imp'}

            for analysis in analyses:
                normalized = self._normalize_for_index(analysis.form)
                if normalized not in self._reverse_index:
                    self._reverse_index[normalized] = []
                self._reverse_index[normalized].append(analysis)
                count += 1

                # Add ventive variant (-am) for finite forms
                if analysis.tense in VENTIVE_TENSES and not analysis.person.endswith('p'):
                    # Ventive -am on singular forms (not plural -ū/-ā which use -nim)
                    vent_form = analysis.form + 'am'
                    vent_norm = self._normalize_for_index(vent_form)
                    vent_analysis = MorphAnalysis(
                        lemma_id=analysis.lemma_id,
                        root=analysis.root,
                        stem=analysis.stem,
                        tense=analysis.tense,
                        person=analysis.person + ' +vent.',
                        form=vent_form,
                    )
                    if vent_norm not in self._reverse_index:
                        self._reverse_index[vent_norm] = []
                    self._reverse_index[vent_norm].append(vent_analysis)
                    count += 1

        self._built = True
        logger.info(f"Conjugator reverse index built: {len(self._reverse_index)} unique forms, {count} total analyses")
        return count

    def lookup(self, form: str) -> List[MorphAnalysis]:
        """Look up a form in the reverse index."""
        if not self._built:
            return []
        normalized = self._normalize_for_index(form)
        return self._reverse_index.get(normalized, [])

    @staticmethod
    def _normalize_for_index(form: str) -> str:
        """Normalize a form for index lookup."""
        # Lowercase, strip long vowel markers
        form = form.lower()
        form = form.replace('ā', 'a').replace('ē', 'e').replace('ī', 'i').replace('ū', 'u')
        return form

    # ── Stats ──

    @property
    def index_size(self) -> int:
        return len(self._reverse_index)

    @property
    def is_built(self) -> bool:
        return self._built
