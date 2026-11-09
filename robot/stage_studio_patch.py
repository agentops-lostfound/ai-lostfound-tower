"""Stage a Studio manual-joint patch in a separate folder; never installs or moves."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

COMMAND='''class ManualJointControlCommand(CommandBase):
    command: Literal["manual_joint_control"] = "manual_joint_control"
    action: Literal["stop", "repair"]


class SetManualJointTargetCommand(CommandBase):
    command: Literal["set_manual_joint_target"] = "set_manual_joint_target"
    target: dict[str, float]
    expected: dict[str, float]
    stage_approved: bool = False


'''

HANDLER='''    def _handle_manual_joint_target(self, command, robot_state):
        # Local experimental extension: one bounded step; no queued trajectory.
        import math
        import time
        names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
        try:
            if getattr(self, "_manual_stop_latched", False):
                raise ValueError("Manual stop latched; repair required")
            if self._follower_source != "hold" or not command.stage_approved:
                raise ValueError("Hold mode and stage approval required")
            if list(self._follower.joint_names) != names:
                raise ValueError("SO101 joint ordering required")
            keys = [n + ".pos" for n in names]
            if set(command.target) != set(keys) or set(command.expected) != set(keys):
                raise ValueError("All six named normalized joints required")
            goal = np.array([command.target[k] for k in keys], dtype=float)
            expected = np.array([command.expected[k] for k in keys], dtype=float)
            current = np.array(robot_state.joint_positions, dtype=float)
            previous = current if self._hold_target is None else np.array(self._hold_target, dtype=float)
            if current.shape != (6,) or not np.isfinite(current).all():
                raise ValueError("Invalid observation")
            if not np.isfinite(goal).all() or not np.isfinite(expected).all():
                raise ValueError("Nonfinite target")
            if (goal[:5] < -100).any() or (goal > 100).any() or goal[5] < 0:
                raise ValueError("Out of normalized range")
            if abs(goal[5] - previous[5]) > 0.5:
                raise ValueError("Gripper must remain unchanged")
            goal[5] = previous[5]
            if np.max(np.abs(current - expected)) > 0.5:
                raise ValueError("Observation mismatch")
            if np.max(np.abs(goal - previous)) > 0.250001:
                raise ValueError("Step exceeds 0.25 normalized units")
            if np.max(np.abs(goal - current)) > 0.5:
                raise ValueError("Following error")
            now = time.monotonic()
            if now - getattr(self, "_manual_joint_last_time", -math.inf) < 0.1:
                raise ValueError("Manual step rate exceeds 10Hz")
            self._hold_target = goal.astype(np.float32)
            self._manual_joint_last_time = now
        except ValueError as exc:
            self._event_sink.emit(ErrorEvent(message=str(exc), error_code="manual_joint_rejected"))

    def _handle_manual_joint_control(self, command, robot_state):
        if command.action == "repair":
            if self._follower_source != "hold":
                self._event_sink.emit(ErrorEvent(message="Repair requires hold", error_code="manual_joint_rejected"))
                return
            self._manual_stop_latched = False
        else:
            self._cancel_arming()
            self._follower_source = "hold"
            self._manual_stop_latched = True
        self._hold_target = np.array(robot_state.joint_positions, dtype=np.float32, copy=True)
        self._emit_state()

'''

ENDPOINT='''

@router.websocket("/manual/ws")
async def manual_joint_websocket(
    websocket: WebSocket,
    project_id: UUID,
    robot_service: Annotated[RobotService, Depends(get_robot_service)],
):
    # Attach only. Never starts/restarts runtime, claims cameras, or opens serial.
    client = None
    sender = None
    follower_id = None
    registry = getattr(manual_joint_websocket, "_clients", None)
    if registry is None:
        registry = {}
        manual_joint_websocket._clients = registry
    await websocket.accept()
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), 5)
        follower_id = UUID(str(hello.get("follower_id")))
        robot = await robot_service.get_robot_by_id(project_id, follower_id)
        if robot.type != "SO101_Follower":
            raise ValueError("SO101 follower required")
        if follower_id in registry:
            raise ValueError("Another manual panel already attached")
        registry[follower_id] = websocket
        client = RuntimeSessionClient(runtime_session_name(follower_id))
        await asyncio.to_thread(client.open)
        await asyncio.to_thread(client.connect, 3.0)
        await websocket.send_json({"event":"manual_capabilities", "data":{"version":1,"max_step":0.25,"rate_hz":10,"attach_only":True}})
        async def outgoing():
            while True:
                if client.error is not None or client.shutdown_received:
                    raise RuntimeError("Runtime unavailable")
                try:
                    event = client.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue
                await websocket.send_json(event.model_dump(mode="json"))
        sender = asyncio.create_task(outgoing())
        while True:
            message = await websocket.receive_json()
            event = message.get("event")
            if event not in {"set_manual_joint_target", "manual_joint_control"}:
                continue
            payload = dict(message.get("data") or {})
            payload["command"] = event
            client.apply(CommandAdapter.validate_python(payload))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json(_websocket_error_payload(exc))
        except Exception:
            pass
    finally:
        if sender is not None:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if client is not None:
            # On panel loss, latch stop in the same runtime; no torque release.
            try:
                client.apply(CommandAdapter.validate_python({"command":"manual_joint_control","action":"stop"}))
            finally:
                client.close()
        if follower_id is not None and registry.get(follower_id) is websocket:
            registry.pop(follower_id, None)
'''


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Studio source anchor mismatch: '+old[:65])
    return text.replace(old,new,1)


def patch_files(source):
    files={name:(source/name).read_text() for name in
           ['runtime/contract.py','runtime/action_source.py','api/runtime_ws.py']}
    if any('SetManualJointTargetCommand' in x for x in files.values()):
        raise ValueError('Source already patched; do not apply twice')
    c=files['runtime/contract.py']
    c=replace_once(c,'class DisconnectCommand(CommandBase):',COMMAND+'class DisconnectCommand(CommandBase):')
    c=replace_once(c,'    | DisconnectCommand','    | ManualJointControlCommand\n    | SetManualJointTargetCommand\n    | DisconnectCommand')
    files['runtime/contract.py']=c
    a=files['runtime/action_source.py']
    a=replace_once(a,'    SetFollowerSourceCommand,','    SetFollowerSourceCommand,\n    SetManualJointTargetCommand,\n    ManualJointControlCommand,')
    a=replace_once(a,'            if isinstance(command, LoadModelCommand):',
                   '            if isinstance(command, ManualJointControlCommand):\n                self._handle_manual_joint_control(command, robot_state)\n            elif isinstance(command, SetManualJointTargetCommand):\n                self._handle_manual_joint_target(command, robot_state)\n            elif isinstance(command, LoadModelCommand):')
    a=replace_once(a,'    def _handle_load_model(',HANDLER+'    def _handle_load_model(')
    files['runtime/action_source.py']=a
    files['api/runtime_ws.py']=replace_once(files['api/runtime_ws.py'],'        "set_follower_source",',
                                         '        "set_follower_source",\n        "set_manual_joint_target",\n        "manual_joint_control",')+ENDPOINT
    for name,text in files.items():ast.parse(text,filename=name)
    return files


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True,help='Studio backend/src')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source=a.source.resolve();output=a.output.resolve()
    if source==output or source in output.parents or output in source.parents:
        raise ValueError('Output must be isolated from Studio source')
    files=patch_files(source)
    manifest={'status':'staged_not_installed','robot_command_sent':False,'files':{}}
    for name,text in files.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise FileExistsError(target)
        target.write_text(text)
        manifest['files'][name]={'original_sha256':hashlib.sha256((source/name).read_bytes()).hexdigest(),
                                 'patched_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
