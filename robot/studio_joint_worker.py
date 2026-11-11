"""Subscriber-only Studio IPC observer. No publisher, commands, drivers or serial."""
from datetime import datetime, timezone
import json
import sys
import threading
import time
import uuid


class ObservationBuffer:
    """Bounded latest observation, fenced by runtime generation."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.instance = None
        self.connected = False
        self.latest = None

    def attach(self, metadata):
        instance = metadata.get('instance_id') if metadata else None
        connected = bool(instance and metadata.get('status') == 'running'
                         and ((metadata.get('state') or {}).get('data') or {}).get('connected'))
        with self.lock:
            if instance != self.instance or not connected:
                self.latest = None
            self.instance, self.connected = instance, connected

    def receive(self, event, instance, fatal=False):
        with self.lock:
            if not self.instance or instance != self.instance:
                return
            if (fatal or event.get('event') == 'lifecycle' and (event.get('data') or {}).get('event') == 'shutdown'
                    or event.get('event') == 'state' and not (event.get('data') or {}).get('connected')):
                self.latest, self.connected = None, False
            elif self.connected and event.get('event') == 'observation':
                self.latest = ({'available': True, 'positions': event['data'],
                                'read_at': datetime.now(timezone.utc).isoformat()}, self.clock())

    def snapshot(self):
        with self.lock:
            if not self.connected or self.latest is None or self.clock() - self.latest[1] > .5:
                return {'available': False}
            return {**self.latest[0], 'sample_age_seconds': self.clock() - self.latest[1]}


def observe(session, name, done, requested):
    from runtime.transport.codec import decode_event, decode_metadata
    from runtime.transport.ids import tick_key, state_key, error_key, lifecycle_key, metadata_key

    buffer = ObservationBuffer()

    def receive(sample):
        try:
            event, fatal, instance = decode_event(sample.payload.to_bytes())
            buffer.receive(event.model_dump(mode='json'), instance, fatal)
        except Exception:
            buffer.attach(None)

    subscribers = [session.declare_subscriber(key, receive) for key in (
        tick_key(name), state_key(name), error_key(name), lifecycle_key(name))]
    try:
        next_probe = 0.
        while not done.is_set():
            if time.monotonic() >= next_probe:
                metadata = None
                try:
                    for reply in session.get(metadata_key(name), timeout=.2):
                        if reply.ok is not None:
                            metadata = decode_metadata(reply.ok.payload.to_bytes())
                            break
                except Exception:
                    pass
                buffer.attach(metadata)
                next_probe = time.monotonic() + 1.
            if requested.is_set():
                requested.clear()
                print(json.dumps(buffer.snapshot(), allow_nan=False), flush=True)
            done.wait(.1)
    finally:
        for subscriber in subscribers:
            subscriber.undeclare()


def main():
    from runtime.transport.session import open_session

    name = 'rt-' + str(uuid.UUID(sys.argv[1]))
    done = threading.Event()
    requested = threading.Event()

    def wait_for_eof():
        for line in sys.stdin:
            if line.strip() == 'sample':
                requested.set()  # Query this observer's cache, never the runtime.
        done.set()

    threading.Thread(target=wait_for_eof, daemon=True).start()
    session = open_session(name, listen=False)  # Attach; never create a runtime.
    try:
        observe(session, name, done, requested)
    finally:
        session.close()  # Only this observer's IPC connection.


if __name__ == '__main__':
    main()
