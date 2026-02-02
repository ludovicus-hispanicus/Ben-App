
const vowelMap = {
    'á': { base: 'a', idx: '₂' }, 'é': { base: 'e', idx: '₂' }, 'í': { base: 'i', idx: '₂' }, 'ú': { base: 'u', idx: '₂' },
    'Á': { base: 'A', idx: '₂' }, 'É': { base: 'E', idx: '₂' }, 'Í': { base: 'I', idx: '₂' }, 'Ú': { base: 'U', idx: '₂' },
    'à': { base: 'a', idx: '₃' }, 'è': { base: 'e', idx: '₃' }, 'ì': { base: 'i', idx: '₃' }, 'ù': { base: 'u', idx: '₃' },
    'À': { base: 'A', idx: '₃' }, 'È': { base: 'E', idx: '₃' }, 'Ì': { base: 'I', idx: '₃' }, 'Ù': { base: 'U', idx: '₃' }
};

const indexMap = {
    'a₂': 'á', 'e₂': 'é', 'i₂': 'í', 'u₂': 'ú',
    'A₂': 'Á', 'E₂': 'É', 'I₂': 'Í', 'U₂': 'Ú',
    'a₃': 'à', 'e₃': 'è', 'i₃': 'ì', 'u₃': 'ù',
    'A₃': 'À', 'E₃': 'È', 'I₃': 'Ì', 'U₃': 'Ù'
};

function toAtf(text) {
    if (!text) return '';

    // 1. Sign Extraction: reading(signs) -> SIGNS @reading{reading}
    text = text.replace(/([a-zšṣṭḫʾA-ZŠṢṬḪāēīūâêîûĀĒĪŪÂÊÎÛ]+?)\(([^)]+)\)/g, (match, reading, signContent) => {
        return `${signContent.toUpperCase()} @reading{${reading}}`;
    });

    // 2. ḫ -> h / Ḫ -> H
    text = text.replace(/ḫ/g, 'h');
    text = text.replace(/Ḫ/g, 'H');

    // 3. Accent Normalization
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

    text = text.replace(/[⸢⸣]/g, "");
    return text;
}

function fromAtf(text) {
    if (!text) return '';

    // 1. Restore Readings: SIGNS @reading{reading} -> reading(signs)
    text = text.replace(/([^\s]+)\s+@reading\{([^}]+)\}/g, (match, signs, reading) => {
        return `${reading}(${signs.toLowerCase()})`;
    });

    // 2. Restore Accents (Indices -> Accents)
    for (const [sub, acc] of Object.entries(indexMap)) {
        const regex = new RegExp(sub, 'g');
        text = text.replace(regex, acc);
    }

    // 3. h -> ḫ?
    text = text.replace(/h/g, 'ḫ');
    text = text.replace(/H/g, 'Ḫ');

    // 4. Restore Half-Brackets: ...# -> ⸢...⸣
    text = text.replace(/((?:[^\s]+#(?:\s+|$))+)/g, (match) => {
        let cleaned = match.replace(/#/g, '');
        cleaned = cleaned.replace(/\s+$/, '');
        return `⸢${cleaned}⸣` + (match.endsWith(' ') ? ' ' : '');
    });

    return text;
}

// Tests
const tests = [
    { name: "Complex Reading", input: "iballuṭ(ṭi.la)" },
    { name: "Damaged Signs", input: "⸢sign sign2⸣" },
    { name: "Mixed", input: "iballuṭ(ṭi.la) ⸢sz⸣" },
    { name: "Accents", input: "ú ù" },
    { name: "H replacement", input: "ḫa-wi-i-tum" }
];

console.log("--- START TESTS ---");
tests.forEach(test => {
    const atf = toAtf(test.input);
    const reversed = fromAtf(atf);
    console.log(`\nTest: ${test.name}`);
    console.log(`Input:    ${test.input}`);
    console.log(`ATF:      ${atf}`);
    console.log(`Reversed: ${reversed}`);
    const success = test.input === reversed || reversed.trim() === test.input; // lax trim check
    console.log(`Success:  ${success ? 'YES' : 'NO'}`);
});
console.log("--- END TESTS ---");
