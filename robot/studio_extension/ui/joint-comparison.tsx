import { useEffect, useState } from 'react';

import { useRuntimeSession } from './runtime-session-provider';

import classes from './joint-comparison.module.css';

const JOINTS = [
    ['shoulder_pan', '어깨 회전'],
    ['shoulder_lift', '어깨 상하'],
    ['elbow_flex', '팔꿈치'],
    ['wrist_flex', '손목 굽힘'],
    ['wrist_roll', '손목 회전'],
    ['gripper', '그리퍼'],
] as const;

interface JointSnapshot {
    follower?: Record<string, number>;
    leader?: Record<string, number>;
}

const format = (value: number | undefined) => (value !== undefined && Number.isFinite(value) ? value.toFixed(2) : '—');

export const JointComparison = () => {
    const { observation, leaderObservation, observationAt, state } = useRuntimeSession();
    const [snapshot, setSnapshot] = useState<JointSnapshot>({});

    useEffect(() => {
        const update = () => {
            const fresh = state.connected && performance.now() - observationAt.current <= 500;
            setSnapshot(fresh ? { follower: observation.current, leader: leaderObservation.current } : {});
        };
        update();
        const timer = setInterval(update, 100);
        return () => clearInterval(timer);
    }, [observation, leaderObservation, observationAt, state.connected]);

    const rows = JOINTS.map(([joint, label]) => {
        const follower = snapshot.follower?.[`${joint}.pos`];
        const leader = snapshot.leader?.[`${joint}.pos`];
        const difference =
            follower !== undefined && leader !== undefined && Number.isFinite(follower) && Number.isFinite(leader)
                ? leader - follower
                : undefined;
        return { joint, label, follower, leader, difference };
    });
    const complete = rows.every((row) => row.difference !== undefined);
    const aligned = complete && rows.every((row) => row.difference !== undefined && Math.abs(row.difference) <= 5);

    return (
        <section className={classes.panel} aria-label='리더·팔로워 실시간 관절 비교'>
            <div className={classes.heading}>
                <strong>리더·팔로워 실시간 관절값</strong>
                <span className={aligned ? classes.matched : classes.pending}>
                    {!complete
                        ? '관절 데이터 대기 · 연결 확인'
                        : aligned
                          ? '모든 관절이 정렬 범위 안'
                          : '리더 자세 조정 필요'}
                </span>
            </div>
            <div className={classes.scroll}>
                <table className={classes.table}>
                    <caption className={classes.caption}>
                        리더 값을 팔로워 값에 맞추세요 · 전 관절 차이 ±5 이내 · 보정 위치값, 각도 단위 아님
                    </caption>
                    <thead>
                        <tr>
                            <th scope='col'>관절</th>
                            {rows.map((row) => (
                                <th scope='col' key={row.joint}>
                                    {row.label}
                                    <small>{row.joint}</small>
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <th scope='row'>팔로워</th>
                            {rows.map((row) => (
                                <td key={row.joint}>{format(row.follower)}</td>
                            ))}
                        </tr>
                        <tr>
                            <th scope='row'>리더</th>
                            {rows.map((row) => (
                                <td key={row.joint}>{format(row.leader)}</td>
                            ))}
                        </tr>
                        <tr>
                            <th scope='row'>차이 · 리더 − 팔로워</th>
                            {rows.map((row) => (
                                <td
                                    key={row.joint}
                                    className={
                                        row.difference !== undefined && Math.abs(row.difference) <= 5
                                            ? classes.matched
                                            : classes.pending
                                    }
                                >
                                    {row.difference !== undefined && row.difference > 0 ? '+' : ''}
                                    {format(row.difference)}
                                    <small>
                                        {row.difference === undefined
                                            ? '대기'
                                            : Math.abs(row.difference) <= 5
                                              ? '범위 안'
                                              : row.difference > 0
                                                ? '리더 값 낮추기'
                                                : '리더 값 높이기'}
                                    </small>
                                </td>
                            ))}
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    );
};
