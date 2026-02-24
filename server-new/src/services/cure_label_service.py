"""
CuRe Label Service — Manages sign label <-> Unicode mappings.

Replaces the old CSV-based mapping files (filtered_label_from_Avital_ver3.csv,
unicode_to_label_dict.csv, label_to_unicode_dict.csv).
Labels are derived from training data and persisted as JSON alongside each model.
"""
import json
import logging
import os
from typing import Dict, List, Optional

import pandas as pd


class CuReLabelService:
    """Manages the bidirectional mapping between sign labels and Unicode characters."""

    def __init__(self):
        self.label_list: List[str] = []
        self.label_to_index: Dict[str, int] = {}
        self.index_to_label: Dict[int, str] = {}
        self.label_to_unicode: Dict[str, str] = {}
        self.unicode_to_labels: Dict[str, List[str]] = {}

    @property
    def num_classes(self) -> int:
        return len(self.label_list)

    def load_from_training(self, annotation_df: pd.DataFrame, label_column: str = "label"):
        """
        Derive label list from training data annotations.
        This is how labels are created when training from scratch.
        """
        unique_labels = sorted(annotation_df[label_column].unique().tolist())
        self._set_labels(unique_labels)
        logging.info(f"CuRe labels loaded from training data: {self.num_classes} classes")

    def load_from_label_list(self, label_list: List[str]):
        """Set labels from an explicit ordered list."""
        self._set_labels(label_list)

    def _set_labels(self, labels: List[str]):
        """Internal: populate all label mappings from an ordered list."""
        self.label_list = labels
        self.label_to_index = {label: i for i, label in enumerate(labels)}
        self.index_to_label = {i: label for i, label in enumerate(labels)}

    def load_unicode_mapping(self, mapping: Dict[str, str]):
        """Load label-to-unicode mapping from a dict."""
        self.label_to_unicode = dict(mapping)
        # Build reverse mapping
        self.unicode_to_labels = {}
        for label, unicode_char in mapping.items():
            if unicode_char:
                self.unicode_to_labels.setdefault(unicode_char, []).append(label)

    def get_unicode(self, label: str) -> str:
        """Get the Unicode character for a label, or empty string if unknown."""
        return self.label_to_unicode.get(label, "")

    def save_mapping(self, json_path: str):
        """Save the complete label mapping to a JSON file."""
        data = {
            "label_list": self.label_list,
            "label_to_index": self.label_to_index,
            "label_to_unicode": self.label_to_unicode,
        }
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"CuRe label mapping saved to {json_path} ({self.num_classes} classes)")

    def load_mapping(self, json_path: str) -> bool:
        """
        Load a complete label mapping from a JSON file.
        Returns True if successful, False if file not found.
        """
        if not os.path.exists(json_path):
            logging.warning(f"CuRe label mapping not found: {json_path}")
            return False

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._set_labels(data["label_list"])
        unicode_map = data.get("label_to_unicode", {})
        if unicode_map:
            self.load_unicode_mapping(unicode_map)

        logging.info(f"CuRe label mapping loaded from {json_path} ({self.num_classes} classes)")
        return True

    def import_from_csv(self, csv_path: str, label_col: str = "label", unicode_col: str = "unicode"):
        """
        Import label-to-unicode mapping from a CSV file.
        Used for importing old-format CSV files (e.g., filtered_label_from_Avital_ver3.csv).
        """
        df = pd.read_csv(csv_path, keep_default_na=False, encoding="utf-8")
        labels = df[label_col].tolist()
        self._set_labels(labels)

        if unicode_col in df.columns:
            mapping = {}
            for _, row in df.iterrows():
                label = row[label_col]
                unicode_char = row.get(unicode_col, "")
                if unicode_char:
                    mapping[label] = unicode_char
            self.load_unicode_mapping(mapping)

        logging.info(f"CuRe labels imported from CSV {csv_path}: {self.num_classes} classes")

    def import_unicode_csv(self, csv_path: str, label_col: str = "label", unicode_col: str = "unicode"):
        """Import only unicode mapping from a separate CSV (e.g., label_to_unicode_dict.csv)."""
        df = pd.read_csv(csv_path, keep_default_na=False, encoding="utf-8")
        mapping = {}
        for _, row in df.iterrows():
            label = str(row[label_col]).strip()
            unicode_char = str(row[unicode_col]).strip()
            if label and unicode_char:
                mapping[label] = unicode_char
        self.load_unicode_mapping(mapping)
        logging.info(f"CuRe unicode mapping imported: {len(mapping)} entries")
