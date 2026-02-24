# eBL-ATF Complete Reference Guide

A comprehensive guide for annotating cuneiform tablets using eBL-ATF notation.
Based on the [official eBL-ATF specification](https://github.com/ElectronicBabylonianLiterature/ebl-api/blob/master/docs/ebl-atf.md) and Lark grammar files.

> **Note:** eBL-ATF is based on Oracc-ATF but is **not fully compatible** with other ATF flavours.
> eBL-ATF uses UTF-8 encoding.

---

## Table of Contents

1. [Line Types Overview](#line-types-overview)
2. [Text Lines](#text-lines)
3. [Damage and Preservation](#damage-and-preservation)
4. [Erasures](#erasures)
5. [Brackets and Enclosures](#brackets-and-enclosures)
6. [Flags and Modifiers](#flags-and-modifiers)
7. [Signs and Readings](#signs-and-readings)
8. [Determinatives and Glosses](#determinatives-and-glosses)
9. [Structure Lines (@-lines)](#structure-lines--lines)
10. [State Lines ($-lines)](#state-lines--lines)
11. [Language Shifts](#language-shifts)
12. [Commentary Protocols](#commentary-protocols)
13. [Notes and Translations](#notes-and-translations)
14. [Parallel Lines](#parallel-lines)
15. [Complete Examples](#complete-examples)
16. [Quick Reference Table](#quick-reference-table)

---

## Line Types Overview

eBL-ATF documents consist of different line types:

| Line Type | Prefix | Purpose |
|-----------|--------|---------|
| Empty | (none) | Blank lines |
| Text line | `N.` | Transliterated content |
| @-line | `@` | Object/surface structure |
| $-line | `$` | State descriptions |
| Note | `#note:` | Scholarly notes |
| Translation | `#tr` | Translations |
| Parallel | `//` | Parallel text references |
| Comment | `#` | Comments (other than note) |

---

## Text Lines

### Basic Format

```
LINE_NUMBER. CONTENT
```

### Line Number Formats

| Format | Example | Meaning |
|--------|---------|---------|
| Simple | `1.` | Line 1 |
| Prime | `1'.` | Line 1 prime (often second column) |
| Double prime | `1''.` | Line 1 double prime |
| With letter | `1a.` | Sub-line 1a |
| With prefix | `a+1.` | Line with letter prefix |
| Range | `1-3.` | Lines 1 through 3 |

**Examples:**
```
1. a-na be-li₂-ia
2. um-ma {m}ṣil-li-{d}IŠKUR-ma
1'. [...] x x [...]
2a. ki-a-am iq-bi
```

---

## Damage and Preservation

### Damage Flag `#`

Add `#` after a sign to indicate physical damage:

```
1. a-na#           → "ana" with damaged final sign
2. LUGAL#          → damaged LUGAL sign
3. a#-na#          → both signs damaged
```

### Uncertain Reading `?`

Add `?` when you're not sure of the reading:

```
1. a-na?           → uncertain reading of "ana"
2. LUGAL?          → uncertain if this is LUGAL
```

### Combining Flags

Flags can be combined (order matters):

```
1. a-na#?          → damaged AND uncertain
2. LUGAL?#         → uncertain AND damaged
3. a-na#!          → damaged but corrected reading
4. LUGAL*          → collated (verified on original)
```

### Flag Summary

| Flag | Meaning | When to Use |
|------|---------|-------------|
| `#` | Damaged | Sign is physically damaged |
| `?` | Uncertain | Reading is not certain |
| `!` | Correction | Scribal error, you've corrected it |
| `*` | Collated | Verified by examining original tablet |

---

## Erasures

Erasures mark where the scribe erased content. The erasure itself is not lemmatizable, but words written over erasure can be.

### Full Erasure (between words)

**Syntax:** `°ERASED\REPLACEMENT°`

- Left of `\` = what was erased
- Right of `\` = what replaced it (can be empty)

```
1. a-na °LUGAL\DUMU° i-din
   → LUGAL was erased, DUMU written over it

2. a-na °LUGAL\° i-din
   → LUGAL was erased, nothing written over it

3. a-na °\DUMU° i-din
   → something erased (illegible), DUMU written over it

4. a-na °\° i-din
   → erasure visible, both sides illegible
```

### Inline Erasure (within a word)

Same notation but within word boundaries:

```
1. a-°na\ta°-din
   → "na" was erased and replaced with "ta"

2. ša-°ar\°-ri
   → "ar" was erased, nothing over it
```

### Erasure vs. Removal

| Notation | Meaning |
|----------|---------|
| `°X\Y°` | Erasure - X erased, Y written over |
| `<<X>>` | Removal - X deliberately removed |

---

## Brackets and Enclosures

### Broken Away `[ ]`

Square brackets for **physically broken/missing** parts that you restore:

```
1. [a]-na                → "a" is broken, restored
2. [a-na]                → whole word broken, restored
3. a-[na]                → "na" is broken, restored
4. [...]                 → unknown number of signs broken
5. [...]-ri-im           → beginning broken, "-ri-im" preserved
6. a-na-[...]            → ending broken
7. [...] x [...]         → broken, one unclear sign, broken
```

### Perhaps Broken Away `( )`

Round brackets for **uncertain breaks** (maybe broken, maybe just unclear):

```
1. (a)-na                → "a" perhaps broken
2. a-(na)                → "na" perhaps broken
3. (a-na)                → whole word perhaps broken
```

### Accidental Omission `< >`

Angle brackets for signs the **scribe accidentally forgot**:

```
1. a-<na>                → scribe forgot to write "na"
2. <a>-na                → scribe forgot to write "a"
3. a-na <LUGAL>          → scribe forgot LUGAL
```

### Intentional Omission `<( )>`

Signs **intentionally left out** by the scribe:

```
1. a-<(na)>              → scribe intentionally omitted "na"
2. {d}<(AMAR.UTU)>       → divine name intentionally abbreviated
```

### Removal/Rasure `<< >>`

Content **deliberately removed** (different from erasure with replacement):

```
1. a-<<na>>              → "na" was deliberately removed
2. <<a-na>>              → whole word deliberately removed
3. <<LUGAL>> DUMU        → LUGAL removed, DUMU remains
```

### Nesting Brackets

Brackets can be nested:

```
1. [a-<na>]              → broken area containing omission
2. [(a-na)]              → perhaps broken, restored
3. [<<LUGAL>>]           → broken area showing removal
```

### Document-Oriented Gloss `{( )}`

For **interlinear glosses** in the original document:

```
1. a-na {(gloss-text)} be-li₂
```

---

## Signs and Readings

### Value Characters (lowercase)

Phonetic readings use: `a ā â b d e ē ê f g ĝ h ḫ i ī î y k l m n p q r s ṣ š t ṭ u ū û w z ʾ`

```
1. a-na be-li₂-ia
2. ša-ar-ri
3. DINGIR-MEŠ
```

### Logogram Characters (UPPERCASE)

Logograms use: `A Ā Â B D E Ē Ê G Ĝ H I Ī Î Y K L M N P Q R S Ṣ Š T Ṭ U Ū Û W Z Ḫ ʾ`

```
1. LUGAL GAL
2. DUMU.MUNUS
3. É.GAL
```

### Sub-indices (subscript numbers)

Use subscript numbers to distinguish homophones:

| Subscript | Unicode | Example |
|-----------|---------|---------|
| ₀ | U+2080 | ba₀ |
| ₁ | U+2081 | ba₁ |
| ₂ | U+2082 | ba₂ |
| ₃ | U+2083 | ba₃ |
| ₄ | U+2084 | ba₄ |
| ... | ... | ... |
| ₓ | U+2093 | baₓ (unknown index) |

```
1. be-li₂-ia              → bēlīya (li₂ = second "li" sign)
2. šar-ru-um              → no subscript needed
3. KI-MIN                 → logogram with subscript
```

### Special Signs

| Symbol | Meaning |
|--------|---------|
| `x` | One unclear sign (lowercase) |
| `X` | One unidentified sign (uppercase) |
| `...` | Unknown number of signs |

```
1. a-na x be-li₂         → one unclear sign between
2. a-na X be-li₂         → one unidentified sign
3. a-na ... be-li₂       → unknown number of signs
4. x x x                 → three unclear signs
```

### Joiners

Signs within words are connected by joiners:

| Joiner | Usage |
|--------|-------|
| `-` | Default sign separator |
| `+` | Ligature |
| `.` | Adjacent signs (in logograms) |
| `:` | Colon joiner |

```
1. a-na                   → standard hyphen
2. DUMU.MUNUS             → dot for logograms
3. AN+INANNA              → ligature
```

### Variants

Use `/` for variant readings:

```
1. LUGAL/MAN              → either LUGAL or MAN
2. a/e-na                 → "a" or "e"
```

---

## Determinatives and Glosses

### Determinatives `{ }`

Semantic classifiers (not pronounced):

| Determinative | Meaning | Example |
|---------------|---------|---------|
| `{d}` | Divine name | `{d}AMAR.UTU` |
| `{m}` | Male personal name | `{m}na-bi-um` |
| `{f}` | Female personal name | `{f}ta-ra-am-{d}UTU` |
| `{ki}` | Place name | `{ki}ba-bi-lam` |
| `{kur}` | Country/land | `{kur}aš-šur` |
| `{urudu}` | Copper object | `{urudu}ḫa-zi-in-nu` |
| `{giš}` | Wooden object | `{giš}TUKUL` |
| `{munus}` | Female | `{munus}SAL` |
| `{lú}` | Person/profession | `{lú}SANGA` |

```
1. {d}AMAR.UTU a-na {m}na-bi-um
2. ina {ki}ba-bi-lam{ki}
3. {lú}SANGA {d}UTU
```

### Phonetic Glosses `{+ }`

Pronunciation hints added by scribe:

```
1. AN{+a-nu-um}           → AN glossed as "anum"
2. LUGAL{+šar-ru}         → LUGAL glossed as "šarru"
```

### Linguistic Glosses `{{ }}`

Scholarly annotations:

```
1. a-na{{ANA}}            → linguistic gloss
```

---

## Structure Lines (@-lines)

### Objects

```
@tablet                   → standard clay tablet
@envelope                 → envelope for tablet
@prism                    → prism
@bulla                    → clay bulla/seal
@object clay cone         → custom object type
@fragment BM 12345        → fragment reference
```

### Surfaces

```
@obverse                  → front of tablet
@reverse                  → back of tablet
@left                     → left edge
@right                    → right edge
@top                      → top edge
@bottom                   → bottom edge
@edge                     → edge (unspecified)
@edge a                   → specific edge "a"
@face a                   → face "a" (for prisms)
@surface inscription      → custom surface name
```

### Columns

```
@column 1                 → column 1
@column 2                 → column 2
@column 1'                → column 1, damaged/prime
@column 2?                → column 2, uncertain
```

### Status Markers for Structure

| Marker | Meaning |
|--------|---------|
| `'` | Prime (damaged or second) |
| `?` | Uncertain |
| `!` | Correction |
| `*` | Collated |

```
@obverse'                 → damaged obverse
@reverse?                 → uncertain if reverse
@column 3!                → corrected column number
```

### Divisions

```
@colophon                 → colophon section
@catchline                → catchline
@date                     → date formula
@signature                → signature
@seal 1                   → seal impression 1
@seal 2                   → seal impression 2
```

### Headings

```
@h1                       → heading level 1
@h2                       → heading level 2
@h3 Section Title         → heading with text
```

---

## State Lines ($-lines)

### Basic States

```
$ blank                   → area is blank
$ broken                  → area is broken
$ missing                 → area is missing
$ effaced                 → area is effaced/worn
$ illegible               → area is illegible
$ traces                  → only traces visible
$ omitted                 → content omitted
$ continues               → text continues
```

### With Extent (Amount)

```
$ 1 line blank
$ 2 lines broken
$ 3 lines missing
$ 1-3 lines blank         → range
$ several lines broken
$ some lines missing
$ rest of obverse missing
$ beginning of reverse broken
$ middle of column effaced
$ end of tablet broken
```

### With Qualification

```
$ at least 3 lines missing
$ at most 5 lines blank
$ about 2 lines broken
```

### With Scope (What)

```
$ 3 lines blank           → lines
$ 2 columns missing       → columns
$ rest of obverse blank   → surface
$ 1 case broken           → case (for lexical lists)
```

### Rulings

Horizontal lines drawn by scribe:

```
$ single ruling
$ double ruling
$ triple ruling
```

### Status on $-lines

```
$ 3 lines missing?        → uncertain
$ rest broken!            → corrected assessment
$ 2 lines blank*          → collated/verified
```

### Loose Notation

For complex descriptions that don't fit the grammar:

```
$ (head of statue broken)
$ (surface badly worn)
$ (traces of 2-3 signs visible)
$ (ruling partially visible)
$ (seal impression illegible)
```

### Images

```
$ (image 1 = diagram of triangle)
$ (image 2a = drawing of tool)
```

---

## Language Shifts

Use `%` to indicate language changes:

### Common Shifts

| Shift | Language |
|-------|----------|
| `%akk` | Akkadian (default) |
| `%sux` | Sumerian |
| `%n` | Normalized Akkadian |
| `%grc` | Greek |

### Period-Specific Akkadian

| Shift | Period |
|-------|--------|
| `%ob` | Old Babylonian |
| `%mb` | Middle Babylonian |
| `%nb` | Neo-Babylonian |
| `%lb` | Late Babylonian |
| `%sb` | Standard Babylonian |
| `%na` | Neo-Assyrian |
| `%ma` | Middle Assyrian |
| `%oa` | Old Assyrian |

**Example:**
```
1. %sux lugal-e %akk LUGAL šu-a-tu
   → Sumerian "lugal-e", then Akkadian "LUGAL šu-a-tu"
```

---

## Commentary Protocols

For scholarly commentary texts:

| Protocol | Meaning |
|----------|---------|
| `!qt` | Quotation from base text |
| `!bs` | Base text being commented |
| `!cm` | Commentary/explanation |
| `!zz` | Uncertain protocol |

```
1. !bs KUR !cm ma-a-tu
   → base text "KUR", commentary "mātu"
```

---

## Notes and Translations

### Notes

```
#note: This line is damaged.
#note: @i{Collated by J. Smith 2023.}
#note: See @bib{RN123} for parallels.
```

### Note Markup

| Markup | Meaning |
|--------|---------|
| `@i{text}` | Italic |
| `@akk{text}` | Akkadian |
| `@sux{text}` | Sumerian |
| `@bib{REF}` | Bibliography reference |
| `@url{URL}` | URL link |

### Translations

```
#tr.en: To my lord speak!
#tr.de: Zu meinem Herrn sprich!
#tr.en.(o 1): For line obverse 1
```

---

## Parallel Lines

Reference parallel texts:

```
// F K.1234 o i 5          → parallel fragment
// cf. F BM.12345 r ii 3   → compare fragment
// L I.1 o 5               → parallel literary text
```

---

## Complete Examples

### Standard Letter

```
@tablet
@obverse
1. a-na {m}ARAD-{d}IŠKUR
2. qí-bi-ma
3. um-ma {d}UTU-ŠEŠ-ma
4. lu šul-mu a-na a-ḫi-ia
5. {d}UTU u {d}AMAR.UTU
6. li-ba-al-li-ṭu-ka
$ single ruling
7. aš-šum GU₄.ḪI.A
8. ša ta-aš-pu-ra-am
9. GU₄.ḪI.A ul i-ba-aš-ši
$ rest of obverse blank

@reverse
$ beginning of reverse broken
1'. [...] x x [...]
2'. a-na pa-ni-ka
3'. lu-uš-pu-ra-am
$ double ruling
4'. ITI ŠU MU 10 KAM
```

### Damaged Tablet with Erasures

```
@tablet
@obverse
1. a#-na# [be-li₂]-ia#
2. qí-bi#-[ma]
3. um-ma °LUGAL\{m}ARAD°-{d}30-ma
   → LUGAL erased, replaced with personal name
4. [...] x x x [...]
5. aš#-šum# <<GU₄.ḪI.A>> UDU.ḪI.A
   → GU₄.ḪI.A removed, UDU.ḪI.A written
$ 2-3 lines broken
8'. ša ta-aš-pu-<ra>-am
   → scribe omitted "ra"
```

### Lexical List

```
@tablet
@obverse
@column 1
1. AN : {d}a-nu-um
2. AN : {d}an-tum
3. AN : šá-mu-ú
$ single ruling
4. KI : er-ṣe-tum
5. KI : {ki}aš-ru
$ rest of column blank

@column 2
$ beginning of column missing
1'. [...] : ṭe₄-e-mu
2'. KA : pu-ú
```

---

## Quick Reference Table

### Damage & Uncertainty

| Notation | Meaning |
|----------|---------|
| `#` | Damaged sign |
| `?` | Uncertain reading |
| `!` | Correction |
| `*` | Collated |

### Brackets

| Notation | Meaning |
|----------|---------|
| `[...]` | Broken away |
| `(...)` | Perhaps broken |
| `<...>` | Accidental omission |
| `<(...)>` | Intentional omission |
| `<<...>>` | Deliberate removal |
| `°...\...°` | Erasure |

### Signs

| Notation | Meaning |
|----------|---------|
| `x` | Unclear sign |
| `X` | Unidentified sign |
| `...` | Unknown number of signs |
| `₂` | Subscript index |

### Glosses

| Notation | Meaning |
|----------|---------|
| `{...}` | Determinative |
| `{+...}` | Phonetic gloss |
| `{{...}}` | Linguistic gloss |

### Structure

| Notation | Meaning |
|----------|---------|
| `@...` | Structure line |
| `$...` | State line |
| `#note:` | Note |
| `#tr.XX:` | Translation |
| `//` | Parallel |

### Common Determinatives

| Det. | Meaning |
|------|---------|
| `{d}` | Divine |
| `{m}` | Male name |
| `{f}` | Female name |
| `{ki}` | Place |
| `{lú}` | Person |
| `{giš}` | Wood |
| `{urudu}` | Copper |

---

## Validation

eBL validates ATF at two levels:

1. **Syntax validation** - Grammar rules (done locally by BEn)
2. **Sign database validation** - Valid sign names (done by eBL API on export)

All readings and signs must be correct according to the eBL sign list when exporting to eBL.

---

*This guide is based on the [official eBL-ATF specification](https://github.com/ElectronicBabylonianLiterature/ebl-api/blob/master/docs/ebl-atf.md) and eBL Lark grammar files.*

**Sources:**
- [eBL API Repository](https://github.com/ElectronicBabylonianLiterature/ebl-api)
- [eBL ATF Documentation](https://github.com/ElectronicBabylonianLiterature/ebl-api/blob/master/docs/ebl-atf.md)
- [Oracc ATF Primer](http://oracc.museum.upenn.edu/doc/help/editinginatf/primer/index.html)
