"""Match a Korean query to stored items and count YOLO boxes in the selected section."""

import argparse
import json
import os
import re
from pathlib import Path

import cv2
import numpy as np
import yaml

from agents.contracts import NONE, UNKNOWN
from agents.db_part import PostgresDbPart
from agents.vision_adapter import CATEGORY, COLOR, calibration_ok
from matching.hybrid import HybridMatcher
from matching.korean_query import KoreanFirstParser
from matching.policy import load_config
from matching.query_parser import guard_decision, guard_query_constraints
from vision.aruco.calibration import calibrate, crop_section
from vision.aruco.detector import detect_markers
from vision.section_regions import crop_pixels, load_regions
from vision.vision_pipeline import ROOT, VISION_ROOT
from vision.yolo.detector import YoloDetector


# First mapping wins for values collapsed by the team's intake adapter.
DB_CATEGORIES = {label: key for key, label in reversed(tuple(CATEGORY.items()))}
DB_COLORS = {label: key for key, label in reversed(tuple(COLOR.items()))}
ON_SHELF = {'본센터 보관', '확인 중', '승인·수령 예약'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_storage(path):
    storage = read_json(path)
    sections, inventory = storage['sections'], storage['inventory']
    occupied = set()
    for item_id, location in inventory.items():
        section, slot = location['section'], location['slot']
        pose = sections[section]['slots'][slot]
        if not item_id.strip() or not isinstance(pose, str) or not pose.strip():
            raise ValueError('Every stored item requires an ID and a named pose')
        if (section, slot) in occupied:
            raise ValueError(f'Multiple items assigned to section {section}, slot {slot}')
        occupied.add((section, slot))
    return sections, inventory


def candidate_features(item):
    """Convert the existing DB intake summary into HybridMatcher features."""
    features = item['features']
    color = DB_COLORS.get(features.get('color'))
    mark = features.get('mark')
    result = {
        'category': DB_CATEGORIES.get(item['category'], 'unknown'),
        'colors': [color] if color else [],
        'sticker_status': 'absent' if mark == NONE else 'unknown',
    }
    if isinstance(mark, str) and re.search(r'\bsticker\b|스티커', mark, re.IGNORECASE):
        result['sticker_status'] = 'present'
        result['distinctive_features'] = [mark]
    for source, target in (('material', 'materials'), ('visible_text', 'logos_or_text')):
        value = features.get(source)
        if isinstance(value, str) and value.strip() and value not in (NONE, UNKNOWN):
            result[target] = [value]
    shape = features.get('shape')
    if isinstance(shape, str) and shape not in (NONE, UNKNOWN):
        result['shape'] = shape
    return result


def check_counts(images, bounds, expected, config, device, *, image_size_px=None):
    detector = None
    attempts = []
    for path in images:
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'Cannot read image: {path}')
        attempt = {'image': str(path), 'detected_count': None}
        attempts.append(attempt)
        if image_size_px is not None:
            actual_size = list(image.shape[1::-1])
            if actual_size != image_size_px:
                attempt.update(status='resolution_mismatch', image_size_px=actual_size,
                               reference_size_px=image_size_px)
                continue
            crop = crop_pixels(image, bounds)
        else:
            aruco = config['aruco']
            calibration = calibrate(detect_markers(image, aruco.get('dictionary', 'DICT_4X4_50')), aruco)
            valid, reason = calibration_ok({'calibration': calibration})
            if not valid:
                attempt.update(status='invalid_calibration', reason=reason)
                continue
            crop = crop_section(image, calibration['homography'], bounds)
            if crop is None:
                attempt['status'] = 'section_out_of_frame'
                continue
        if detector is None:
            detector = YoloDetector(ROOT / config['model'], device or config.get('device', 'auto'),
                                    config.get('confidence', 0.25), config.get('imgsz', 640))
        count = len(detector.detect(crop))
        attempt.update(status='count_match' if count == expected else 'count_mismatch',
                       detected_count=count, crop_size_px=list(crop.shape[1::-1]))
        if count == expected:
            break
    return attempts


