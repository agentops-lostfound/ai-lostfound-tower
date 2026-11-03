"""Environment overrides are read at process start; .env is not loaded implicitly."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Settings:
    model_id: str = 'Qwen/Qwen3-VL-2B-Instruct'
    cache_dir: Path = ROOT / '.cache' / 'huggingface'
    log_dir: Path = ROOT / 'logs'
    max_edge: int = int(os.getenv('WALLET_MAX_EDGE', '768'))
    max_new_tokens: int = int(os.getenv('WALLET_MAX_NEW_TOKENS', '512'))
    retries: int = int(os.getenv('WALLET_RETRIES', '1'))
    offline: bool = os.getenv('HF_HUB_OFFLINE', '0') == '1'

    def __post_init__(self):
        if self.max_edge < 32 or self.max_new_tokens < 1 or not 0 <= self.retries <= 3:
            raise ValueError('max_edge >= 32, max_new_tokens >= 1, retries in 0..3 required')
