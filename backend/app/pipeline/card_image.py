"""Conservative card-boundary preparation; original bytes are never replaced."""

import numpy as np
from PIL import Image


def crop_card(source):
    import cv2

    if min(source.size) < 240:
        return source.copy(), {
            "applied": False,
            "reason": "Image is too small for a reliable card boundary.",
        }
    working = source.copy()
    working.thumbnail((2200, 2200))
    rgb = np.asarray(working.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 45, 140)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = working.width * working.height
    candidates = []
    for contour in contours:
        polygon = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        fraction = cv2.contourArea(polygon) / area
        if len(polygon) != 4 or not cv2.isContourConvex(polygon) or not 0.18 < fraction < 0.97:
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        total, diff = points.sum(axis=1), np.diff(points, axis=1).ravel()
        ordered = np.array(
            [
                points[total.argmin()],
                points[diff.argmin()],
                points[total.argmax()],
                points[diff.argmax()],
            ],
            dtype=np.float32,
        )
        if len(np.unique(ordered, axis=0)) != 4:
            continue
        top, right, bottom, left = [
            np.linalg.norm(ordered[(i + 1) % 4] - ordered[i]) for i in range(4)
        ]
        width, height = int(max(top, bottom)), int(max(left, right))
        if (
            min(width, height) < 180
            or max(width, height) / min(width, height) > 2.5
            or max(width, height) / min(width, height) < 1.2
        ):
            continue
        candidates.append((fraction, ordered, width, height))
    if len(candidates) != 1:
        return source.copy(), {
            "applied": False,
            "reason": "No single confident card boundary; full photo retained.",
        }
    _, points, width, height = candidates[0]
    centre = points.mean(axis=0)
    points = centre + (points - centre) * 1.025
    points[:, 0] = np.clip(points[:, 0], 0, working.width - 1)
    points[:, 1] = np.clip(points[:, 1], 0, working.height - 1)
    # Reject a logo/panel rectangle when letter-sized components remain outside it.
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, points.astype(np.int32), 255)
    ink = ((gray < 160) & (mask == 0)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    outside_letters = sum(
        1
        for x, y, w, h, area in stats[1:]
        if 3 <= h <= working.height * 0.08 and 1 <= w <= working.width * 0.15 and 4 <= area <= 2500
    )
    if outside_letters >= 12:
        return source.copy(), {
            "applied": False,
            "reason": "Printed detail outside the boundary; full photo retained.",
        }
    normalized = points.astype(np.float64) / np.array([working.width, working.height])
    info = {
        "applied": True,
        "polygon": normalized.tolist(),
        "space": "normalized_original",
        "original_size": list(source.size),
    }
    # Detect at low resolution, but rectify from original detail, not that detection copy.
    scaled = normalized * np.array(source.size)
    edges = [np.linalg.norm(scaled[(i + 1) % 4] - scaled[i]) for i in range(4)]
    width, height = max(edges[0], edges[2]), max(edges[1], edges[3])
    factor = min(1.0, 4096 / max(width, height))
    info["output_size"] = [max(1, round(width * factor)), max(1, round(height * factor))]
    return apply_card_crop(source, info), info


def apply_card_crop(source, info):
    import cv2

    if not info.get("applied"):
        return source.copy()
    points = np.array(info["polygon"], dtype=np.float64)
    if info.get("space") == "normalized_original":
        points *= np.array(source.size)
    else:
        # Older cached preparation metadata used detection-image coordinates.
        points *= np.array(source.size) / np.array(info["detection_size"])
    edges = [np.linalg.norm(points[(i + 1) % 4] - points[i]) for i in range(4)]
    width, height = info.get(
        "output_size", [round(max(edges[0], edges[2])), round(max(edges[1], edges[3]))]
    )
    factor = min(1.0, 4096 / max(width, height))
    width, height = max(1, round(width * factor)), max(1, round(height * factor))
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(points.astype(np.float32), target)
    return Image.fromarray(
        cv2.warpPerspective(
            np.asarray(source.convert("RGB")),
            matrix,
            (width, height),
            borderMode=cv2.BORDER_REPLICATE,
        )
    )