def inspect_storage(text, images, sections, inventory, get_item, parser, matcher, config, device, *, regions=None):
    result = {'status': 'match_held', 'robot_authorized': False, 'requires_staff_confirmation': True}
    candidates = []
    for item_id in inventory:
        item = get_item(item_id)
        if not item or item['status'] not in ON_SHELF:
            raise ValueError(f'Storage assignment has no corresponding on-shelf DB item: {item_id}')
        candidates.append({'id': item_id, 'features': candidate_features(item)})

    parsed = parser.parse(text)
    ranking, engine, _ = matcher.match(candidates, parsed['features'])
    decision = guard_query_constraints(engine, parsed)
    result.update(matching=guard_decision(engine, parsed),
                  top_candidates=[{'item_id': row['id'], 'score': row['final_score']}
                                  for row in ranking if row['eligible']][:3])
    if decision['status'] != 'matched' or parsed['needs_clarification']:
        return result

    # A provisional candidate can drive the camera check even with the parser's review flag.
    item_id = decision['selected_id']
    section, slot = inventory[item_id]['section'], inventory[item_id]['slot']
    expected = sum(location['section'] == section for location in inventory.values())
    result.update(candidate={'item_id': item_id, 'section': section, 'slot': slot,
                             'pose': sections[section]['slots'][slot]}, expected_count=expected)
    if regions is None:
        attempts = check_counts(images, sections[section]['bounds_mm'], expected, config, device)
    else:
        bounds = regions['regions'].get(section)
        if bounds is None:
            return {**result, 'status': 'verification_unavailable', 'reason': 'missing_saved_region'}
        attempts = check_counts(images, bounds, expected, config, device, image_size_px=regions['image_size_px'])
    status = attempts[-1]['status']
    result.update(status=status if status.startswith('count_') else 'verification_unavailable', attempts=attempts)
    return result


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--storage', type=Path, required=True,
                     help='JSON with sections {name: {slots: {slot: pose}}} and inventory {item_id: {section, slot}}. '
                          'Supply bounds_mm in the section when not using --regions.')
    cli.add_argument('--regions', type=Path, help='Named fixed-camera region JSON from preview_section --draw')
    cli.add_argument('--snapshot', type=Path,
                     help='Offline DB rows keyed by item_id (category, status, merged features). '
                          'Otherwise reads PostgreSQL via DATABASE_URL.')
    query = cli.add_mutually_exclusive_group(required=True)
    query.add_argument('--text')
    query.add_argument('--query-file', type=Path, help='UTF-8 Korean query')
    cli.add_argument('--image', type=Path, action='append', required=True,
                     help='Top-view frame. Repeat with up to two additional captures, in order.')
    cli.add_argument('--config', type=Path, default=VISION_ROOT / 'configs/vision.yaml')
    cli.add_argument('--device', default='cpu')
    args = cli.parse_args(argv)
    images = [path.resolve() for path in args.image]
    if len(images) > 3 or len(set(images)) != len(images):
        cli.error('Provide one to three distinct captures with --image')
    try:
        text = args.query_file.read_text(encoding='utf-8-sig') if args.query_file else args.text
        if not text.strip():
            raise ValueError('Query text is empty')
        sections, inventory = load_storage(args.storage)
        regions = load_regions(args.regions) if args.regions else None
        get_item = (read_json(args.snapshot).get if args.snapshot else
                    PostgresDbPart(os.environ.get('DATABASE_URL')).db_get_item)
        config = yaml.safe_load(args.config.read_text(encoding='utf-8-sig'))
        result = inspect_storage(text.strip(), images, sections, inventory, get_item,
                                 KoreanFirstParser(offline=True), HybridMatcher(load_config(), offline=True),
                                 config, args.device, regions=regions)
    except (ValueError, KeyError, AttributeError, TypeError, OSError, RuntimeError, ImportError,
            yaml.YAMLError, cv2.error, np.linalg.LinAlgError) as exc:
        result = {'status': 'failed', 'error': str(exc), 'robot_authorized': False}
    print(json.dumps(result, indent=2, allow_nan=False))
    return {'count_match': 0, 'failed': 1}.get(result['status'], 2)


if __name__ == '__main__':
    raise SystemExit(main())
