"""
CuRe Sign Detection — OpenCV-based bounding box detection for cuneiform signs.

Adapted from CuneiformOcr/src/utils.py (get_bounding_box_of_img, combine_boxes).
Detects individual cuneiform signs from tablet hand-copy images using
contour detection, then groups them into lines.
"""
import logging
from dataclasses import dataclass
from typing import List

import cv2
import numpy as np


@dataclass
class SignDetection:
    """A detected cuneiform sign bounding box."""
    x: int
    y: int
    width: int
    height: int
    line_number: int
    position_in_line: int


def _union(box1, box2):
    """Merge two boxes into their bounding union. Boxes are (x1, y1, x2, y2)."""
    return (
        min(box1[0], box2[0]),
        min(box1[1], box2[1]),
        max(box1[2], box2[2]),
        max(box1[3], box2[3]),
    )


def _should_merge(box1, box2, max_x_gap: int = 50, max_y_diff: int = 20) -> bool:
    """Check if two adjacent boxes should be merged based on proximity."""
    # box1[2] is x2 (right edge), box2[0] is x1 (left edge)
    x_gap = box1[2] - box2[0]
    y_diff = abs(box1[3] - box2[3])
    return 2 < x_gap < max_x_gap and y_diff < max_y_diff


def _combine_boxes(
    boxes: np.ndarray,
    max_x_gap: int = 50,
    max_y_diff: int = 20,
) -> np.ndarray:
    """Merge adjacent overlapping boxes. Boxes are (x1, y1, x2, y2)."""
    if len(boxes) == 0:
        return boxes
    result = []
    i = 0
    while i < len(boxes) - 1:
        if _should_merge(boxes[i], boxes[i + 1], max_x_gap, max_y_diff):
            result.append(_union(boxes[i], boxes[i + 1]))
            i += 2
        else:
            result.append(tuple(boxes[i]))
            i += 1
    if i <= len(boxes) - 1:
        result.append(tuple(boxes[i]))
    return np.array(result, dtype=int)


