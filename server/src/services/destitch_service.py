"""
Destitch Service

Splits a stitched tablet composite (produced by ebl-tablet-studio) into labeled
view crops. Each view carries its bounding box in composite pixel space ("origin"),
so downstream annotations can be stored in composite-absolute coordinates and
projected back onto any crop or the original composite.

Layout assumption (from ebl-tablet-studio stitch_layout_calculation.py):

    [obverse_top intermediates]            _ot, _ot2, ...
    [left]  [OBVERSE]  [right]             _05 _01 _06
    [obverse_bottom intermediates]         _ob, _ob2, ...
    [BOTTOM edge strip]                    _04
    [reverse_top intermediates]            _rt, _rt2, ...
    [reverse_left]  [REVERSE]  [reverse_right]   _02  (+ _rl / _rr intermediates)
    [reverse_bottom intermediates]         _rb, _rb2, ...
    [TOP edge strip]                       _03
    [ruler]                                (discarded)

Rotated-duplicate side edges (_05r / _06r) are intentionally dropped.
"""

import base64
import logging
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel

# Stitched tablet composites legitimately exceed PIL's default decompression
# bomb threshold. The images we receive are authored by us (ebl-tablet-studio),
# so the DoS heuristic is not relevant.
Image.MAX_IMAGE_PIXELS = None

logger = logging.getLogger(__name__)


# ── DTOs ───────────────────────────────────────────────────────────────

class ViewBBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class View(BaseModel):
    code: str
    bbox: ViewBBox
    origin: ViewBBox  # top-left in composite pixel space (x, y) + width/height
    area: int
    crop_base64: Optional[str] = None
    mask_base64: Optional[str] = None


class DestitchResult(BaseModel):
    views: List[View]
    canvas: ViewBBox
    background: List[int]
    error: Optional[str] = None


class DestitchClassification(BaseModel):
    is_composite: bool
    view_count: int
    confidence: float
    error: Optional[str] = None


# ── Service ────────────────────────────────────────────────────────────

