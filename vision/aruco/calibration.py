import cv2
import numpy as np


def calibrate(markers, config):
    def fail(reason):
        return {"valid": False, "reason": reason, "homography": None}
    if not markers:
        return fail("no_markers")
    known = config.get("markers_mm", {})
    src, dst, seen = [], [], set()
    for marker in markers:
        mid = marker["marker_id"]
        if mid in seen:
            return fail("duplicate_marker_id")
        seen.add(mid)
        world = known.get(mid, known.get(str(mid)))
        if world is None:
            continue
        pixels = np.asarray(marker["corners_px"], dtype=float)
        world = np.asarray(world, dtype=float)
        if world.shape != (4, 2) or pixels.shape != (4, 2) or not np.isfinite(world).all() or not np.isfinite(pixels).all():
            return fail("invalid_correspondences")
        src.extend(pixels)
        dst.extend(world)
    if len(src) < 4:
        return fail("insufficient_correspondences")
    src, dst = np.asarray(src), np.asarray(dst)
    if any(np.linalg.matrix_rank(p-p.mean(axis=0)) < 2 or
           np.linalg.cond(p-p.mean(axis=0)) > 1e6 for p in (src, dst)):
        return fail("degenerate_correspondences")
    try:
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, config.get("ransac_threshold_mm", 3.0))
        if H is None or mask is None or not np.isfinite(H).all() or np.linalg.matrix_rank(H) < 3:
            return fail("unstable_homography")
        # Normalize coordinate scales before checking conditioning.
        def normalization(points):
            mean = points.mean(axis=0)
            scale = 1 / np.sqrt(np.mean(np.sum((points-mean)**2, axis=1)))
            return np.array([[scale,0,-scale*mean[0]],[0,scale,-scale*mean[1]],[0,0,1]])
        normalized = normalization(dst) @ H @ np.linalg.inv(normalization(src))
        if np.linalg.cond(normalized) > 1e8:
            return fail("unstable_homography")
        inliers = mask.ravel().astype(bool)
        if inliers.sum() < 4 or inliers.mean() < config.get("min_inlier_ratio", 0.75):
            return fail("insufficient_inliers")
        if any(np.linalg.matrix_rank(p[inliers]-p[inliers].mean(axis=0)) < 2 for p in (src, dst)):
            return fail("degenerate_inliers")
        projected = cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2)
        errors = np.linalg.norm(projected-dst, axis=1)
        # Reject conflicting surveyed corners, even if RANSAC could discard them.
        if not np.isfinite(errors).all() or errors.max() > config.get("max_reprojection_error_mm", 3.0):
            return fail("high_reprojection_error")
    except (cv2.error, np.linalg.LinAlgError):
        return fail("homography_failed")
    return {"valid": True, "reason": "ok", "homography": H.tolist(),
            "correspondence_count": len(src), "inlier_count": int(inliers.sum()),
            "max_reprojection_error_mm": float(errors.max())}


def transform_center(center_px, calibration):
    result = {"center_px": list(center_px), "center_world_mm": None, "calibration_valid": False}
    if not calibration["valid"]:
        return result
    H = np.asarray(calibration["homography"])
    p = H @ np.array([*center_px, 1.0])
    if not np.isfinite(p).all() or abs(p[2]) < 1e-10:
        return result
    world = p[:2]/p[2]
    if np.isfinite(world).all():
        result.update(center_world_mm=world.tolist(), calibration_valid=True)
    return result


def crop_section(image, homography, bounds_mm):
    """Project a surveyed section into the current frame, then rectify that crop."""
    left, top, right, bottom = np.asarray(bounds_mm, dtype=float)
    if not np.isfinite([left, top, right, bottom]).all() or left >= right or top >= bottom:
        raise ValueError('bounds_mm must be [left, top, right, bottom] with positive area')
    corners = np.array([[left, top, 1], [right, top, 1], [right, bottom, 1], [left, bottom, 1]])
    projected = corners @ np.linalg.inv(homography).T
    scale = projected[:, 2]
    if not (np.all(scale > 1e-10) or np.all(scale < -1e-10)):
        return None
    quad = projected[:, :2] / scale[:, None]
    frame_h, frame_w = image.shape[:2]
    if (not np.isfinite(quad).all() or (quad < 0).any()
            or (quad[:, 0] > frame_w - 1).any() or (quad[:, 1] > frame_h - 1).any()):
        return None
    edges = np.linalg.norm(np.roll(quad, -1, axis=0) - quad, axis=1)
    width = round(max(edges[0], edges[2]))
    height = round(max(edges[1], edges[3]))
    if min(width, height) < 2:
        return None
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    transform = cv2.getPerspectiveTransform(quad.astype(np.float32), target)
    return cv2.warpPerspective(image, transform, (width, height))
