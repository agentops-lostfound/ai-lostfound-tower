import { describe, expect, it, rs } from '@rstest/core';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { render } from '../../test-utils/render';
import { useRuntimeSession } from './runtime-session-provider';
import { SavedPoseControls } from './saved-pose-controls';

rs.mock('./runtime-session-provider', () => ({ useRuntimeSession: rs.fn() }));

const session = (
    options: {
        recording?: boolean;
        moving?: boolean;
        wrongRobot?: boolean;
        unconfirmed?: boolean;
        noTarget?: boolean;
        holdingTarget?: boolean;
    } = {}
) => {
    const move = rs.fn();
    rs.mocked(useRuntimeSession).mockReturnValue({
        state: {
            connected: true,
            follower_source: 'hold',
            has_leader: true,
            is_recording: options.recording ?? false,
            saved_pose_names: ['home', 'pose_1', 'pose_8', 'open', 'outlet_return_1'],
            saved_pose_robot_id: options.wrongRobot ? 'other' : 'follower',
            saved_pose_status: options.moving ? 'moving' : options.holdingTarget ? 'holding_target' : 'idle',
            approach_pose: options.unconfirmed || options.noTarget ? null : 'pose_8',
            saved_pose_name: options.unconfirmed ? 'pose_1' : null,
        },
        environment: { robots: [{ robot: { id: 'follower' } }] },
        moveSavedPose: { mutate: move },
        stopSavedPose: { mutate: rs.fn() },
        setFollowerSource: { mutate: rs.fn() },
        poseFlowBusy: false,
        observation: { current: undefined },
        leaderObservation: { current: undefined },
        observationAt: { current: 0 },
    } as unknown as ReturnType<typeof useRuntimeSession>);
    return move;
};

describe('Studio saved pose controls', () => {
    it('requires path confirmation and applies all six saved joints', async () => {
        const move = session();
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        const button = screen.getByRole('button', { name: '선택 자세로 이동' });
        expect(button).toBeDisabled();
        await user.click(screen.getByRole('checkbox'));
        await user.click(button);
        expect(move).toHaveBeenCalledWith({
            pose: 'pose_1',
            returnToApproach: false,
            includeGripper: true,
            durationSeconds: 3,
        });
        expect(button).toBeDisabled();
    });
    it('records only the grasp and offers save-then-return while recording', async () => {
        const move = session({ recording: true });
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        expect(screen.getByRole('combobox', { name: '저장 자세' })).toBeDisabled();
        expect(screen.getByRole('button', { name: '선택 자세로 이동' })).toBeDisabled();
        await user.click(screen.getByRole('checkbox'));
        await user.click(screen.getByRole('button', { name: '집기 완료 · 저장 후 복귀' }));
        expect(move).toHaveBeenCalledWith({
            pose: 'pose_8',
            returnToApproach: true,
            includeGripper: true,
            durationSeconds: 3,
        });
        expect(screen.getByText(/복귀 위치: pose_8/)).toBeInTheDocument();
    });
    it('leaves stop available while moving', () => {
        session({ moving: true });
        render(<SavedPoseControls />);
        expect(screen.getByRole('button', { name: '선택 자세로 이동' })).toBeDisabled();
        expect(screen.getByRole('button', { name: '이동 정지 / HOLD' })).toBeEnabled();
    });
    it('sends the selected five-second profile and renews path confirmation', async () => {
        const move = session();
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        const button = screen.getByRole('button', { name: '선택 자세로 이동' });
        await user.click(screen.getByRole('checkbox'));
        await user.selectOptions(screen.getByRole('combobox', { name: '이동 시간' }), '5');
        expect(button).toBeDisabled();
        await user.click(screen.getByRole('checkbox'));
        await user.click(button);
        expect(move).toHaveBeenCalledWith({
            pose: 'pose_1',
            returnToApproach: false,
            includeGripper: true,
            durationSeconds: 5,
        });
    });
    it('uses the chosen four-second profile for save-and-return', async () => {
        const move = session({ recording: true });
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        await user.selectOptions(screen.getByRole('combobox', { name: '이동 시간' }), '4');
        await user.click(screen.getByRole('checkbox'));
        await user.click(screen.getByRole('button', { name: '집기 완료 · 저장 후 복귀' }));
        expect(move).toHaveBeenCalledWith({
            pose: 'pose_8',
            returnToApproach: true,
            includeGripper: true,
            durationSeconds: 4,
        });
    });
    it('allows the next outlet pose while the previous target is held', async () => {
        const move = session({ holdingTarget: true, unconfirmed: true });
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        expect(screen.getByText(/목표값 유지 · 도착 확인 중/)).toBeInTheDocument();
        await user.selectOptions(screen.getByRole('combobox', { name: '저장 자세' }), 'outlet_return_1');
        await user.click(screen.getByRole('checkbox'));
        await user.click(screen.getByRole('button', { name: '선택 자세로 이동' }));
        expect(move).toHaveBeenCalledWith({
            pose: 'outlet_return_1',
            returnToApproach: false,
            includeGripper: true,
            durationSeconds: 3,
        });
    });
    it('returns after a non-recorded grasp without starting an episode', async () => {
        const move = session();
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        await user.click(screen.getByRole('checkbox'));
        await user.click(screen.getByRole('button', { name: '집기 완료 · 어프로치 복귀' }));
        expect(move).toHaveBeenCalledWith({
            pose: 'pose_8',
            returnToApproach: true,
            includeGripper: true,
            durationSeconds: 3,
        });
        expect(screen.queryByRole('button', { name: '집기 완료 · 저장 후 복귀' })).not.toBeInTheDocument();
    });
    it('can retry the original approach after an unconfirmed move during a non-recorded test', async () => {
        const move = session({ unconfirmed: true });
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        await user.selectOptions(screen.getByRole('combobox', { name: '저장 자세' }), 'pose_8');
        await user.click(screen.getByRole('checkbox'));
        await user.click(screen.getByRole('button', { name: '집기 완료 · 어프로치 복귀' }));
        expect(move).toHaveBeenCalledWith({
            pose: 'pose_1',
            returnToApproach: false,
            includeGripper: true,
            durationSeconds: 3,
        });
        expect(screen.getByText(/복귀 위치: pose_1 \(도착 미확인\)/)).toBeInTheDocument();
    });
    it('requires an attempted approach before offering return', async () => {
        session({ noTarget: true });
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        await user.click(screen.getByRole('checkbox'));
        expect(screen.getByRole('button', { name: '집기 완료 · 어프로치 복귀' })).toBeDisabled();
    });
    it('still requires confirmed arrival for recording and save-then-return', async () => {
        session({ unconfirmed: true, recording: true });
        const user = userEvent.setup();
        render(<SavedPoseControls />);
        await user.click(screen.getByRole('checkbox'));
        expect(screen.getByRole('button', { name: '집기 완료 · 저장 후 복귀' })).toBeDisabled();
    });
    it('disables movement for another follower', () => {
        session({ wrongRobot: true });
        render(<SavedPoseControls />);
        expect(screen.getByRole('checkbox')).toBeDisabled();
        expect(screen.getByRole('button', { name: '선택 자세로 이동' })).toBeDisabled();
    });
});
