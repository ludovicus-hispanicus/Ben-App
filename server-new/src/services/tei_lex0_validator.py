"""
TEI Lex-0 XML Validator

Validates <entry> elements against the TEI Lex-0 XSD schema + 12 custom
project rules specific to the LAD/AHw dictionary project.

Uses lxml for XSD validation (no external service needed).
"""

import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Paths
SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
XSD_PATH = SCHEMAS_DIR / "lex0.xsd"

# TEI wrapper template for validating standalone <entry> elements
TEI_WRAPPER = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" type="lex-0">
    <teiHeader>
        <fileDesc>
            <titleStmt>
                <title type="full">Akkadisches Handwörterbuch</title>
                <title type="abbr">AHw</title>
            </titleStmt>
            <publicationStmt>
                <publisher><orgName>Sächsische Akademie der Wissenschaften</orgName></publisher>
                <availability><licence target="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</licence></availability>
            </publicationStmt>
        </fileDesc>
        <profileDesc>
            <langUsage>
                <language ident="akk" role="objectLanguage">Akkadian</language>
                <language ident="de" role="workingLanguage">German</language>
                <language ident="sux" role="objectLanguage">Sumerian</language>
            </langUsage>
        </profileDesc>
    </teiHeader>
    <text>
        <body>
            {entry_xml}
        </body>
    </text>
