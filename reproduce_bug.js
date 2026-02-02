
const vowelMap = {
    'á': { base: 'a', idx: '₂' }, 'é': { base: 'e', idx: '₂' }, 'í': { base: 'i', idx: '₂' }, 'ú': { base: 'u', idx: '₂' },
    'Á': { base: 'A', idx: '₂' }, 'É': { base: 'E', idx: '₂' }, 'Í': { base: 'I', idx: '₂' }, 'Ú': { base: 'U', idx: '₂' },
    'à': { base: 'a', idx: '₃' }, 'è': { base: 'e', idx: '₃' }, 'ì': { base: 'i', idx: '₃' }, 'ù': { base: 'u', idx: '₃' },
    'À': { base: 'A', idx: '₃' }, 'È': { base: 'E', idx: '₃' }, 'Ì': { base: 'I', idx: '₃' }, 'Ù': { base: 'U', idx: '₃' }
};

function toAtf(text) {
    if (!text) return '';
    // Fix: Normalize
    text = text.normalize('NFC');

    // Legacy conversion (current logic)
    text = text.replace(/([a-zšṣṭhʾA-ZŠṢṬHʾ]*)([áéíúàèìùÁÉÍÚÀÈÌÙ])([a-zšṣṭhʾA-ZŠṢṬHʾ]*)/g, (match, pre, vowel, post) => {
        const mapping = vowelMap[vowel];
        if (mapping) {
            return pre + mapping.base + post + mapping.idx;
        }
        return match;
    });

    return text;
}

const cases = [
    "ú-ka-am", // Likely NFC
    "ú-ka-am-x",
    "ki-ṣa-a-li-šu",
    "ga-al-ta",
    "pa-a[š-ra]",
    "ni-ši-i-ni-šu",
    "ú",
    "ú".normalize('NFD') + "-ka-am" // Force NFD case which failed before
];

console.log("--- REPRODUCTION TEST ---");
cases.forEach(c => {
    console.log(`Input: ${c} => Output: ${toAtf(c)}`);
});
