import { describe, expect, it, rs } from '@rstest/core';
import { act, screen, within } from '@testing-library/react';

import { render } from '../../test-utils/render';
import { JointComparison } from './joint-comparison';
import { useRuntimeSession } from './runtime-session-provider';

rs.mock('./runtime-session-provider', () => ({ useRuntimeSession: rs.fn() }));

const setup = () => {
    const follower = Object.fromEntries(
        ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'].map((name) => [
            `${name}.pos`,
            10,
        ])
    );
    const leader = { ...follower, 'shoulder_pan.pos': 22, 'elbow_flex.pos': 3 };
    const session = {
        state: { connected: true },
        observation: { current: follower },
        leaderObservation: { current: leader as Record<string, number> | undefined },
        observationAt: { current: performance.now() },
    };
    rs.mocked(useRuntimeSession).mockReturnValue(session as unknown as ReturnType<typeof useRuntimeSession>);
    return session;
};

describe('Live joint comparison', () => {
    it('shows measured values, signed differences and adjustment direction', () => {
        setup();
        render(<JointComparison />);
        expect(screen.getByText('리더 자세 조정 필요')).toBeInTheDocument();
        const rows = screen.getAllByRole('row');
        expect(within(rows[1]).getAllByText('10.00')).toHaveLength(6);
        expect(within(rows[2]).getByText('22.00')).toBeInTheDocument();
        expect(within(rows[3]).getByText(/\+12.00/)).toBeInTheDocument();
        expect(within(rows[3]).getByText('리더 값 낮추기')).toBeInTheDocument();
        expect(within(rows[3]).getByText('리더 값 높이기')).toBeInTheDocument();
    });

    it('updates readings and clears them when the stream becomes stale', async () => {
        const session = setup();
        render(<JointComparison />);
        session.leaderObservation.current = { ...session.observation.current };
        expect(await screen.findByText('모든 관절이 정렬 범위 안')).toBeInTheDocument();
        act(() => {
            session.observationAt.current = performance.now() - 1000;
        });
        expect(await screen.findByText('관절 데이터 대기 · 연결 확인')).toBeInTheDocument();
        const rows = screen.getAllByRole('row');
        expect(within(rows[1]).getAllByText('—')).toHaveLength(6);
    });

    it('does not treat a missing leader as aligned', () => {
        const session = setup();
        session.leaderObservation.current = undefined;
        render(<JointComparison />);
        expect(screen.getByText('관절 데이터 대기 · 연결 확인')).toBeInTheDocument();
        expect(screen.queryByText('모든 관절이 정렬 범위 안')).not.toBeInTheDocument();
    });
});
