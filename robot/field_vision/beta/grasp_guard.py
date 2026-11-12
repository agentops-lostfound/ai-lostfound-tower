"""접촉 후보 조기 정지 결정. 저항/영상은 잡힘 성공과 별개이다."""


def decide(start, current, initial_vision, vision, travel_ticks):
    load_delta=current['load_magnitude']-start['load_magnitude']
    current_delta=current['current_magnitude']-start['current_magnitude']
    # These are conservative raw-unit trial thresholds, not calibrated force.
    resistance=load_delta>=15 or current_delta>=8
    new_visual=bool(vision.get('valid') and vision.get('bilateral_contact_candidate') and
                    not initial_vision.get('bilateral_contact_candidate'))
    stop=bool(travel_ticks>=12 and (resistance or new_visual))
    return {'stop_closing':stop,'contact_candidate':stop,'grasp_success':False,
        'load_delta_raw':load_delta,'current_delta_raw':current_delta,'resistance_rise':resistance,
        'new_visual_contact_candidate':new_visual,
        'vision_ambiguous_before_closing':bool(initial_vision.get('bilateral_contact_candidate')),
        'reason':'저항 상승 또는 새 양쪽 영상 접촉 후보에서 추가 닫기 중단' if stop else '접촉 미확정'}
