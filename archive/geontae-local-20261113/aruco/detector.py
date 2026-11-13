import cv2


def detect_markers(image, dictionary="DICT_4X4_50"):
    if not dictionary.startswith("DICT_") or not hasattr(cv2.aruco, dictionary):
        raise ValueError(f"Unknown ArUco dictionary: {dictionary}")
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)),
                                       cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(image)
    if ids is None:
        return []
    return [{"marker_id": int(i), "corners_px": c.reshape(4, 2).tolist()}
            for i, c in zip(ids.flatten(), corners)]
