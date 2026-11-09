"""Preview a crop from a top-view photo without running YOLO or Qwen."""

import argparse
import json
from pathlib import Path
from tkinter import TclError

import cv2
import numpy as np
import yaml

from agents.vision_adapter import calibration_ok
from vision.aruco.calibration import calibrate, crop_section
from vision.aruco.detector import detect_markers
from vision.scripts.region_editor import edit_regions
from vision.section_regions import crop_pixels, load_regions
from vision.sequence import write_report


ROOT = Path(__file__).resolve().parents[2]


def select_bounds(image, window):
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    try:
        x, y, width, height = cv2.selectROI(window, image, showCrosshair=True)
    finally:
        cv2.destroyWindow(window)
    return [x, y, x + width, y + height] if width and height else None


def save_selections(image, path, names):
    image_size = list(image.shape[1::-1])
    saved = load_regions(path) if path.exists() else {'image_size_px': image_size, 'regions': {}}
    if saved['image_size_px'] != image_size:
        raise ValueError('Reference resolution changed. Draw regions into a new JSON file.')
    saved = edit_regions(image, saved, names)
    if saved is None:
        print('Selection cancelled. Region file was not changed.')
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    write_report(path, saved)
    print(json.dumps({**saved, 'output': str(path)}))
    return 0


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--image', required=True, type=Path, help='Saved top-view photo')
    bounds = cli.add_mutually_exclusive_group()
    bounds.add_argument('--bounds-px', type=int, nargs=4, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'),
                        help='Crop in original-image pixels. Right and bottom are exclusive.')
    bounds.add_argument('--bounds-mm', type=float, nargs=4, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'),
                        help='Crop in the calibrated ArUco worktable frame. Matches storage bounds_mm.')
    bounds.add_argument('--draw', nargs='*', metavar='NAME', help='Open the cabinet editor, optionally with region names')
    bounds.add_argument('--region', help='Preview one saved region by name')
    cli.add_argument('--regions', type=Path, help='Region JSON used with --draw or --region')
    cli.add_argument('--config', type=Path, default=ROOT / 'vision/configs/vision.yaml')
    cli.add_argument('--output', type=Path, help='Output PNG path')
    cli.add_argument('--show', action='store_true', help='Show the crop when bounds are supplied')
    args = cli.parse_args(argv)
    drawing = args.draw is not None
    if (drawing or args.region is not None) != bool(args.regions):
        cli.error('--regions is required with --draw or --region and only used with those modes')
    if args.draw and (len(set(args.draw)) != len(args.draw) or any(not name.strip() for name in args.draw)):
        cli.error('Use distinct, non-empty region names')
    interactive = not (args.bounds_px or args.bounds_mm or drawing or args.region is not None)
    output = (args.output or ROOT / 'outputs/section_preview' / f'{args.image.stem}-crop.png').resolve()

    try:
        if args.image.resolve() == output:
            raise ValueError('Output must be different from the original photo')
        image = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'Cannot read image: {args.image}')

        if drawing:
            path = args.regions.resolve()
            if path.suffix.lower() != '.json' or args.image.resolve() == path:
                raise ValueError('Save named regions to a separate .json file')
            return save_selections(image, path, args.draw)
        if args.region is not None:
            if args.regions.resolve() == output:
                raise ValueError('Crop output must be different from the region file')
            saved = load_regions(args.regions)
            if saved['image_size_px'] != list(image.shape[1::-1]):
                raise ValueError('Photo resolution differs from the region reference')
            region_bounds = saved['regions'][args.region]
            crop = crop_pixels(image, region_bounds)
            coordinates = {'region': args.region, 'bounds_px': region_bounds}
        elif args.bounds_mm is not None:
            aruco = yaml.safe_load(args.config.read_text(encoding='utf-8-sig'))['aruco']
            markers = detect_markers(image, aruco.get('dictionary', 'DICT_4X4_50'))
            calibration = calibrate(markers, aruco)
            valid, reason = calibration_ok({'calibration': calibration})
            if not valid:
                raise ValueError(f'ArUco calibration unavailable: {reason}')
            crop = crop_section(image, calibration['homography'], args.bounds_mm)
            if crop is None:
                raise ValueError('Section must be fully visible in the photo')
            coordinates = {'bounds_mm': args.bounds_mm}
        else:
            if interactive:
                args.bounds_px = select_bounds(image, 'Select region - drag then Enter, c to cancel')
                if args.bounds_px is None:
                    print('Selection cancelled.')
                    return 2
            crop = crop_pixels(image, args.bounds_px)
            coordinates = {'bounds_px': args.bounds_px}

        success, png = cv2.imencode('.png', crop)
        if not success:
            raise OSError('Cannot encode crop')
        output.parent.mkdir(parents=True, exist_ok=True)
        png.tofile(output)
        print(json.dumps({**coordinates, 'size_px': list(crop.shape[1::-1]), 'output': str(output)}), flush=True)
        if interactive or args.show:
            cv2.imshow('Section crop - press any key to close', crop)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, cv2.error, np.linalg.LinAlgError, TclError) as exc:
        cli.exit(1, f'{exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
