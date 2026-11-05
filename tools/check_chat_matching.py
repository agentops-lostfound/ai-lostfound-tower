"""No models/DB/hardware: run the internal LF-5 -> LF-20 link on a synthetic scene."""
import json
from agents.chatbot import Chatbot
from agents.guidance import Guidance


def synthetic_scene():
    return {'sequence': {'status': 'complete'}, 'objects': [
        {'id': 710+i, 'confidence': .9, 'bbox': [i*40, 0, i*40+30, 30],
         'center_px': [i*40+15, 15], 'qwen': {'status': 'ok', 'features': {
             'category': category, 'colors': [color], 'shape': 'rectangle',
             'materials': [], 'logos_or_text': [], 'sticker_status': 'unknown',
             'stickers': [], 'distinctive_features': []}}}
        for i, (category, color) in enumerate([('wallet', 'black'), ('usb', 'gray'), ('power_bank', 'white')])]}


def main():
    bot = Chatbot(Guidance())
    cases = [('지갑 품목·색상', '검정 지갑 찾아줘'),
             ('USB 품목·색상', '회색 USB 찾아줘'),
             ('없는 색상', '빨간 지갑 찾아줘'),
             ('미지원 품목', '빨간 우산 찾아줘'),
             ('품목 불확실', '휴대폰처럼 생긴 검정 물건'),
             ('상세 번역 대기', '검정 지갑에 꽃 스티커가 있어요')]
    for label, text in cases:
        print(json.dumps({'case': label, **bot.inspect_matching(text, synthetic_scene())}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
