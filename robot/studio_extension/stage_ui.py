"""Apply anchored UI edits to a staging copy of Studio, never the running UI."""
from pathlib import Path
import argparse
import shutil
from robot.studio_extension.stage import replace


def patch_joint_comparison_ui(root):
    provider = root / "src/features/robots/runtime-session-provider.tsx"
    text = provider.read_text(encoding="utf-8")
    text = replace(text, "    actions?: Record<string, number> | null;", "    actions?: Record<string, number> | null;\n    leader?: Record<string, number> | null;")
    text = replace(text, "    actions: RefObject<Record<string, number> | undefined>;", "    actions: RefObject<Record<string, number> | undefined>;\n    leaderObservation: RefObject<Record<string, number> | undefined>;\n    observationAt: RefObject<number>;")
    text = replace(text, "    const actions = useRef<Record<string, number> | undefined>(undefined);", "    const actions = useRef<Record<string, number> | undefined>(undefined);\n    const leaderObservation = useRef<Record<string, number> | undefined>(undefined);")
    text = replace(text, "                actions.current = message.actions ?? undefined;", "                actions.current = message.actions ?? undefined;\n                leaderObservation.current = message.leader ?? undefined;")
    text = replace(text, "            setState(createRuntimeSessionState());", "            observationAt.current = 0;\n            leaderObservation.current = undefined;\n            setState(createRuntimeSessionState());")
    text = replace(text, "                observation,\n                actions,", "                observation,\n                actions,\n                leaderObservation,\n                observationAt,")
    provider.write_text(text, encoding="utf-8", newline="\n")


