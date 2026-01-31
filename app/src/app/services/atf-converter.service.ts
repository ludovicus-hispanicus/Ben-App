
import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class AtfConverterService {

    constructor() { }

    // Converts Raw/CuReD format to EBL-ATF format (Editable View)
    toAtf(text: string): string {
        if (!text) return '';
        text = text.normalize('NFC');

        // 1. Sign Extraction: reading(signs) -> SIGNS @reading{reading}
        // Save the reading to allow reversing
        text = text.replace(/([a-zšṣṭḫʾA-ZŠṢṬḪāēīūâêîûĀĒĪŪÂÊÎÛ]+?)\(([^)]+)\)/g, (match, reading, signContent) => {
            return `${signContent.toUpperCase()} @reading{${reading}}`;
        });

        // 2. ḫ -> h / Ḫ -> H
        text = text.replace(/ḫ/g, 'h');
        text = text.replace(/Ḫ/g, 'H');

        // 3. Accent Normalization (Accents -> Indices)
        const vowelMap = {
            'á': { base: 'a', idx: '₂' }, 'é': { base: 'e', idx: '₂' }, 'í': { base: 'i', idx: '₂' }, 'ú': { base: 'u', idx: '₂' },
            'Á': { base: 'A', idx: '₂' }, 'É': { base: 'E', idx: '₂' }, 'Í': { base: 'I', idx: '₂' }, 'Ú': { base: 'U', idx: '₂' },
            'à': { base: 'a', idx: '₃' }, 'è': { base: 'e', idx: '₃' }, 'ì': { base: 'i', idx: '₃' }, 'ù': { base: 'u', idx: '₃' },
            'À': { base: 'A', idx: '₃' }, 'È': { base: 'E', idx: '₃' }, 'Ì': { base: 'I', idx: '₃' }, 'Ù': { base: 'U', idx: '₃' }
        };

        text = text.replace(/([a-zšṣṭhʾA-ZŠṢṬHʾ]*)([áéíúàèìùÁÉÍÚÀÈÌÙ])([a-zšṣṭhʾA-ZŠṢṬHʾ]*)/g, (match, pre, vowel, post) => {
            const mapping = vowelMap[vowel];
            if (mapping) {
                return pre + mapping.base + post + mapping.idx;
            }
            return match;
        });

        // 4. Damage Marker Conversion: ⸢...⸣ -> ...#
        text = text.replace(/⸢(.*?)⸣/g, (match, content) => {
            return content.replace(/([^\s\-\.]+)/g, "$1#");
        });

        // Remove leftover half-brackets
        text = text.replace(/[⸢⸣]/g, "");

        return text;
    }

    // Converts EBL-ATF format back to Raw/CuReD format
    fromAtf(text: string): string {
        if (!text) return '';
        text = text.normalize('NFC');

        // 1. Restore Readings: SIGNS @reading{reading} -> reading(signs)
        // We match: WORD @reading{...}
        // Note: SIGNS might have damage markers or indices, but usually readings wrap the whole sign set?
        // User example: iballuṭ(ṭi.la) -> ṬI.LA
        // Our toAtf produced: ṬI.LA @reading{iballuṭ}
        text = text.replace(/([^\s]+)\s+@reading\{([^}]+)\}/g, (match, signs, reading) => {
            // signs might be ṬI.LA or ṬI.LA# if damaged in ATF mode?
            // If user edits signs in ATF mode, we keep their edits but wrap with old reading?
            // This is "lossy" regarding the relationship if structure changes significantly.
            // But good enough for toggling.
            return `${reading}(${signs.toLowerCase()})`;
        });

        // 2. Restore Accents (Indices -> Accents)
        // u₂ -> ú, u₃ -> ù
        const indexMap = {
            'a₂': 'á', 'e₂': 'é', 'i₂': 'í', 'u₂': 'ú',
            'A₂': 'Á', 'E₂': 'É', 'I₂': 'Í', 'U₂': 'Ú',
            'a₃': 'à', 'e₃': 'è', 'i₃': 'ì', 'u₃': 'ù',
            'A₃': 'À', 'E₃': 'È', 'I₃': 'Ì', 'U₃': 'Ù'
        };
        // We also need to handle cases like u2 (plain number) if user typed it that way?
        // EBL uses subscript chars usually? #atf: use unicode implies subscripts.

        // Replace unicode subscripts
        // Iterate keys
        for (const [sub, acc] of Object.entries(indexMap)) {
            // escape regex special chars? ₂ is fine.
            const regex = new RegExp(sub, 'g');
            text = text.replace(regex, acc);
        }

        // 3. h -> ḫ? 
        // Logic: h is used in EBL. In CuReD we prefer ḫ.
        // But what if it's a real 'h'? Akkadian uses ḫ usually.
        text = text.replace(/h/g, 'ḫ');
        text = text.replace(/H/g, 'Ḫ');

        // 4. Restore Half-Brackets: ...# -> ⸢...⸣
        // This is tricky. 
        // a# b# -> ⸢a b⸣
        // a# -> ⸢a⸣
        // We can look for sequences of tokens ending in #
        // Token definition: sequences of non-space chars.

        // find consecutive words ending with #
        // regex: ((?:[^\s]+#(?:\s+|$))+)
        text = text.replace(/((?:[^\s]+#(?:\s+|$))+)/g, (match) => {
            // match is sequence like "a# b# c# "
            // clean the #s
            let cleaned = match.replace(/#/g, '');
            // trim trailing space if captured
            cleaned = cleaned.replace(/\s+$/, '');
            // wrap
            return `⸢${cleaned}⸣` + (match.endsWith(' ') ? ' ' : '');
        });

        return text;
    }

    // Cleans the text for final ATF export (removes internal tags)
    cleanForExport(text: string): string {
        if (!text) return '';
        // Remove @reading{...} tags
        return text.replace(/\s+@reading\{[^}]+\}/g, '');
    }
}
