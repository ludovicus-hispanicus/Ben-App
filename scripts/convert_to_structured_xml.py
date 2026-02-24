"""
Convert YOLO + DeepSeek OCR results to structured XML with semantic markup.
Parses dictionary entry components: headword, language markers, references, etc.
"""
import sys
import os
import io
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# Language/period abbreviations in Assyriological dictionaries
LANGUAGE_MARKERS = {
    'aA': 'alt-Assyrisch',
    'aAK': 'alt-Akkadisch',
    'aB': 'alt-Babylonisch',
    'mA': 'mittel-Assyrisch',
    'mB': 'mittel-Babylonisch',
    'jB': 'jung-Babylonisch',
    'nA': 'neu-Assyrisch',
    'nB': 'neu-Babylonisch',
    'spB': 'spät-Babylonisch',
    'Am.': 'Amarna',
    'Ug.': 'Ugarit',
}

# Common reference abbreviations
REFERENCE_PATTERN = r'\b(ABL|CT|VAB|AfO|AKA|BWL|CAD|MSL|ARM|YOS|RA|Or\.|Sn\.|Ash\.|Gilg\.|KAR|LKA|PRT|AGH|STT|UET|ZA|ASKT|LTBA|MCT|RMA|ADD|Iraq|Tigl\.|Anp\.|AOB|TuL|AOTU|AOTAT|ArOr|Maqlu|EL|Ugar\.|ACh\.|LSS|ITn|Tn|Sg\.|WO|AGS|CCT|MAD|ER|AOS)\s*\.?\s*[\d\w,\.\s;:\-\[\]]+?(?=\s*[;.]|\s*[a-z]{2}B|\s*$)'