def detect_signs(
    image_np: np.ndarray,
    min_width: int = None,
    max_width: int = None,
    min_height: int = None,
    max_height: int = None,
    min_contour_area: int = None,
    min_black_pixel_pct: float = None,
    line_y_tolerance: int = None,
) -> List[SignDetection]:
    """
    Detect cuneiform sign bounding boxes from a tablet image.

    All filter parameters are adaptive: when None (default) they scale
    automatically based on image dimensions.  Explicit values override.

    Args:
        image_np: BGR numpy array (from cv2.imread or decoded from base64)
        min_width/max_width: Width filter range for sign contours
        min_height/max_height: Height filter range for sign contours
        min_contour_area: Minimum contour area in pixels
        min_black_pixel_pct: Minimum percentage of dark pixels in crop
        line_y_tolerance: Max Y-distance to consider signs on the same line

    Returns:
        List of SignDetection sorted by line_number then position_in_line.
    """
    if image_np is None or image_np.size == 0:
        logging.warning("CuRe detection: image is None or empty")
        return []

    logging.info(f"CuRe detection: image shape={image_np.shape}, dtype={image_np.dtype}")

    h_img, w_img = image_np.shape[:2]

    # ---------- adaptive defaults based on image size ----------
    # Reference size the original hard-coded values were tuned for (~400x300).
    if min_width is None:
        min_width = max(8, int(w_img * 0.01))
    if max_width is None:
        max_width = max(130, int(w_img * 0.35))
    if min_height is None:
        min_height = max(8, int(h_img * 0.01))
    if max_height is None:
        max_height = max(50, int(h_img * 0.15))
    if min_contour_area is None:
        img_diag = (w_img ** 2 + h_img ** 2) ** 0.5
        min_contour_area = max(60, int(img_diag * 0.04))
    if min_black_pixel_pct is None:
        min_black_pixel_pct = 5.0
    if line_y_tolerance is None:
        line_y_tolerance = max(25, int(h_img * 0.04))

    # Scale morphological kernel with image size
    scale = max(w_img, h_img) / 400.0
    kernel_size = max(2, min(5, round(2 * scale)))

    logging.info(
        f"CuRe detection params: w=[{min_width},{max_width}], "
        f"h=[{min_height},{max_height}], area>={min_contour_area}, "
        f"ink>={min_black_pixel_pct}%, kernel={kernel_size}, "
        f"line_tol={line_y_tolerance}"
    )

    # Convert to grayscale
    if len(image_np.shape) == 3:
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_np.copy()

    # Otsu thresholding — also capture the threshold value for ink check
    otsu_val, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Morphological gradient to highlight edges of signs
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    gradient = cv2.morphologyEx(thresh, cv2.MORPH_GRADIENT, kernel)

    # Find contours
    contours, _ = cv2.findContours(gradient, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    logging.info(f"CuRe detection: {len(contours)} total contours found")

    # Filter contours by size, area, and ink density
    raw_boxes = []  # (x1, y1, x2, y2) format
    rejected_size = 0
    rejected_area = 0
    rejected_ink = 0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)

        if not (min_width < w < max_width and min_height < h < max_height):
            rejected_size += 1
            continue
        if cv2.contourArea(contour) <= min_contour_area:
            rejected_area += 1
            continue

        # Check ink density — use Otsu threshold (not exact ==0)
        y_start = max(0, y - 1)
        x_start = max(0, x - 1)
        crop = gray[y_start:y + h + 1, x_start:x + w + 1]
        if crop.size == 0:
            continue
        black_pct = (np.sum(crop < otsu_val) / crop.size) * 100
        if black_pct < min_black_pixel_pct:
            rejected_ink += 1
            continue

        # Store as (x1, y1, x2, y2) with 1px padding
        raw_boxes.append((x - 1, y - 1, x + w + 1, y + h + 1))

    logging.info(
        f"CuRe detection filter: {len(raw_boxes)} passed, "
        f"rejected: size={rejected_size}, area={rejected_area}, ink={rejected_ink}"
    )

    if not raw_boxes:
        logging.info("CuRe detection: no signs found after filtering")
        return []

    # Sort by Y coordinate for line grouping
    raw_boxes.sort(key=lambda b: b[1])

    # Assign line numbers based on Y proximity
    line_assignments = []
    current_y = raw_boxes[0][1]
    current_line = 0
    for box in raw_boxes:
        if abs(box[1] - current_y) > line_y_tolerance:
            current_y = box[1]
            current_line += 1
        line_assignments.append(current_line)

    # Group boxes by line and sort within line by X
    lines = {}
    for box, line_num in zip(raw_boxes, line_assignments):
        lines.setdefault(line_num, []).append(box)
    for line_num in lines:
        lines[line_num].sort(key=lambda b: b[0])

    # Flatten back into sorted array for box merging
    sorted_boxes = []
    sorted_lines = []
    for line_num in sorted(lines.keys()):
        for box in lines[line_num]:
            sorted_boxes.append(box)
            sorted_lines.append(line_num)

    if not sorted_boxes:
        return []

    # Merge adjacent boxes (run twice like original)
    # Scale merge thresholds with image size
    merge_x_gap = max(50, int(w_img * 0.03))
    merge_y_diff = max(20, int(h_img * 0.02))
    boxes_arr = np.array(sorted_boxes, dtype=int)
    merged = _combine_boxes(boxes_arr, merge_x_gap, merge_y_diff)
    merged = _combine_boxes(merged, merge_x_gap, merge_y_diff)

    # Re-assign line numbers and positions after merging
    if len(merged) == 0:
        return []

    # Re-group merged boxes into lines
    merged_sorted = sorted(merged.tolist(), key=lambda b: (b[1], b[0]))
    current_y = merged_sorted[0][1]
    current_line = 0
    detections = []
    position = 0

    for box in merged_sorted:
        x1, y1, x2, y2 = box
        if abs(y1 - current_y) > line_y_tolerance:
            current_y = y1
            current_line += 1
            position = 0

        detections.append(SignDetection(
            x=x1,
            y=y1,
            width=x2 - x1,
            height=y2 - y1,
            line_number=current_line,
            position_in_line=position,
        ))
        position += 1

    # Sort within each line by X
    detections.sort(key=lambda d: (d.line_number, d.x))
    # Reassign position_in_line after final sort
    current_line = -1
    pos = 0
    for det in detections:
        if det.line_number != current_line:
            current_line = det.line_number
            pos = 0
        det.position_in_line = pos
        pos += 1

    logging.info(f"CuRe detection: found {len(detections)} signs in {current_line + 1} lines")
    return detections
