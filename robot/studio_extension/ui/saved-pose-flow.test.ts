import { describe, expect, it, rs as vi } from '@rstest/core';

import { finishGraspAndReturn } from './saved-pose-flow';

describe('grasp recording boundary', () => {
    it('does not move until save has acknowledged', async () => {
        let saved: () => void = () => {};
        const order: string[] = [];
        const pending = finishGraspAndReturn({
            hold: async () => { order.push('hold'); },
            save: () => new Promise<void>((resolve) => { order.push('save'); saved = resolve; }),
            move: async () => { order.push('move'); }, cancelled: () => false,
        });
        await Promise.resolve();
        expect(order).toEqual(['hold', 'save']);
        saved();
        await pending;
        expect(order).toEqual(['hold', 'save', 'move']);
    });
    it('does not return after a save failure', async () => {
        const move = vi.fn();
        await expect(finishGraspAndReturn({
            hold: async () => {}, save: async () => { throw new Error('disk full'); },
            move, cancelled: () => false,
        })).rejects.toThrow('disk full');
        expect(move).not.toHaveBeenCalled();
    });
    it('stop during saving cancels the queued return', async () => {
        let stopped = false;
        const move = vi.fn();
        await expect(finishGraspAndReturn({
            hold: async () => {}, save: async () => { stopped = true; },
            move, cancelled: () => stopped,
        })).rejects.toThrow();
        expect(move).not.toHaveBeenCalled();
    });
});
