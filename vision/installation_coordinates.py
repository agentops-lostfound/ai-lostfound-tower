"""Read-only work-plane to provisional robot-installation coordinate preview.

No robot imports, connections, commands or authorization. This is an installation
estimate, not a measured camera-to-controller/TCP calibration.
"""
import argparse
import json
import hashlib
import math
from pathlib import Path
import yaml

DEFAULT_CONFIG = Path(__file__).parent/'configs/installation.yaml'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                      allow_nan=False).encode()).hexdigest()


def marker_layout(markers):
    return {str(k):[[float(v) for v in point] for point in corners]
            for k,corners in markers.items()}


def work_context(aruco_config):
    """Snapshot the surveyed plane, not camera pixels or a robot frame."""
    layout=marker_layout(aruco_config.get('markers_mm',{}))
    return {'units':'mm','markers_mm':layout,'layout_sha256':fingerprint(layout)}


def coordinate_chain(report, config):
    """Recompute bbox center -> source homography -> configured installation XY/Z.

    A report without a layout snapshot is never silently assigned today's frame.
    """
    from .aruco.calibration import transform_center
    from agents.vision_adapter import calibration_ok
    context=report.get('coordinate_context')
    expected=marker_layout(config['source_markers_mm'])
    layout_ok=(isinstance(context,dict) and context.get('units')=='mm'
               and context.get('markers_mm')==expected
               and context.get('layout_sha256')==fingerprint(expected))
    valid,_=calibration_ok(report)
    rows=[]
    objects=report.get('objects',[])
    ids=[o.get('id') for o in objects]
    if any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Coordinate chain requires unique integer object IDs')
    for obj in objects:
        row={'object_id':obj['id'],'robot_authorized':False,'status':'unavailable'}
        bbox=obj.get('bbox')
        if (not isinstance(bbox,(list,tuple)) or len(bbox)!=4
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in bbox)
                or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]):
            row['status']='invalid_bbox'
        else:
            center=[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2]
            row.update(bbox_px=list(bbox),center_px=center)
            if not layout_ok:
                row['status']='work_frame_unverified'
            elif not valid or obj.get('calibration_valid') is not True:
                row['status']='calibration_unavailable'
            else:
                try:
                    import numpy as np
                    h=np.asarray(report['calibration']['homography'],dtype=float)
                    if h.shape!=(3,3) or not np.isfinite(h).all() or np.linalg.matrix_rank(h)<3:
                        raise ValueError('Invalid homography')
                    transformed=transform_center(center,report['calibration'])
                    xy=transformed['center_world_mm']
                    if xy is None:
                        raise ValueError('Unstable pixel transform')
                    row.update(work_xy_mm=xy,**preview_point(xy,config),status='preview_only')
                except (ValueError,TypeError,KeyError):
                    row['status']='invalid_homography'
        rows.append(row)
    return {'schema':'coordinate_chain.v1','units':'mm','pixel_units':'px',
            'source_image':report.get('image_path'),'captured_at':report.get('captured_at'),
            'work_frame_id':config['work_frame_id'], 'target_frame_id':config['frame_id'],
            'config_version':config['config_version'],'config_sha256':fingerprint(config),
            'config_snapshot':config,'source_context':context,
            'controller_frame_verified':config.get('controller_frame_verified',False),
            'robot_authorized':False,'objects':rows}


def load_installation(path=DEFAULT_CONFIG):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    transform = config['work_xy_to_installation_xy']
    matrix, offset = transform['matrix'], transform['offset_mm']
    def finite(v):
        return type(v) in (int, float) and math.isfinite(v)
    if (not isinstance(matrix, list) or len(matrix)!=2
            or any(not isinstance(row,list) or len(row)!=2 for row in matrix)
            or not all(finite(v) for row in matrix for v in row)
            or not isinstance(offset,list) or len(offset)!=2 or not all(map(finite,offset))
            or not finite(config['approach_z_mm'])):
        raise ValueError('Installation transform must contain finite mm values')
    # No arbitrary scaling of measured millimetres. Work-plane handedness may differ.
    for i in range(2):
        for j in range(2):
            if abs(sum(matrix[k][i]*matrix[k][j] for k in range(2))-(1 if i==j else 0))>1e-8:
                raise ValueError('XY transform must preserve lengths')
    return config


def preview_point(center_world_mm, config):
    if (not isinstance(center_world_mm,(list,tuple)) or len(center_world_mm)!=2
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in center_world_mm)):
        raise ValueError('Expected finite work-plane XY in mm')
    transform=config['work_xy_to_installation_xy']
    xy=[sum(a*b for a,b in zip(row,center_world_mm))+offset
        for row,offset in zip(transform['matrix'],transform['offset_mm'])]
    return {'frame_id':config['frame_id'], 'xy_mm':xy,
            'approach_xyz_mm':[*xy,config['approach_z_mm']],
            'horizontal_distance_mm':math.hypot(*xy),
            'robot_authorized':False,
            'notice':'Provisional installation frame; controller/TCP calibration and physical checks pending.'}


def preview_report(report, config):
    rows=[]
    calibration=report.get('calibration',{})
    for obj in report.get('objects',[]):
        row={'object_id':obj['id'],'center_px':obj.get('center_px'),
             'work_xy_mm':obj.get('center_world_mm'),'robot_authorized':False}
        if calibration.get('valid') is not True or obj.get('calibration_valid') is not True:
            row['status']='calibration_unavailable'
        elif obj.get('center_world_mm') is None:
            row['status']='coordinates_unavailable'
        else:
            row.update(preview_point(obj['center_world_mm'],config),status='preview_only')
        rows.append(row)
    return {'schema':'installation_coordinate_preview.v1','robot_authorized':False,
            'controller_frame_verified':config.get('controller_frame_verified',False),
            'source_sequence_status':report.get('sequence',{}).get('status'),
            'notice':'Geometric preview only, including unclassified detections; no target selected or robot action permitted.',
            'objects':rows}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--report',type=Path,required=True)
    cli.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    result=coordinate_chain(json.loads(args.report.read_text(encoding='utf-8-sig')),load_installation(args.config))
    result['source_report']=str(args.report.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':
    main()
