import json
import re
from .schemas import WalletFeatures

def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result

def validate_response(raw: str) -> WalletFeatures:
    text = raw.strip()
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)
    value = json.loads(text, object_pairs_hook=_unique_object,
                       parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    return WalletFeatures.model_validate(value)