def patch_ui(root):
    provider = root / "src/features/robots/runtime-session-provider.tsx"
    text = provider.read_text(encoding="utf-8")
    text = replace(text, "createContext, ReactNode", "createContext, useEffect, ReactNode")
    text = replace(text, "type InferenceDevice =", "import { finishGraspAndReturn } from './saved-pose-flow';\n\ntype InferenceDevice =")
    text = replace(text, "    episodes_recorded: number;", '''    episodes_recorded: number;
    saved_pose_status?: string;
    saved_pose_name?: string | null;
    saved_pose_names?: string[];
    saved_pose_robot_id?: string;
    saved_pose_token?: string | null;
    saved_pose_error?: string | null;
    approach_pose?: string | null;''')
    text = replace(text, "    readyForInference: boolean;", '''    moveSavedPose: MutationResult<{pose: string; returnToApproach: boolean; includeGripper: boolean; durationSeconds: number}>;
    stopSavedPose: MutationResult;
    poseFlowBusy: boolean;
    readyForInference: boolean;''')
    text = replace(text, "    const devices = handshakeDevices(props.environment);", '''    const devices = handshakeDevices(props.environment);
    const ownedMove = useRef<string | null>(null);
    const cancelGeneration = useRef(0);
    const observationAt = useRef(0);
    const flowLock = useRef(false);''')
    text = replace(text, "            setFollowerSource.mutate('teleop');", "            // Begin in HOLD so the operator can position before recording.")
    text = replace(text, "                observation.current = message.data", "                observationAt.current = performance.now();\n                observation.current = message.data")
    text = replace(text, "                    episodes_recorded: next.episodes_recorded ?? 0,", '''                    episodes_recorded: next.episodes_recorded ?? 0,
                    saved_pose_status: next.saved_pose_status,
                    saved_pose_name: next.saved_pose_name,
                    saved_pose_names: next.saved_pose_names,
                    saved_pose_robot_id: next.saved_pose_robot_id,
                    saved_pose_token: next.saved_pose_token,
                    saved_pose_error: next.saved_pose_error,
                    approach_pose: next.approach_pose,''')
    text = replace(text, "            if (message.event === 'error') {", '''            if (message.event === 'state') {
                const next = message.data as Partial<RuntimeSessionState>;
                if (next.saved_pose_status !== 'moving') ownedMove.current = null;
            }
            if (message.event === 'error') {''')
    text = replace(text, "        onClose: () => {", "        onClose: () => {\n            ownedMove.current = null;\n            cancelGeneration.current += 1;")
    text = replace(text, "    const loadModel = useMutation({", '''    const send = socket.sendJsonMessage;
    useEffect(() => {
        const timer = setInterval(() => {
            if (ownedMove.current && socket.readyState === 1) {
                send({event: 'saved_pose_heartbeat', data: {token: ownedMove.current}}, false);
            }
        }, 200);
        return () => clearInterval(timer);
    }, [send, socket.readyState]);

    const loadModel = useMutation({''')
    insertion = '''    const stopSavedPose = useMutation({
        meta: { skipInvalidation: true },
        mutationFn: async () => {
            cancelGeneration.current += 1;
            ownedMove.current = null;
            if (socket.readyState !== 1) throw new Error('Robot connection is unavailable');
            return socket.sendJsonMessageAndWait<RuntimeApiJsonResponse>(
                {event: 'stop_saved_pose', data: {}},
                ({event, data}) => event === 'state' && data?.follower_source === 'hold' && data?.saved_pose_status !== 'moving'
            );
        },
    });

    const moveSavedPose = useMutation({
        meta: { skipInvalidation: true },
        mutationFn: async (options: {pose: string; returnToApproach: boolean; includeGripper: boolean; durationSeconds: number}) => {
            if (flowLock.current) throw new Error('A pose operation is already pending');
            if (socket.readyState !== 1 || performance.now() - observationAt.current > 500) {
                throw new Error('Fresh connected robot observations required');
            }
            if (state.saved_pose_status === 'moving') throw new Error('Stop the current move first');
            flowLock.current = true;
            const generation = cancelGeneration.current;
            const cancelled = () => generation !== cancelGeneration.current;
            const move = async () => {
                if (cancelled() || socket.readyState !== 1) throw new Error('Move cancelled');
                const token = crypto.randomUUID();
                ownedMove.current = token;
                return socket.sendJsonMessageAndWait<RuntimeApiJsonResponse>(
                    {event: 'move_saved_pose', data: {
                        pose: options.pose, follower_id: devices.follower_id, token, approved: true,
                        return_to_approach: options.returnToApproach, include_gripper: options.includeGripper,
                        duration_seconds: options.durationSeconds,
                    }},
                    ({event, data}) => event === 'state' && data?.saved_pose_token === token && data.saved_pose_status === 'moving'
                );
            };
            try {
                if (state.is_recording) {
                    if (!options.returnToApproach) throw new Error('Finish the episode first');
                    let result: RuntimeApiJsonResponse = {event: 'state'};
                    await finishGraspAndReturn({
                        hold: () => setFollowerSource.mutateAsync('hold'),
                        save: () => saveEpisode.mutateAsync(),
                        move: async () => { result = await move(); }, cancelled,
                    });
                    return result;
                }
                await setFollowerSource.mutateAsync('hold');
                return await move();
            } catch (error) {
                ownedMove.current = null;
                throw error;
            } finally { flowLock.current = false; }
        },
    });

'''
    text = replace(text, "    return (\n        <RuntimeSessionContext.Provider", insertion + "    return (\n        <RuntimeSessionContext.Provider")
    text = replace(text, "                readyForInference:", "                moveSavedPose,\n                stopSavedPose,\n                poseFlowBusy: moveSavedPose.isPending || stopSavedPose.isPending || saveEpisode.isPending || discardEpisode.isPending,\n                readyForInference:")
    provider.write_text(text, encoding="utf-8", newline="\n")
    record = root / "src/routes/datasets/record/recording-viewer.tsx"
    text = record.read_text(encoding="utf-8")
    text = replace(text, "import { paths }", "import { SavedPoseControls } from '../../../features/robots/saved-pose-controls';\nimport { paths }")
    text = replace(text, "        dataset,", "        poseFlowBusy,\n        dataset,")
    text = replace(text, "    const [task, setTask]", "    const canStart = readyForRecording && state.follower_source === 'teleop' && state.saved_pose_status !== 'moving' && !!state.approach_pose && !poseFlowBusy;\n    const [task, setTask]")
    text = replace(text, "!state.is_recording && !startEpisode.isPending && task !== ''", "canStart && !state.is_recording && !startEpisode.isPending && task !== ''")
    text = text.replace("state.is_recording && !saveEpisode.isPending", "state.is_recording && !poseFlowBusy")
    text = replace(text, "if (task !== '')", "if (canStart && task !== '')")
    text = replace(text, "                <Form validationBehavior", "                <SavedPoseControls />\n                <Form validationBehavior")
    text = replace(text, "isDisabled={saveEpisode.isPending}", "isDisabled={poseFlowBusy}")
    text = replace(text, "<Button isPending={saveEpisode.isPending}", "<Button isDisabled={poseFlowBusy} isPending={saveEpisode.isPending}")
    text = replace(text, "<Button type={'submit'} isPending={startEpisode.isPending}>", "<Button type={'submit'} isDisabled={!canStart} isPending={startEpisode.isPending}>")
    record.write_text(text, encoding="utf-8", newline="\n")
    infer = root / "src/features/models/inference/inference-viewer.tsx"
    text = infer.read_text(encoding="utf-8")
    text = replace(text, "import { runtimeExportUrl }", "import { SavedPoseControls } from '../../robots/saved-pose-controls';\nimport { runtimeExportUrl }")
    text = replace(text, "        model,", "        poseFlowBusy,\n        model,")
    text = replace(text, "    const canTeleoperate = state.has_leader;", "    const poseBusy = poseFlowBusy || state.saved_pose_status === 'moving';\n    const canTeleoperate = state.has_leader && !poseBusy;")
    text = replace(text, "                <RobotControlView", "                <SavedPoseControls />\n                <RobotControlView")
    text = replace(text, "                                isPending={startTask.isPending}", "                                isDisabled={poseBusy}\n                                isPending={startTask.isPending}")
    infer.write_text(text, encoding="utf-8", newline="\n")
    patch_joint_comparison_ui(root)
    for file in Path(__file__).with_name("ui").glob("*.ts*"):
        shutil.copy2(file, root / "src/features/robots" / file.name)
    for file in Path(__file__).with_name("ui").glob("*.module.css"):
        shutil.copy2(file, root / "src/features/robots" / file.name)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ui", type=Path, required=True)
    patch_ui(p.parse_args().ui)
