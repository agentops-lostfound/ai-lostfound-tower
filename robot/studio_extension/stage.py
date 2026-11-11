"""Build an inspectable Studio overlay from the installed v4 backend and UI.

Writes only the chosen staging directory. Does not restart Studio or move a robot.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one Studio anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def backend_files(source, poses, follower_id):
    from robot.phone_carry import augmented_poses
    poses, motion_profiles = augmented_poses(poses)
    c = (source / "runtime/contract.py").read_text(encoding="utf-8")
    commands = '''class MoveSavedPoseCommand(CommandBase):
    command: Literal["move_saved_pose"] = "move_saved_pose"
    pose: str = ""
    follower_id: str
    token: str = Field(min_length=1, max_length=100)
    approved: bool = False
    return_to_approach: bool = False
    include_gripper: bool = True
    duration_seconds: Literal[3, 4, 5] = 3


class SavedPoseHeartbeatCommand(CommandBase):
    command: Literal["saved_pose_heartbeat"] = "saved_pose_heartbeat"
    token: str


class StopSavedPoseCommand(CommandBase):
    command: Literal["stop_saved_pose"] = "stop_saved_pose"


'''
    c = replace(c, "class DisconnectCommand(CommandBase):", commands + "class DisconnectCommand(CommandBase):")
    c = replace(c, "    | DisconnectCommand", "    | MoveSavedPoseCommand\n    | SavedPoseHeartbeatCommand\n    | StopSavedPoseCommand\n    | DisconnectCommand")
    c = replace(c, "    actions: dict[str, float] | None = None", "    actions: dict[str, float] | None = None\n    leader: dict[str, float] | None = None")
    a = (source / "runtime/action_source.py").read_text(encoding="utf-8")
    a = replace(a, "class StudioActionSource:", "from runtime.saved_pose import SavedPoseMixin\n\n\nclass StudioActionSource(SavedPoseMixin):")
    a = replace(a, "        self._recording: RecordingState | None = None", "        self._recording: RecordingState | None = None\n        self._init_saved_poses()")
    a = replace(a, "            connected=True,", "            **self._saved_pose_state(),\n            connected=True,")
    a = replace(a, "        self._drain_commands(robot_state)", "        self._observe_saved_pose(robot_state)\n        self._drain_commands(robot_state)\n        self._tick_saved_pose(robot_state)")
    a = replace(a, "        policy_action = self._policy_action(robot_state, camera_frames, step)", "        policy_action = self._policy_action(robot_state, camera_frames, step) if self._follower_source == 'policy' else None")
    for output in ("leader_action", "policy_action", "self._hold_target.copy()"):
        a = replace(a, f"return {output}\n", f"return self._remember_pose_output({output})\n")
    a = replace(a, "        for command in self._mailbox.drain():", '''        for command in self._mailbox.drain():
            if command.command in {"move_saved_pose", "saved_pose_heartbeat", "stop_saved_pose"}:
                self._handle_saved_pose(command, robot_state)
                continue
            if self._pose_command_blocked(command, robot_state):
                continue''')
    w = (source / "runtime_ws.py").read_text(encoding="utf-8")
    w = replace(w, '        "set_follower_source",', '        "move_saved_pose",\n        "saved_pose_heartbeat",\n        "stop_saved_pose",\n        "set_follower_source",')
    w = replace(w, "            client.apply(command)\n", '''            if event == "move_saved_pose" and runtime_session_name(command.follower_id) != client._name:
                await websocket.send_json({"event": "error", "error_code": "saved_pose_rejected",
                                           "message": "Saved pose follower does not match this session"})
                continue
            client.apply(command)
''')
    session = (source / "runtime/session.py").read_text(encoding="utf-8")
    session = replace(session, "            state_data=action_source.state_data,", "            state_data=action_source.state_data,\n            leader_positions=action_source.leader_positions,")
    stream = (source / "runtime/callbacks/stream.py").read_text(encoding="utf-8")
    stream = replace(stream, "        state_data: Callable[[], StateData] | None = None,", "        state_data: Callable[[], StateData] | None = None,\n        leader_positions: Callable[[], dict[str, float] | None] | None = None,")
    stream = replace(stream, "        self._state_data = state_data", "        self._state_data = state_data\n        self._leader_positions = leader_positions")
    stream = replace(stream, "        self._event_sink.emit(ObservationEvent(data=data, actions=actions))", "        leader = self._leader_positions() if self._leader_positions is not None else None\n        self._event_sink.emit(ObservationEvent(data=data, actions=actions, leader=leader))")
    for method in ("save_episode", "discard_episode"):
        anchor = f"    def _{method}(self) -> None:\n"
        wrapper = f'''    def _{method}(self) -> None:
        source = self._action_source
        if source is not None:
            source._pose_episode_finalizing = True
        try:
            self._pose_original_{method}()
        finally:
            if source is not None:
                source._pose_episode_finalizing = False

    def _pose_original_{method}(self) -> None:
'''
        session = replace(session, anchor, wrapper)
    files = {"runtime/contract.py": c, "runtime/action_source.py": a, "runtime/session.py": session, "api/runtime_ws.py": w,
             "runtime/callbacks/stream.py": stream,
             "runtime/saved_pose.py": Path(__file__).with_name("runtime").joinpath("saved_pose.py").read_text(encoding="utf-8"),
             "runtime/saved_poses.json": json.dumps({"follower_id": follower_id, "poses": poses,
                                                    "motion_profiles": motion_profiles}, indent=2)}
    from robot.command_correction import load_command_corrections
    corrections = load_command_corrections(poses)
    if corrections:
        data = json.loads(files['runtime/saved_poses.json'])
        data['command_corrections'] = corrections
        files['runtime/saved_poses.json'] = json.dumps(data, indent=2)
    for name, text in files.items():
        if name.endswith(".py"):
            ast.parse(text, name)
    return files


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--poses", type=Path, required=True)
    p.add_argument("--follower-id", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    files = backend_files(args.source, json.loads(args.poses.read_text(encoding="utf-8")), args.follower_id)
    manifest = {}
    for name, text in files.items():
        dest = args.output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        manifest[name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