class DestitchService:

    MIN_AREA_FRAC = 0.002
    BG_TOLERANCE = 15
    COMPOSITE_MIN_VIEWS = 4
    SILENT_CONFIDENCE_THRESHOLD = 0.75
    MASK_DILATION_PX = 6

    # Public API ────────────────────────────────────────────────────────

    def classify(self, image_base64: str) -> DestitchClassification:
        """Quick check: is this image a stitched composite?"""
        try:
            img = self._decode_to_bgr(image_base64)
        except Exception as e:
            return DestitchClassification(is_composite=False, view_count=0,
                                          confidence=0.0, error=str(e))

        try:
            blobs, _ = self._find_blobs(img)
        except Exception as e:
            logger.warning(f"classify: blob detection failed: {e}")
            return DestitchClassification(is_composite=False, view_count=0,
                                          confidence=0.0, error=str(e))

        h, w = img.shape[:2]
        filtered = [b for b in blobs if not self._looks_like_ruler(b, h, w)]
        view_count = len(filtered)

        upper = [b for b in filtered if b["cy"] < h / 2]
        lower = [b for b in filtered if b["cy"] >= h / 2]
        has_obv = bool(upper)
        has_rev = bool(lower)

        # Require top-2 blobs to be sizeable relative to their rows, and the
        # obverse/reverse anchors to be vertically separated.
        confidence = 0.0
        if view_count >= self.COMPOSITE_MIN_VIEWS and has_obv and has_rev:
            base = min(1.0, (view_count - (self.COMPOSITE_MIN_VIEWS - 1)) / 5.0)
            obv = max(upper, key=lambda b: b["area"])
            rev = max(lower, key=lambda b: b["area"])
            vsep = abs(rev["cy"] - obv["cy"]) / h
            separation_bonus = min(0.3, max(0.0, vsep - 0.3))
            confidence = min(1.0, base + separation_bonus)

        is_composite = confidence > 0 and view_count >= self.COMPOSITE_MIN_VIEWS
        return DestitchClassification(is_composite=is_composite,
                                      view_count=view_count,
                                      confidence=round(confidence, 3))

    def split(
        self,
        image_base64: str,
        include_crops: bool = False,
        include_masks: bool = False,
    ) -> DestitchResult:
        """Full detection + labeling. Returns labeled view bboxes (and optional
        crops / per-view masks)."""
        try:
            img = self._decode_to_bgr(image_base64)
        except Exception as e:
            return DestitchResult(views=[], canvas=ViewBBox(x=0, y=0, width=0, height=0),
                                  background=[0, 0, 0], error=f"could not decode image: {e}")

        h, w = img.shape[:2]
        blobs, bg = self._find_blobs(img)
        if not blobs:
            return DestitchResult(views=[], canvas=ViewBBox(x=0, y=0, width=w, height=h),
                                  background=list(bg), error="no foreground detected")

        labeled = self._classify_views(blobs, h, w)

        views: List[View] = []
        for code, b in labeled.items():
            bbox = ViewBBox(x=b["x"], y=b["y"], width=b["w"], height=b["h"])
            origin = ViewBBox(x=b["x"], y=b["y"], width=b["w"], height=b["h"])
            view = View(code=code, bbox=bbox, origin=origin, area=b["area"])
            if include_crops:
                view.crop_base64 = self._encode_png(
                    img[b["y"]: b["y"] + b["h"], b["x"]: b["x"] + b["w"]])
            if include_masks:
                mask = self._build_mask(b, h, w)
                view.mask_base64 = self._encode_png(mask)
            views.append(view)

        views.sort(key=lambda v: self._view_sort_key(v.code))
        return DestitchResult(views=views,
                              canvas=ViewBBox(x=0, y=0, width=w, height=h),
                              background=list(bg))

    # CV primitives ─────────────────────────────────────────────────────

    def _find_blobs(self, img: np.ndarray) -> Tuple[List[Dict], Tuple[int, int, int]]:
        h, w = img.shape[:2]
        bg = self._sample_background(img)
        diff = np.abs(img.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
        fg = (diff > self.BG_TOLERANCE).astype(np.uint8) * 255
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k, iterations=1)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=2)

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area = int(h * w * self.MIN_AREA_FRAC)
        blobs: List[Dict] = []
        for c in contours:
            area = int(cv2.contourArea(c))
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            blobs.append({
                "x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
                "area": area, "cx": int(x + bw / 2), "cy": int(y + bh / 2),
                "contour": c,
            })
        return blobs, tuple(int(v) for v in bg)

    @staticmethod
    def _sample_background(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        s = min(50, h // 20, w // 20) or 1
        patches = [img[:s, :s], img[:s, -s:], img[-s:, :s], img[-s:, -s:]]
        return np.median(
            np.concatenate([p.reshape(-1, p.shape[-1]) for p in patches], axis=0),
            axis=0,
        )

    @staticmethod
    def _looks_like_ruler(b: Dict, canvas_h: int, canvas_w: int) -> bool:
        in_bottom = b["y"] > canvas_h * 0.88
        wide_short = b["w"] > 3 * b["h"]
        narrow = b["w"] < canvas_w * 0.6
        return in_bottom and wide_short and narrow

    # View labeling ─────────────────────────────────────────────────────

    def _classify_views(self, blobs: List[Dict], canvas_h: int, canvas_w: int) -> Dict[str, Dict]:
        views = [b for b in blobs if not self._looks_like_ruler(b, canvas_h, canvas_w)]
        if not views:
            return {}

        upper = [b for b in views if b["cy"] < canvas_h / 2]
        lower = [b for b in views if b["cy"] >= canvas_h / 2]
        obverse = max(upper, key=lambda b: b["area"]) if upper else None
        reverse = max(lower, key=lambda b: b["area"]) if lower else None

        result: Dict[str, Dict] = {}
        if obverse is not None:
            result["_01"] = obverse
        if reverse is not None:
            result["_02"] = reverse

        def overlaps_y(b, anchor):
            return not (b["y"] + b["h"] < anchor["y"] or b["y"] > anchor["y"] + anchor["h"])

        def classify_side(row_blobs, anchor, codes):
            """codes = (outer_left, inner_left_stem, outer_right, inner_right_stem)."""
            out: Dict[str, Dict] = {}
            left = sorted([b for b in row_blobs if b["cx"] < anchor["cx"]],
                          key=lambda b: b["cx"], reverse=True)
            right = sorted([b for b in row_blobs if b["cx"] > anchor["cx"]],
                           key=lambda b: b["cx"])
            if left:
                out[codes[0]] = left[-1]
                for i, b in enumerate(left[:-1]):
                    out[f"_{codes[1]}{'' if i == 0 else i + 1}"] = b
            if right:
                out[codes[2]] = right[-1]
                for i, b in enumerate(right[:-1]):
                    out[f"_{codes[3]}{'' if i == 0 else i + 1}"] = b
            return out

        if obverse is not None:
            obv_row = [b for b in views if b is not obverse and overlaps_y(b, obverse)]
            result.update(classify_side(obv_row, obverse, ("_05", "ol", "_06", "or")))

        # Reverse-row side edges are the rotated duplicates of the obverse-row
        # edges (same source image, rendered 180° flipped). We intentionally
        # drop the outermost duplicates and keep only extra intermediates
        # discovered in the reverse row.
        if reverse is not None:
            rev_row = [b for b in views if b is not reverse and overlaps_y(b, reverse)]
            rev_sides = classify_side(rev_row, reverse,
                                      ("__drop_05r", "rl", "__drop_06r", "rr"))
            for code, b in rev_sides.items():
                if code.startswith("__drop_"):
                    continue
                result[code] = b

        used = {id(b) for b in result.values()}
        rest = [b for b in views if id(b) not in used]

        above = sorted(
            [b for b in rest if obverse is not None and b["cy"] < obverse["y"]],
            key=lambda b: b["cy"])
        between = sorted(
            [b for b in rest
             if obverse is not None and reverse is not None
             and b["cy"] > obverse["y"] + obverse["h"] and b["cy"] < reverse["y"]],
            key=lambda b: b["cy"])
        below = sorted(
            [b for b in rest if reverse is not None and b["cy"] > reverse["y"] + reverse["h"]],
            key=lambda b: b["cy"])

        for i, b in enumerate(above):
            result[f"_ot{'' if i == 0 else i + 1}"] = b

        if len(between) == 1:
            result["_04"] = between[0]
        elif between:
            mid_idx = len(between) // 2
            for i, b in enumerate(between[:mid_idx]):
                result[f"_ob{'' if i == 0 else i + 1}"] = b
            result["_04"] = between[mid_idx]
            for i, b in enumerate(between[mid_idx + 1:]):
                result[f"_rt{'' if i == 0 else i + 1}"] = b

        if len(below) == 1:
            result["_03"] = below[0]
        elif below:
            for i, b in enumerate(below[:-1]):
                result[f"_rb{'' if i == 0 else i + 1}"] = b
            result["_03"] = below[-1]

        return result

    # Mask + encoding helpers ───────────────────────────────────────────

    def _build_mask(self, blob: Dict, canvas_h: int, canvas_w: int) -> np.ndarray:
        """Binary PNG-sized mask showing only tablet pixels inside the bbox."""
        mask = np.zeros((blob["h"], blob["w"]), dtype=np.uint8)
        local = blob["contour"] - np.array([blob["x"], blob["y"]])
        cv2.fillPoly(mask, [local], 255)
        if self.MASK_DILATION_PX > 0:
            kernel = np.ones((self.MASK_DILATION_PX, self.MASK_DILATION_PX), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=1)
        return mask

    @staticmethod
    def _encode_png(img: np.ndarray) -> str:
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise RuntimeError("PNG encoding failed")
        return base64.b64encode(buf.tobytes()).decode("ascii")

    @staticmethod
    def _decode_to_bgr(image_base64: str) -> np.ndarray:
        if image_base64.startswith("data:"):
            comma = image_base64.find(",")
            if comma != -1:
                image_base64 = image_base64[comma + 1:]
        raw = base64.b64decode(image_base64)
        pil = Image.open(BytesIO(raw)).convert("RGB")
        return np.asarray(pil)[:, :, ::-1].copy()  # RGB → BGR

    @staticmethod
    def _view_sort_key(code: str) -> Tuple[int, str]:
        priority = {"_01": 0, "_02": 1, "_03": 2, "_04": 3, "_05": 4, "_06": 5}
        return (priority.get(code, 99), code)


destitch_service = DestitchService()
