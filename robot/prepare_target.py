"""Export a vision target for offline robot integration. Never connects to hardware."""
import argparse
import json
from pathlib import Path

from vision.installation_coordinates import coordinate_chain, load_installation


def prepare_target(report, object_id, config):
    chain=coordinate_chain(report,config)
    matches=[row for row in chain['objects'] if row['object_id']==object_id]
    if len(matches)!=1:
        raise ValueError('Requested object ID is absent')
    target=matches[0]
    reasons=['controller_base_and_tcp_not_validated',
             'ik_model_and_joint_zero_mapping_not_validated',
             'studio_motion_transport_not_connected']
    if target['status']!='preview_only':
        reasons.insert(0,target['status'])
    return {'schema':'robot_target_preview.v1','object_id':object_id,
            'status':'blocked_for_motion','robot_authorized':False,
            'blocking_reasons':reasons,'target':target,
            'coordinate_chain':chain,
            'transport':{'driver':'physicalai_so101_plugin','unit':'normalized',
                         'body_range':[-100,100],'gripper_range':[0,100],
                         'joint_targets':None}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--object-id',type=int,required=True)
    parser.add_argument('--installation-config',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config=load_installation(args.installation_config) if args.installation_config else load_installation()
    report=json.loads(args.report.read_text(encoding='utf-8-sig'))
    result=prepare_target(report,args.object_id,config)
    result['source_report']=str(args.report.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'output':str(args.output.resolve()),'target':result['target'],
                      'blocking_reasons':result['blocking_reasons']},indent=2))


if __name__=='__main__':
    main()
