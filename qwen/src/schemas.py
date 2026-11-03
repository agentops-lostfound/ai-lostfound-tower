from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Sticker(StrictModel):
    shape: str | None
    position: str | None

class WalletFeatures(StrictModel):
    category: Literal['wallet', 'other', 'unknown']
    colors: list[str] = Field(max_length=20)
    shape: str | None
    wallet_type: str | None
    materials: list[str]
    logos_or_text: list[str]
    sticker_status: Literal['present', 'absent', 'unknown']
    stickers: list[Sticker]
    distinctive_features: list[str]

    @model_validator(mode='after')
    def consistent_stickers(self):
        if (self.sticker_status == 'present') != bool(self.stickers):
            raise ValueError('present requires stickers; absent/unknown requires empty stickers')
        return self
