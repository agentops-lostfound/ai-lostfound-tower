"""Attach-only IPC worker inside Studio. No owner, driver or serial connection."""
import json
import queue
import sys
import threading
import time
import uuid


def confirm_stop(client, adapter, instance_id, *, expected_token=None,
                 was_accepted=lambda: False, clock=time.monotonic, sleep=time.sleep):
    """Publish HOLD, then query its current state, not an old broadcast.

    This is state confirmation, not a hardware emergency-stop acknowledgement.
    The installed runtime does not support stop through its request/ACK path.
    """
    client.apply(adapter.validate_python({'command': 'stop_saved_pose'}))
    if not isinstance(instance_id, str) or not instance_id:
        return False
    seen_accepted = False
    deadline = clock() + 1.0
    while clock() < deadline:
        if client.error is not None or client.shutdown_received:
            return False
        metadata = client.probe(timeout=0.2)
        if metadata and metadata.get('instance_id') == instance_id and metadata.get('status') == 'running':
            state = (metadata.get('state') or {}).get('data') or {}
            if (expected_token is not None and state.get('saved_pose_token') == expected_token
                    and state.get('saved_pose_status') in ('moving', 'holding_target')):
                seen_accepted = True
            # A metadata query is not a command-processing barrier. If our
            # move was never observed as accepted, an old stopped snapshot
            # cannot prove that a queued move/stop has been processed.
            if (state.get('connected') and state.get('follower_source') == 'hold'
                    and state.get('saved_pose_status') == 'stopped'
                    and (expected_token is None or seen_accepted or was_accepted())):
                return True
        sleep(0.02)
    return False


def main():
    from runtime.contract import CommandAdapter
    from runtime.transport.client import RuntimeSessionClient

    follower = str(uuid.UUID(sys.argv[1]))
    client = RuntimeSessionClient('rt-' + follower)
    done = threading.Event()
    owned = threading.Event()
    move = {'token': None, 'pose': None, 'accepted': False}
    output_lock = threading.Lock()
    move_lock = threading.Lock()
    instance_id = None

    def emit(row):
        with output_lock:
            print(json.dumps(row), flush=True)

    def stop_current():
        with move_lock:
            token = move['token'] if owned.is_set() else None
        def was_accepted():
            with move_lock:
                return move['token'] == token and move['accepted']
        return confirm_stop(client, CommandAdapter, instance_id,
                            expected_token=token, was_accepted=was_accepted)

    def incoming():
        try:
            for line in sys.stdin:
                row = json.loads(line)
                event = row.get('event')
                if event not in ('move_saved_pose', 'saved_pose_heartbeat', 'stop_saved_pose'):
                    raise ValueError('Unsupported pose command')
                data = dict(row.get('data') or {})
                if event == 'stop_saved_pose':
                    ok = stop_current()
                    if ok:
                        owned.clear()
                    emit({'event': 'stop_result', 'request_id': data.get('request_id'), 'ok': ok})
                    continue
                command = CommandAdapter.validate_python({**data, 'command': event})
                if event == 'move_saved_pose':
                    if data.get('follower_id') != follower:
                        raise ValueError('Follower mismatch')
                    with move_lock:
                        move.update(token=data.get('token'), pose=data.get('pose'), accepted=False)
                        owned.set()
                client.apply(command)
        except Exception:
            emit({'event': 'error', 'message': 'Studio pose command failed'})
        finally:
            done.set()

    client.open()
    try:
        metadata = client.connect(3.0)  # Existing IPC only; cannot spawn a runtime.
        instance_id = metadata.get('instance_id')
        if metadata.get('state'):
            emit(metadata['state'])  # HOLD state may not be re-emitted until it changes.
        threading.Thread(target=incoming, daemon=True).start()
        while not done.is_set():
            if client.error is not None or client.shutdown_received:
                raise RuntimeError('Studio runtime unavailable')
            try:
                event = client.get_nowait()
            except queue.Empty:
                time.sleep(0.005)
                continue
            row = event.model_dump(mode='json')
            if row.get('event') == 'state':
                state = row.get('data') or {}
                with move_lock:
                    if move['token'] and state.get('saved_pose_token') == move['token']:
                        move['accepted'] = True
                    if move['accepted'] and state.get('saved_pose_name') == move['pose'] and state.get('saved_pose_status') in ('arrived', 'stopped', 'error'):
                        owned.clear()
            emit(row)
    except Exception:
        emit({'event': 'error', 'message': 'Studio runtime attach failed; connect Studio first'})
    finally:
        if owned.is_set():
            try:
                stop_current()
            except Exception:
                pass
        client.close()


if __name__ == '__main__':
    main()
