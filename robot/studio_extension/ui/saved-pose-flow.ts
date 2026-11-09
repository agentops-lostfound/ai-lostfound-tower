/** The save ACK is the boundary between training data and deterministic return. */
export const finishGraspAndReturn = async (steps: {
    hold: () => Promise<unknown>;
    save: () => Promise<unknown>;
    move: () => Promise<unknown>;
    cancelled: () => boolean;
}) => {
    await steps.hold();
    if (steps.cancelled()) throw new Error('복귀가 취소되었습니다.');
    await steps.save();
    if (steps.cancelled()) throw new Error('저장 완료. 복귀는 취소되었습니다.');
    await steps.move();
};
