
const lines = [
    "18'. AŠ a-wi-lum ka-ap-pi i-ni-šu ik-bi-ru-ú-ma",
    "19'. ù i-na-šu di-im-tam i-na-an-di-a ši-bi-iṭ-⸢ša-ri-im⸣",
    "20'. AŠ a-wi-lum pa-ga-ar-šu ka-ṣi-i-ma re-eš li-i[b-bi-šu]]",
    "21'. ⸢i-la⸣-ak imât(ug₇.e) ù iballuṭ(ṭi.la)",
    "22'. AŠ [a-wi]-lum ap-pa-at ⸢uz⸣-<ni->-šu ik-ta-na-ṣa-a mu-⸢ru-us⸣-[ṣú] / i-ri-ik",
    "23'. ud.6.kam ⸢ud⸣.7.kam mu-ru-us-sú / ⸢i-il⸣-la-a[k]",
    "24'. [AŠ a-wi-lum qá]-aq-qá-⸢as-sú⸣ ù pa-ga-ar-šu [mi-it-ḫa-ri-iš?]",
    "25'. i[k-t]a-na-aṣ-ṣa-[a] ṣibit(⸢ì⸣.dab) {d}māšī(maš.tab.[bal])",
    "26'. AŠ a-⸢wi⸣-lum še-er-⸢ḫa-an i⸣-ir-ti-šu ṭe-b[u-ú-ma]",
    "27'. ù ⸢tu⸣-qá-ar-mu-⸢uḫ-ḫi-šu⸣ ka-ṣi n[a-ḫi-id? (or ⸢i⸣.[dab DN?)]",
    "28'. AŠ ma-⸢ar⸣-ṣú pa-ri-id-⸢ma ù⸣ it-te-[x x x] / ṣibit(ì.⸢dab⸣) li-l[i-i-im]",
    "29'. AŠ ma-ar-⸢ṣú⸣ zu-mu-ur-šu i-mi-im-[ma i-ka-ṣi?] / ù ṣi-⸢bi⸣-is-sú it-[t]a-na-ki-ir ṣibti(ì-⸢dab⸣) ⸢{d}[šama]š([ut]u)",
    "30'. AŠ ma-ar-ṣú keq-li ⸢1⸣-ni-inl tun-Dli-liš-rrla",
    "31'. iš-tu qí-id-da-at u₄-mi-im ka-li mu-ši-im ma-ru-/-uṣ / ṣibiṭ(⸢ì⸣.dab) eṭemmim(gidim.ma)",
    "32'. AŠ ⸢ma⸣-ar-ṣú zu-mu-ur-šu mi-it-ḫa-ri-iš e-em",
    "33'. ⸢uq⸣-qú-uq i-na zu-um-ri-šu qá-tum la i-ba-aš-ši",
    "34'. ḫi-mi-⸢iṭ se-e⸣-tim",
    "35'. AŠ ⸢a⸣-wi-lim še-er-ḫa-an na-⸢ak⸣-ka-ap-ti-šu ša i-mi-tim",
    "36'. ṭe-bu-ú ša šu-me-lim ⸢ṭa⸣-a-ku ù re-eš li-ib-bi-šu",
    "37'. na-p[i-i]ḫ ṣibit(ì.dab) ḫa-wi-i-tum",
    "38'. AŠ ma-ar-ṣú ku-nu-uk ki-ša-di-i-šu pa-ṭe-er",
    "39'. še-er-ḫa-nu-šu ta-a-ku na-ḫi-ra-šu it-ta-na-aṣ-ba-⸢ta⸣ / na-ḫi-id",
    "40'. AŠ ⸢ma⸣-ar-ṣú i-na-šu da-ma-am! BI-ma-am ma-li-a",
    "41'. [i-in]-šu ṣa-pi-ir ù ṣi-ib-tu-šu ta-a-ku",
    "42'. [ú-u]l i-ba-al-lu-uṭ"
];

let content = "&P123456 = CuReD Export\n#project: ebl\n#atf: lang akk\n#atf: use unicode\n@tablet\n@obverse\n";

