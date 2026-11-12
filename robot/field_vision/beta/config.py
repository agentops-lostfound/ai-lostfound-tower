from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'beta_data'
MEDIA = DATA / 'media'
SETTINGS = DATA / 'settings.json'
CLASSES = {'phone': 'mobile phone', 'wallet': 'wallet', 'hand_cream': 'hand cream tube', 'usb': 'USB flash drive', 'lip_balm': 'lip balm tube'}
DETECTION_PROMPTS = {
    'phone': ['mobile phone'],
    'wallet': ['wallet', 'card wallet', 'a photo of a card holder', 'a photo of a credit card holder'],
    'hand_cream': ['hand cream tube'],
    'usb': ['USB flash drive'],
    'lip_balm': ['lip balm tube', 'lip balm stick', 'lip balm container'],
}
NAMES = {'phone': '핸드폰', 'wallet': '지갑', 'hand_cream': '핸드크림', 'usb': 'USB', 'lip_balm': '립밤'}
CLASSES['power_bank']='portable power bank'
DETECTION_PROMPTS['power_bank']=['portable power bank','external battery pack','a photo of a power bank']
NAMES['power_bank']='보조배터리'
from .category_catalog import Catalog
CATEGORY_CATALOG=Catalog(DATA/'categories.json',CLASSES,DETECTION_PROMPTS,NAMES)
MODEL_IDS = {'owl': 'google/owlv2-base-patch16-ensemble', 'sig': 'google/siglip2-base-patch16-224', 'qwen': 'Qwen/Qwen3-VL-2B-Instruct'}
DEFAULTS = {
    'cameras': {'top': {'name': '탑뷰 · 웹캠', 'source': 'device:1', 'enabled': True},
                'arm': {'name': 'ARM · 손목 카메라', 'source': 'http://127.0.0.1:8765/camera.mjpg', 'enabled': True}},
    'interval': 3.0, 'threshold': 0.15, 'auto_features': False, 'feature_limit': 4,
    'cooldown': 60.0, 'roi': None, 'show_candidates': False, 'analysis_delay': 5.0,
    'exclude_aruco': True,
}
