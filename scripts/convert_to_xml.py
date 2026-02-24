"""
Convert YOLO + DeepSeek OCR results to XML format.
"""
import sys
import os
import io
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def clean_ocr_text(text):
    """Clean OCR artifacts from text."""
    # Remove "NO PATCHES" artifact
    text = text.replace("NO PATCHES\n", "").replace("NO PATCHES", "")

    # Remove detection markers like <|ref|>, <|/ref|>, <|det|>[[...]]<|/det|>
    text = re.sub(r'<\|/?ref\|>', '', text)
    text = re.sub(r'<\|det\|>\[\[.*?\]\]<\|/det\|>', '', text)

    # Remove LaTeX-like artifacts
    text = re.sub(r'\\\[.*?\\\]', '', text)

    # Clean up multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def parse_results_file(filepath):
    """Parse the deepseek_snippets_output.txt file."""
    entries = []
    current_entry = None

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Check for entry header
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

        # Parse size
        if current_entry and line.startswith('Size: '):
            current_entry['size'] = line[6:]
            i += 1
            continue

        # Parse time
        if current_entry and line.startswith('Time: '):
            current_entry['time'] = line[6:]
            i += 1
            continue

        # Skip header lines
        if line.startswith('DeepSeek OCR Results') or line.startswith('Total ') or line.startswith('==='):
            i += 1
            continue

        # Collect text content
        if current_entry:
            current_entry['text'].append(line)

        i += 1

    # Don't forget last entry
    if current_entry:
        entries.append(current_entry)

    return entries


def create_xml(entries, source_image="page_3.png"):
    """Create XML from parsed entries."""
    # Root element
    root = ET.Element('dictionary_page')
    root.set('source', source_image)
    root.set('entries', str(len(entries)))

    for i, entry in enumerate(entries):
        # Parse entry info from filename
        # Format: 05_entry_1.00.png
        parts = entry['filename'].replace('.png', '').split('_')
        entry_num = parts[0] if parts else str(i + 1)
        entry_type = parts[1] if len(parts) > 1 else 'entry'
        confidence = parts[2] if len(parts) > 2 else '0.00'

        # Create entry element
        entry_elem = ET.SubElement(root, 'entry')
        entry_elem.set('id', entry_num)
        entry_elem.set('type', entry_type)
        entry_elem.set('confidence', confidence)

        # Add metadata
        meta = ET.SubElement(entry_elem, 'metadata')
        ET.SubElement(meta, 'source_file').text = entry['filename']
        ET.SubElement(meta, 'size').text = entry['size']
        ET.SubElement(meta, 'ocr_time').text = entry['time']

        # Clean and add text content
        raw_text = '\n'.join(entry['text'])
        cleaned_text = clean_ocr_text(raw_text)

        text_elem = ET.SubElement(entry_elem, 'text')
        text_elem.text = cleaned_text

    return root


def prettify_xml(elem):
    """Return a pretty-printed XML string."""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def main():
    input_file = "deepseek_snippets_output.txt"
    output_file = "dictionary_entries.xml"

    if not os.path.exists(input_file):
        print(f"Input file not found: {input_file}")
        return

    print("=" * 60)
    print("Converting OCR results to XML")
    print("=" * 60)
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print()

    # Parse results
    print("Parsing OCR results...")
    entries = parse_results_file(input_file)
    print(f"Found {len(entries)} entries")

    # Create XML
    print("Creating XML...")
    root = create_xml(entries)

    # Write XML file
    xml_string = prettify_xml(root)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(xml_string)

    print(f"XML saved to: {output_file}")
    print()

    # Show sample
    print("=" * 60)
    print("Sample XML output (first 2000 chars):")
    print("=" * 60)
    print(xml_string[:2000])
    if len(xml_string) > 2000:
        print("...")


if __name__ == "__main__":
    main()