lines.forEach((line, index) => {
    let text = line;

    // 1. Sign Extraction: reading(signs) -> SIGNS
    // Example: iballuṭ(ṭi.la) -> ṬI.LA
    text = text.replace(/[a-zšṣṭḫʾA-ZŠṢṬḪāēīūâêîûĀĒĪŪÂÊÎÛ]+?\(([^)]+)\)/g, (match, signContent) => {
        return signContent.toUpperCase();
    });

    // 2. ḫ -> h
    text = text.replace(/ḫ/g, 'h');
    text = text.replace(/Ḫ/g, 'H');

    // 3. Accent Normalization
    // accute (´) -> subscript 2
    // grave (`) -> subscript 3
    // á->a₂, é->e₂, í->i₂, ú->u₂
    // à->a₃, è->e₃, ì->i₃, ù->u₃
    // pattern: find word-parts containing these vowels.
    // We iterate over the string finding words with accents.
    // Regex for a "segment" of letters allowing accents.
    // Including h, š, ṣ, ṭ, ʾ, and base vowels.
    // NOTE: We already replaced ḫ->h.

    const vowelMap = {
        'á': { base: 'a', idx: '₂' },
        'é': { base: 'e', idx: '₂' },
        'í': { base: 'i', idx: '₂' },
        'ú': { base: 'u', idx: '₂' },
        'Á': { base: 'A', idx: '₂' }, // Just in case, though usually lowercase
        'É': { base: 'E', idx: '₂' },
        'Í': { base: 'I', idx: '₂' },
        'Ú': { base: 'U', idx: '₂' },

        'à': { base: 'a', idx: '₃' },
        'è': { base: 'e', idx: '₃' },
        'ì': { base: 'i', idx: '₃' },
        'ù': { base: 'u', idx: '₃' },
        'À': { base: 'A', idx: '₃' },
        'È': { base: 'E', idx: '₃' },
        'Ì': { base: 'I', idx: '₃' },
        'Ù': { base: 'U', idx: '₃' }
    };

    // Regex to capture a sequence of chars that includes at least one accented char
    // We search for tokens.
    // More precise: replace specific characters but append index to the end of the logical sign/segment?
    // "pàd" -> "pad₃".
    // If we simply replace à->a₃ we get "pa₃d".
    // We need to capture the whole segment [p][à][d].

    // Pattern: 
    // [consonants/vowels]* [accented_vowel] [consonants/vowels]*
    // We must ensure we don't overlap.
    // simple greedy match for a syllable?
    // ([a-zšṣṭhʾ]*)([áéíúàèìù])([a-zšṣṭhʾ]*)

    text = text.replace(/([a-zšṣṭhʾA-ZŠṢṬHʾ]*)([áéíúàèìùÁÉÍÚÀÈÌÙ])([a-zšṣṭhʾA-ZŠṢṬHʾ]*)/g, (match, pre, vowel, post) => {
        const mapping = vowelMap[vowel];
        if (mapping) {
            return pre + mapping.base + post + mapping.idx;
        }
        return match;
    });

    // 4. Damage Marker Conversion: ⸢...⸣ -> ...#
    // Example: ⸢sign sign2⸣ -> sign# sign2#
    text = text.replace(/⸢(.*?)⸣/g, (match, content) => {
        // Apply # to each part separated by space, dot, hyphen
        // But replicate the logic: return content.replace(/([^\s\-\.]+)/g, "$1#");
        return content.replace(/([^\s\-\.]+)/g, "$1#");
    });

    // Remove leftover half-brackets
    text = text.replace(/[⸢⸣]/g, "");

    // Ensure line numbering
    if (!/^\d+\.?\s+/.test(text) && !/^\d+\.'\s*/.test(text) && !/^\d+'\.?\s*/.test(text)) {
        content += `${index + 1}. ${text}\n`;
    } else {
        content += `${text}\n`;
    }
});

const fs = require('fs');
fs.writeFileSync('verify_output_utf8.txt', content, 'utf8');
console.log("Written to verify_output_utf8.txt");