</TEI>"""

# Line offset: the <entry> content starts at this line in the wrapper
_WRAPPER_LINES_BEFORE_ENTRY = TEI_WRAPPER.split("{entry_xml}")[0].count("\n")


class TeiLex0Validator:
    """
    Validates TEI Lex-0 <entry> XML against XSD schema and custom project rules.

    Usage:
        validator = TeiLex0Validator()
        result = validator.validate_entry('<entry xml:id="test" ...>...</entry>')
        # result = {"valid": True/False, "errors": [...]}
    """

    def __init__(self):
        self._schema = None
        self._schema_available = False
        self._load_xsd()

    def _load_xsd(self):
        """Load and parse the XSD schema. Graceful fallback if lxml unavailable."""
        try:
            from lxml import etree

            if not XSD_PATH.exists():
                logger.warning(f"XSD schema not found at {XSD_PATH}")
                return

            schema_doc = etree.parse(str(XSD_PATH))
            self._schema = etree.XMLSchema(schema_doc)
            self._schema_available = True
            logger.info(f"TEI Lex-0 XSD schema loaded from {XSD_PATH}")

        except ImportError:
            logger.warning("lxml not installed — XSD validation disabled. Install with: pip install lxml")
        except Exception as e:
            logger.error(f"Failed to load XSD schema: {e}")

    def validate_entry(self, entry_xml: str) -> Dict[str, Any]:
        """
        Validate a single <entry> element.

        Returns:
            {
                "valid": bool,
                "errors": [{"type": "error"|"warning", "line": int, "column": int|None, "message": str}],
                "validation_source": str
            }
        """
        all_errors: List[Dict[str, Any]] = []

        # XSD validation
        if self._schema_available:
            xsd_errors = self._validate_xsd(entry_xml)
            all_errors.extend(xsd_errors)
        else:
            # At least check well-formedness
            wf_errors = self._check_well_formedness(entry_xml)
            all_errors.extend(wf_errors)

        # Custom project rules
        custom_errors = self._check_custom_rules(entry_xml)
        all_errors.extend(custom_errors)

        error_count = sum(1 for e in all_errors if e["type"] == "error")

        return {
            "valid": error_count == 0,
            "errors": all_errors,
            "validation_source": "xsd+custom" if self._schema_available else "wellformed+custom",
        }

    def _validate_xsd(self, entry_xml: str) -> List[Dict[str, Any]]:
        """Validate entry against XSD schema using lxml."""
        from lxml import etree

        tei_doc = TEI_WRAPPER.format(entry_xml=entry_xml)
        errors = []

        try:
            doc = etree.fromstring(tei_doc.encode("utf-8"))
            is_valid = self._schema.validate(doc)

            if not is_valid:
                for error in self._schema.error_log:
                    # Adjust line number to be relative to the entry
                    entry_line = max(1, error.line - _WRAPPER_LINES_BEFORE_ENTRY)
                    errors.append({
                        "type": "error",
                        "line": entry_line,
                        "column": error.column if error.column > 0 else None,
                        "message": str(error.message),
                    })

        except etree.XMLSyntaxError as e:
            entry_line = max(1, e.lineno - _WRAPPER_LINES_BEFORE_ENTRY) if e.lineno else 1
            errors.append({
                "type": "error",
                "line": entry_line,
                "column": None,
                "message": f"XML syntax error: {e.msg}",
            })

        return errors

    def _check_well_formedness(self, entry_xml: str) -> List[Dict[str, Any]]:
        """Basic well-formedness check when lxml is not available."""
        import xml.etree.ElementTree as ET

        tei_doc = TEI_WRAPPER.format(entry_xml=entry_xml)
        try:
            ET.fromstring(tei_doc)
            return []
        except ET.ParseError as e:
            return [{
                "type": "error",
                "line": 1,
                "column": None,
                "message": f"XML is not well-formed: {e}",
            }]

    def _check_custom_rules(self, xml: str) -> List[Dict[str, Any]]:
        """
        Check 12 custom LAD/AHw project rules.
        These catch patterns the XSD cannot check.
        """
        errors = []
        lines = xml.split("\n")

        # Rule 1: No <ref> inside <bibl>
        for i, line in enumerate(lines):
            if re.search(r"<bibl[^>]*>.*<ref[\s>]", line) or \
               (re.search(r"<bibl", line) and re.search(r"<ref", line)):
                errors.append({
                    "type": "error", "line": i + 1, "column": None,
                    "message": "Do not use <ref> inside <bibl>. Use <bibl source=\"#BIBLIOGRAPHY_ID\">text</bibl> instead.",
                })

        # Rule 2: <bibl> should have source attribute (warning)
        bibl_no_source = re.findall(r"<bibl(?![^>]*source=)[^>]*>", xml)
        if bibl_no_source:
            errors.append({
                "type": "warning", "line": 1, "column": None,
                "message": f"Found {len(bibl_no_source)} <bibl> element(s) without source attribute. Use <bibl source=\"#...\">",
            })

        # Rule 3: Entry must have xml:id
        if not re.search(r"<entry[^>]*xml:id=", xml):
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": "Entry is missing xml:id attribute.",
            })

        # Rule 4: Entry must have xml:lang="akk"
        if not re.search(r'<entry[^>]*xml:lang="akk"', xml):
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": 'Entry is missing xml:lang="akk" attribute.',
            })

        # Rule 5: Must have <form type="lemma">
        if not re.search(r'<form[^>]*type="lemma"', xml):
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": "Entry is missing <form type=\"lemma\">.",
            })

        # Rule 6: Sense xml:id should start with the entry xml:id (warning)
        entry_id_match = re.search(r'xml:id="([^"]+)"', xml)
        entry_id = entry_id_match.group(1) if entry_id_match else None
        sense_ids = re.findall(r'<sense[^>]*xml:id="([^"]+)"', xml)
        for sense_id in sense_ids:
            if entry_id and not sense_id.startswith(entry_id):
                errors.append({
                    "type": "warning", "line": 1, "column": None,
                    "message": f'Sense id "{sense_id}" should start with entry id "{entry_id}".',
                })

        # Rule 7: Stem taxonomy references must use lad_stem_taxonomy.xml (warning)
        bad_stem_refs = re.findall(r'ana="(?!lad_stem_taxonomy\.xml#)[^"]*"', xml)
        for ref in bad_stem_refs:
            if "stem" in ref.lower() or "itype" in ref.lower():
                errors.append({
                    "type": "warning", "line": 1, "column": None,
                    "message": f"Stem reference {ref} should use lad_stem_taxonomy.xml#ID format.",
                })

        # Rule 8: No period ana on <cit> — use <usg type="temporal"> instead
        cit_period_ana = re.findall(
            r'<cit[^>]*ana="[^"]*lad_period_taxonomy\.xml[^"]*"[^>]*>', xml
        )
        if cit_period_ana:
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": f"Found {len(cit_period_ana)} <cit> with period in ana attribute. "
                           f"Use <usg type=\"temporal\" corresp=\"...\"> as a child element instead.",
            })

        # Rule 9: No <mentioned> inside <etym>
        if re.search(r"<etym[^>]*>[\s\S]*?<mentioned[\s>]", xml):
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": "Do not use <mentioned> inside <etym>. Use <seg xml:lang=\"LANG_CODE\">cognate</seg> instead.",
            })

        # Rule 10: No <hi> as direct child of <cit>
        cit_blocks = re.findall(r"<cit[^>]*>[\s\S]*?</cit>", xml)
        for block in cit_blocks:
            without_quotes = re.sub(r"<quote[^>]*>[\s\S]*?</quote>", "", block)
            without_notes = re.sub(r"<note[^>]*>[\s\S]*?</note>", "", without_quotes)
            if re.search(r"<hi[\s>]", without_notes):
                errors.append({
                    "type": "error", "line": 1, "column": None,
                    "message": "<hi> cannot be a direct child of <cit>. Place it inside <quote> or use <seg> or <lbl> instead.",
                })
                break

        # Rule 11: No <supplied> inside <quote>
        if re.search(r"<quote[^>]*>[\s\S]*?<supplied[\s>]", xml):
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": "Do not use <supplied> inside <quote>. Use square brackets in plain text instead, e.g. [an]a.",
            })

        # Rule 12: No <note> inside <quote>
        if re.search(r"<quote[^>]*>[\s\S]*?<note[\s>]", xml):
            errors.append({
                "type": "error", "line": 1, "column": None,
                "message": "Do not use <note> inside <quote>. Place <note> as a sibling after <quote> inside <cit>.",
            })

        return errors

    def is_available(self) -> bool:
        """Check if XSD validation is available."""
        return self._schema_available


# Global singleton
tei_lex0_validator = TeiLex0Validator()
