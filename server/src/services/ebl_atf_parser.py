"""
eBL-ATF Parser Service

Uses Lark to parse and validate ATF text according to the eBL-ATF specification.
This provides local validation without needing the eBL API connection.

Grammar files are from: https://github.com/ElectronicBabylonianLiterature/transliterated-fragments

Note: This parser validates syntax but does NOT verify signs against a sign database.
For full validation including sign verification, use the eBL API.
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, TypedDict


class ValidationError(TypedDict, total=False):
    """Structured validation error with position info."""
    line: int       # 1-based line number
    column: int     # 1-based column number (optional)
    message: str    # Error message

try:
    from lark import Lark, UnexpectedInput, UnexpectedCharacters, UnexpectedToken
    from lark.exceptions import LarkError
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    logging.warning("lark-parser not installed. Local eBL-ATF validation will use basic syntax checking.")


class EblAtfParser:
    """Parser for eBL-ATF format using Lark grammar."""

    # Path to grammar files
    GRAMMAR_DIR = Path(__file__).parent.parent / "ebl_atf_grammar"

    def __init__(self):
        self._parser: Optional[Lark] = None
        self._initialization_error: Optional[str] = None

        if LARK_AVAILABLE:
            self._initialize_parser()

    def _initialize_parser(self):
        """Initialize the Lark parser with eBL-ATF grammar."""
        try:
            grammar_file = self.GRAMMAR_DIR / "ebl_atf.lark"

            if not grammar_file.exists():
                self._initialization_error = f"Grammar file not found: {grammar_file}"
                logging.error(self._initialization_error)
                return

            # Read the main grammar
            with open(grammar_file, 'r', encoding='utf-8') as f:
                grammar = f.read()

            # Create parser with import path set to grammar directory
            # Use Earley parser - the eBL grammar has ambiguities that LALR can't handle
            self._parser = Lark(
                grammar,
                parser='earley',
                import_paths=[str(self.GRAMMAR_DIR)],
                propagate_positions=True
            )

            logging.info("eBL-ATF Lark parser initialized successfully")

        except Exception as e:
            self._initialization_error = f"Failed to initialize parser: {str(e)}"
            logging.error(self._initialization_error)

    @property
    def is_available(self) -> bool:
        """Check if the parser is available."""
        return self._parser is not None

    def parse_line(self, line: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Parse a single line of ATF text.

        Returns:
            Tuple of (success, error_message, column)
            column is 1-based if available, None otherwise
        """
        if not self._parser:
            return True, None, None  # Can't validate without parser

        line = line.strip()
        if not line:
            return True, None, None

        try:
            self._parser.parse(line)
            return True, None, None
        except UnexpectedCharacters as e:
            return False, f"Unexpected character '{e.char}'", e.column
        except UnexpectedToken as e:
            expected = ', '.join(e.expected) if e.expected else 'unknown'
            return False, f"Unexpected token. Expected: {expected}", e.column
        except UnexpectedInput as e:
            col = getattr(e, 'column', None)
            return False, "Parse error", col
        except LarkError as e:
            return False, str(e), None
        except Exception as e:
            return False, f"Parse error: {str(e)}", None

    def validate(self, atf_text: str) -> Dict[str, Any]:
        """
        Validate ATF text.

        Returns dict with:
        - valid: bool
        - errors: list of structured error objects {line, column, message}
        - error_strings: list of error strings (for display)
        - warnings: list of warning messages
        - parsed_lines: number of lines parsed
        - validation_source: "local_lark" or "local_basic"
        """
        errors: List[ValidationError] = []
        error_strings: List[str] = []
        warnings = []
        parsed_lines = 0

        lines = atf_text.strip().split('\n')

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue

            parsed_lines += 1

            if self._parser:
                success, error_msg, column = self.parse_line(stripped)
                if not success and error_msg:
                    error: ValidationError = {
                        "line": i,
                        "message": error_msg
                    }
                    if column is not None:
                        error["column"] = column
                        error_strings.append(f"Line {i}, col {column}: {error_msg}")
                    else:
                        error_strings.append(f"Line {i}: {error_msg}")
                    errors.append(error)

                # Also check brackets (Lark grammar may not catch mismatches)
                if success and not stripped.startswith(('&', '#', '@', '$', '//')):
                    bracket_err = self._check_brackets(stripped, i)
                    if bracket_err:
                        errors.append(bracket_err)
                        col_str = f", col {bracket_err['column']}" if 'column' in bracket_err else ""
                        error_strings.append(f"Line {i}{col_str}: {bracket_err['message']}")
            else:
                # Fall back to basic validation
                basic_errors = self._basic_validate_line(stripped, i)
                for err in basic_errors:
                    errors.append({"line": i, "message": err})
                    error_strings.append(f"Line {i}: {err}")

        validation_source = "local_lark" if self._parser else "local_basic"

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "error_strings": error_strings,
            "warnings": warnings,
            "parsed_lines": parsed_lines,
            "validation_source": validation_source
        }

    def _check_brackets(self, line: str, line_num: int) -> Optional[ValidationError]:
        """Check for mismatched brackets in a line. Returns error with column or None.
        Uses separate stacks per bracket type because ATF allows interleaving
        (e.g., [text {det]text} is valid — damage and determinative brackets are independent)."""
        bracket_pairs = {'(': ')', '[': ']', '<': '>', '{': '}'}
        closing = {v: k for k, v in bracket_pairs.items()}
        stacks: Dict[str, List[int]] = {op: [] for op in bracket_pairs}

        for i, ch in enumerate(line):
            if ch in bracket_pairs:
                stacks[ch].append(i)
            elif ch in closing:
                opener = closing[ch]
                if stacks[opener]:
                    stacks[opener].pop()
                else:
                    return {"line": line_num, "column": i + 1, "message": f"Invalid brackets."}

        for op, positions in stacks.items():
            if positions:
                return {"line": line_num, "column": positions[-1] + 1, "message": f"Invalid brackets."}

        return None

    def _basic_validate_line(self, line: str, line_num: int) -> List[str]:
        """Basic validation without Lark parser."""
        errors = []

        # Control lines - minimal validation
        if line.startswith(('&', '#', '@', '$', '//')):
            return errors

        # Text line - check brackets
        bracket_pairs = [('[', ']'), ('(', ')'), ('<', '>'), ('{', '}')]
        for open_b, close_b in bracket_pairs:
            if line.count(open_b) != line.count(close_b):
                errors.append(f"Line {line_num}: Unmatched brackets '{open_b}' and '{close_b}'")

        return errors


# Global singleton instance
_parser_instance: Optional[EblAtfParser] = None


def get_parser() -> EblAtfParser:
    """Get the global parser instance."""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = EblAtfParser()
    return _parser_instance


def validate_atf(atf_text: str) -> Dict[str, Any]:
    """Convenience function to validate ATF text."""
    return get_parser().validate(atf_text)
