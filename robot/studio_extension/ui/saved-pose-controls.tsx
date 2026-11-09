import { useId, useState } from 'react';

import { Button, Checkbox, Flex, Text } from '@geti-ui/ui';

import { JointComparison } from './joint-comparison';
import { useRuntimeSession } from './runtime-session-provider';

export const SavedPoseControls = () => {
    const { state, environment, moveSavedPose, stopSavedPose, setFollowerSource, poseFlowBusy, dataset } =
        useRuntimeSession();
    const [pose, setPose] = useState('pose_1');
    const [durationSeconds, setDurationSeconds] = useState(3);
    const [approved, setApproved] = useState(false);
    const selectId = useId();
    const durationId = useId();
    const names = state.saved_pose_names ?? [];
    const moving = state.saved_pose_status === 'moving';
    const statusLabel =
        state.saved_pose_status === 'holding_target' ? '목표값 유지 · 도착 확인 중' : state.saved_pose_status;
    const busy = moving || poseFlowBusy;
    const matchingRobot = environment.robots?.[0]?.robot.id === state.saved_pose_robot_id;
    const disabled = !state.connected || !matchingRobot || busy;
    const requestedApproach = /^pose_[1-8]$/.test(state.saved_pose_name ?? '') ? state.saved_pose_name : null;
    const returnPose = state.approach_pose ?? requestedApproach;
    const canReturn = !!returnPose && (!state.is_recording || !!state.approach_pose);
    if (names.length === 0) return null;

    const run = (returning: boolean) => {
        setApproved(false);
        moveSavedPose.mutate({
            pose: returning ? (returnPose ?? pose) : pose,
            returnToApproach: returning && !!state.approach_pose,
            includeGripper: true,
            durationSeconds,
        });
    };

    return (
        <Flex direction='column' gap='size-100' margin='size-150'>
            <Flex gap='size-150' alignItems='center' wrap='wrap'>
                <label htmlFor={selectId}>저장 자세</label>
                <select
                    id={selectId}
                    value={pose}
                    disabled={disabled || state.is_recording}
                    onChange={(event) => {
                        setPose(event.target.value);
                        setApproved(false);
                    }}
                >
                    {names.map((name) => (
                        <option key={name} value={name}>
                            {name}
                        </option>
                    ))}
                </select>
                <label htmlFor={durationId}>이동 시간</label>
                <select
                    id={durationId}
                    value={durationSeconds}
                    disabled={disabled}
                    onChange={(event) => {
                        setDurationSeconds(Number(event.target.value));
                        setApproved(false);
                    }}
                >
                    {[3, 4, 5].map((seconds) => (
                        <option key={seconds} value={seconds}>
                            {seconds}초
                        </option>
                    ))}
                </select>
                <Checkbox isSelected={approved} isDisabled={disabled} onChange={setApproved}>
                    물건을 충분히 들었고 이동 경로가 비어 있습니다
                </Checkbox>
                <Button isDisabled={disabled || state.is_recording || !approved} onPress={() => run(false)}>
                    선택 자세로 이동
                </Button>
                <Button isDisabled={disabled || !approved || !canReturn} onPress={() => run(true)}>
                    {state.is_recording ? '집기 완료 · 저장 후 복귀' : '집기 완료 · 어프로치 복귀'}
                </Button>
                <Button variant='negative' isDisabled={!state.connected} onPress={() => stopSavedPose.mutate()}>
                    이동 정지 / HOLD
                </Button>
                {dataset && (
                    <Button
                        isDisabled={disabled || state.is_recording || !state.has_leader || setFollowerSource.isPending}
                        onPress={() => setFollowerSource.mutate(state.follower_source === 'teleop' ? 'hold' : 'teleop')}
                    >
                        {state.follower_source === 'teleop' ? '텔레 끄기' : '리더 정렬 후 텔레 켜기'}
                    </Button>
                )}
            </Flex>
            <Text>
                연결 유지 · {state.follower_source} · {statusLabel} · 복귀 위치: {returnPose ?? '미지정'}
                {returnPose && !state.approach_pose ? ' (도착 미확인)' : ''} · 그리퍼 포함 저장된 6축 값 적용
            </Text>
            <Text>선택한 시간에 맞춰 이동합니다. 시간이 지나도 목표값을 유지하며 도착을 기다립니다.</Text>
            {!state.is_recording && (
                <Text>녹화 없이 집기 시험 · 선택 자세로 이동 → 리더 정렬 후 텔레 켜기 → 집기 완료 · 어프로치 복귀</Text>
            )}
            <JointComparison />
            {!matchingRobot && <Text>이 자세 파일에 지정된 Follower에서만 사용할 수 있습니다.</Text>}
            {(state.saved_pose_error || moveSavedPose.error) && (
                <Text>{state.saved_pose_error || moveSavedPose.error?.message}</Text>
            )}
        </Flex>
    );
};
