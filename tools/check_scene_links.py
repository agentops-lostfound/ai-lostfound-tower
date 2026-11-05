"""Demonstrate inspection-only receipt links with synthetic data; no DB/hardware."""
import json
from datetime import datetime, timedelta, timezone
from agents.chatbot import Chatbot
from agents.guidance import Guidance
from agents.scene_bindings import bind_scene, scene_digest
from tools.check_chat_matching import synthetic_scene


def main():
    now = [datetime.now(timezone.utc)]
    report = synthetic_scene()
    day = now[0].strftime('%Y%m%d')
    manifest = {'capture_id': 'synthetic-session-001', 'captured_at': now[0].isoformat(),
        'report_sha256': scene_digest(report), 'bindings': [
            {'vision_id': obj['id'], 'item_id': f'{prefix}-{day}-0001'}
            for obj, prefix in zip(report['objects'], ['A', 'B', 'S'])]}
    bound = bind_scene(report, manifest, clock=lambda: now[0])
    bot = Chatbot(Guidance())
    for label, check in [('가상 재고 유지', lambda _item: True), ('가상 재고 변경', lambda _item: False)]:
        output = bot.inspect_inventory_matching('회색 USB 찾아줘', bound, check)
        print(json.dumps({'case': label, **output}, ensure_ascii=False))
    now[0] += timedelta(seconds=301)
    output = bot.inspect_inventory_matching('회색 USB 찾아줘', bound, lambda _item: True)
    print(json.dumps({'case': '촬영 유효 시간 초과', **output}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