def clean_ocr_text(text):
    """Clean OCR artifacts from text."""
    text = text.replace("NO PATCHES\n", "").replace("NO PATCHES", "")
    text = re.sub(r'<\|/?ref\|>', '', text)
    text = re.sub(r'<\|det\|>\[\[.*?\]\]<\|/det\|>', '', text)
    text = re.sub(r'\\\[.*?\\\]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_headword(text):
    """Try to extract the headword from entry text."""
    lines = text.strip().split('\n')
    if not lines:
        return None, text

    first_line = lines[0].strip()

    # Look for patterns like "qablu" or "qa-ab-lu" at start
    # Headwords often start with Akkadian syllabic writing
    headword_patterns = [
        r'^([a-zšṣṭāēīūâêîû][a-zšṣṭāēīūâêîû\-]+)',  # Simple word
        r'^([A-Z][a-zšṣṭāēīūâêîû\-\.]+)',  # Capitalized
        r'^(q\.\s*[a-zšṣṭāēīūâêîû]+)',  # q. abbreviation pattern
    ]

    for pattern in headword_patterns:
        match = re.match(pattern, first_line, re.IGNORECASE)
        if match:
            return match.group(1), text

    return None, text


def extract_language_markers(text):
    """Extract language/period markers from text."""
    markers = []
    for abbr, full_name in LANGUAGE_MARKERS.items():
        # Look for the abbreviation as a word boundary
        pattern = r'\b' + re.escape(abbr) + r'\b'
        if re.search(pattern, text):
            markers.append({'abbr': abbr, 'name': full_name})
    return markers


def extract_references(text):
    """Extract bibliographic references from text."""
    references = []

    # Pattern for common reference formats
    patterns = [
        r'(ABL\s*\d+[\w\s,\.\-]*)',
        r'(CT\s*\d+[\w\s,\.\-]*)',
        r'(VAB\s*\d+[\w\s,\.\-]*)',
        r'(AfO\s*\d+[\w\s,\.\-]*)',
        r'(MSL\s*\d+[\w\s,\.\-/]*)',
        r'(ARM\s*\d+[\w\s,\.\-]*)',
        r'(YOS\s*\d+[\w\s,\.\-]*)',
        r'(RA\s*\d+[\w\s,\.\-]*)',
        r'(BWL\s*\d+[\w\s,\.\-]*)',
        r'(Gilg\.\s*[IVXL\d]+[\w\s,\.\-]*)',
        r'(KAR\s*\d+[\w\s,\.\-]*)',
        r'(LKA\s*\d+[\w\s,\.\-]*)',
        r'(Iraq\s*\d+[\w\s,\.\-:]*)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            ref = match.strip().rstrip(',;.')
            if ref and len(ref) > 3:
                references.append(ref)

    return list(set(references))[:20]  # Limit and dedupe


def extract_meanings(text):
    """Extract meanings/translations (often in parentheses or after colons)."""
    meanings = []

    # Look for parenthetical translations
    paren_pattern = r'\(([^)]+)\)'
    matches = re.findall(paren_pattern, text)
    for match in matches:
        # Filter out references and keep translations
        if not re.match(r'^[A-Z]{2,}', match) and len(match) > 2:
            if any(c.isalpha() for c in match):
                meanings.append(match)

    return meanings[:10]  # Limit


def parse_results_file(filepath):
    """Parse the deepseek_snippets_output.txt file."""
    entries = []
    current_entry = None

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if line.startswith('=== ') and line.endswith(' ==='):
            if current_entry:
                entries.append(current_entry)
            filename = line[4:-4]
            current_entry = {
                'filename': filename,
                'size': '',
                'time': '',
                'text': []
            }
            i += 1
            continue

        if current_entry and line.startswith('Size: '):
            current_entry['size'] = line[6:]
            i += 1
            continue

        if current_entry and line.startswith('Time: '):
            current_entry['time'] = line[6:]
            i += 1
            continue

        if line.startswith('DeepSeek OCR Results') or line.startswith('Total ') or line.startswith('==='):
            i += 1
            continue

        if current_entry:
            current_entry['text'].append(line)

        i += 1

    if current_entry:
        entries.append(current_entry)

    return entries


def create_structured_xml(entries, source_image="page_3.png"):
    """Create structured XML with semantic markup."""
    root = ET.Element('dictionary')
    root.set('xmlns', 'http://example.org/assyrian-dictionary')
    root.set('source', source_image)

    # Page element
    page = ET.SubElement(root, 'page')
    page.set('number', '888')  # From the image
    page.set('total_entries', str(len(entries)))

    for i, entry in enumerate(entries):
        parts = entry['filename'].replace('.png', '').split('_')
        entry_num = parts[0] if parts else str(i + 1)
        entry_type = parts[1] if len(parts) > 1 else 'entry'
        confidence = parts[2] if len(parts) > 2 else '0.00'

        # Clean text
        raw_text = '\n'.join(entry['text'])
        cleaned_text = clean_ocr_text(raw_text)

        if not cleaned_text or cleaned_text == "Output the text exactly as shown.":
            continue

        # Create entry element
        entry_elem = ET.SubElement(page, 'entry')
        entry_elem.set('id', f"entry_{entry_num}")
        entry_elem.set('type', entry_type)
        entry_elem.set('detection_confidence', confidence)

        # Extract and add headword
        headword, _ = extract_headword(cleaned_text)
        if headword:
            hw_elem = ET.SubElement(entry_elem, 'headword')
            hw_elem.text = headword

        # Extract language markers
        lang_markers = extract_language_markers(cleaned_text)
        if lang_markers:
            langs_elem = ET.SubElement(entry_elem, 'languages')
            for marker in lang_markers:
                lang = ET.SubElement(langs_elem, 'language')
                lang.set('abbr', marker['abbr'])
                lang.set('name', marker['name'])

        # Extract meanings
        meanings = extract_meanings(cleaned_text)
        if meanings:
            meanings_elem = ET.SubElement(entry_elem, 'meanings')
            for meaning in meanings:
                m = ET.SubElement(meanings_elem, 'meaning')
                m.text = meaning

        # Extract references
        refs = extract_references(cleaned_text)
        if refs:
            refs_elem = ET.SubElement(entry_elem, 'references')
            for ref in refs:
                r = ET.SubElement(refs_elem, 'ref')
                r.text = ref

        # Full text content
        content = ET.SubElement(entry_elem, 'content')
        content.text = cleaned_text

        # Metadata
        meta = ET.SubElement(entry_elem, 'ocr_metadata')
        ET.SubElement(meta, 'source_snippet').text = entry['filename']
        ET.SubElement(meta, 'snippet_size').text = entry['size']
        ET.SubElement(meta, 'processing_time').text = entry['time']

    return root


def prettify_xml(elem):
    """Return a pretty-printed XML string."""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def main():
    input_file = "deepseek_snippets_output.txt"
    output_file = "dictionary_structured.xml"

    if not os.path.exists(input_file):
        print(f"Input file not found: {input_file}")
        return

    print("=" * 60)
    print("Converting to Structured XML")
    print("=" * 60)
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print()

    # Parse results
    print("Parsing OCR results...")
    entries = parse_results_file(input_file)
    print(f"Found {len(entries)} entries")

    # Create structured XML
    print("Creating structured XML...")
    root = create_structured_xml(entries)

    # Write XML file
    xml_string = prettify_xml(root)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(xml_string)

    print(f"XML saved to: {output_file}")
    print()

    # Show sample
    print("=" * 60)
    print("Sample XML (first entry):")
    print("=" * 60)
    # Find first entry in output
    lines = xml_string.split('\n')
    in_entry = False
    entry_lines = []
    for line in lines:
        if '<entry ' in line:
            in_entry = True
        if in_entry:
            entry_lines.append(line)
        if '</entry>' in line and in_entry:
            break

    print('\n'.join(entry_lines[:50]))
    if len(entry_lines) > 50:
        print("...")


if __name__ == "__main__":
    main()
