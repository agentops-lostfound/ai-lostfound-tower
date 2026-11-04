# 필터 → 자유 특징 임베딩 비교

기존 34개 질문을 재사용했습니다. 조건과 자유 문장은 사람이 원래 질문에서 분리했습니다. 자동 추출 성능은 평가하지 않았습니다.
Qwen 저장값에 맞춘 질문이며 중복 실행이 있습니다. 실물 정확도나 일반화 성능이 아닙니다. 기존 결과는 보존했습니다.
새 점수와 기존 코사인은 다른 척도입니다. 품목 관계·판정 조건 변경과 임베딩 입력 변경을 함께 적용했으므로 개선 원인을 개별적으로 입증한 실험은 아닙니다.

```json
{
  "positive": {
    "matched": 16,
    "needs_confirmation": 1
  },
  "contradictory": {
    "no_match": 17
  },
  "positive_wrong_selected": 0
}
```

| 실행/대상 | 종류 | 기존 임베딩 1위 | 이전 정책 | 새 정책 | 새 선택 | 이유 |
|---|---|---|---|---|---|---|
| 262a3fbb/0 | positive | 0 | needs_confirmation | matched | 0 |  |
| 262a3fbb/0 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| 262a3fbb/1 | positive | 1 | matched | matched | 1 |  |
| 262a3fbb/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| 2fa66a50/0 | positive | 0 | needs_confirmation | matched | 0 |  |
| 2fa66a50/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |
| 2fa66a50/1 | positive | 1 | matched | matched | 1 |  |
| 2fa66a50/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| 4560b8a5/0 | positive | 0 | needs_confirmation | needs_confirmation | None | unknown_requested_attributes, weak_attribute_match |
| 4560b8a5/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |
| 4560b8a5/1 | positive | 1 | matched | matched | 1 |  |
| 4560b8a5/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| 60fd6277/0 | positive | 0 | needs_confirmation | matched | 0 |  |
| 60fd6277/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |
| 60fd6277/1 | positive | 1 | matched | matched | 1 |  |
| 60fd6277/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| 94b94ac4/0 | positive | 0 | matched | matched | 0 |  |
| 94b94ac4/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |
| cb97b414/0 | positive | 0 | needs_confirmation | matched | 0 |  |
| cb97b414/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |
| cb97b414/1 | positive | 1 | matched | matched | 1 |  |
| cb97b414/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| d3dfa2e2/0 | positive | 0 | needs_confirmation | matched | 0 |  |
| d3dfa2e2/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |
| d3dfa2e2/1 | positive | 1 | matched | matched | 1 |  |
| d3dfa2e2/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| ed1419ed/1 | positive | 1 | matched | matched | 1 |  |
| ed1419ed/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| f7e7af5f/0 | positive | 0 | needs_confirmation | matched | 0 |  |
| f7e7af5f/0 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| f7e7af5f/1 | positive | 1 | matched | matched | 1 |  |
| f7e7af5f/1 | contradictory | 1 | no_match | no_match | None | no_eligible_candidates |
| qwen_onl/0 | positive | 0 | matched | matched | 0 |  |
| qwen_onl/0 | contradictory | 0 | no_match | no_match | None | no_eligible_candidates |

## 262a3fbb20e1489495aa30dd55cf18e9 / 0 / positive

진한 파란색 폰이고 뒷면 왼쪽 아래에 캐릭터 스티커가 있어요.

My handset is navy blue and has an animated character decal near the lower left of its rear.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "navy"
    ],
    "sticker_status": "present",
    "free_text": "Animated character decal near the lower left of the rear."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.36617839336395264,
      "final_score": 0.8232356786727905,
      "attribute_scores": {
        "semantic": 0.36617839336395264,
        "category": 1.0,
        "color": 0.9,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.3750000000000001,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0,
        "sticker": 1.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 262a3fbb20e1489495aa30dd55cf18e9 / 0 / contradictory

밝은 노란색이고 스티커가 전혀 없는 폰이에요.

My phone is bright yellow with no stickers or decals anywhere.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "yellow"
    ],
    "sticker_status": "absent",
    "free_text": ""
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.25000000000000006,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.25000000000000006,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 262a3fbb20e1489495aa30dd55cf18e9 / 1 / positive

흰색 폰이고 뒤에 카메라 두 개와 애플 로고가 있으며 금이 가 있어요.

I lost a white smartphone with a pair of rear cameras, an Apple emblem and a crack on its back.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "white"
    ],
    "free_text": "A pair of rear cameras, an Apple emblem and a crack on the back."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.5863776206970215,
      "final_score": 0.9080839157104492,
      "attribute_scores": {
        "semantic": 0.5863776206970215,
        "category": 1.0,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 262a3fbb20e1489495aa30dd55cf18e9 / 1 / contradictory

빨간 폰이고 카메라가 하나이며 뒷면 손상이 없어요.

My phone is red, has only one rear camera, and has no damage or cracks on the back.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "red"
    ],
    "free_text": "Only one rear camera and no damage or cracks on the back."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 2fa66a50d89e4a788480166975c2a7b6 / 0 / positive

검은 가죽 카드지갑이고 HONOR라는 글자와 카드 슬롯이 있어요.

My black leather card holder has HONOR lettering and a slot for a card.

```json
{
  "conditions": {
    "category": "card_wallet",
    "colors": [
      "black"
    ],
    "free_text": "Leather, HONOR lettering and a slot for a card."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": 0.2579141894976298,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.7124343514442444,
      "final_score": 0.8916520780987209,
      "attribute_scores": {
        "semantic": 0.7124343514442444,
        "category": 0.8,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": 0.3518204987049103,
      "final_score": 0.6337378886010911,
      "attribute_scores": {
        "semantic": 0.3518204987049103,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## 2fa66a50d89e4a788480166975c2a7b6 / 0 / contradictory

흰색 천 지갑이고 VISA라고 적혀 있어요.

My wallet is white fabric with VISA lettering.

```json
{
  "conditions": {
    "category": "wallet",
    "colors": [
      "white"
    ],
    "free_text": "Fabric with VISA lettering."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## 2fa66a50d89e4a788480166975c2a7b6 / 1 / positive

검정과 초록색의 직사각형 물건이고 MIDAS 글자와 위쪽 사각 스티커가 있어요.

My rectangular item is black and green, marked MIDAS, with a rectangular sticker at the top.

```json
{
  "conditions": {
    "colors": [
      "black",
      "green"
    ],
    "sticker_status": "present",
    "free_text": "Rectangular, MIDAS marking, rectangular sticker at the top."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": 0.5056027546525002,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.7541389465332031,
      "final_score": 0.9385347366333009,
      "attribute_scores": {
        "semantic": 0.7541389465332031,
        "color": 1.0,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": 0.4817279279232025,
      "final_score": 0.4329319819808007,
      "attribute_scores": {
        "semantic": 0.4817279279232025,
        "color": 0.5,
        "sticker": 0.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    }
  ]
}
```

## 2fa66a50d89e4a788480166975c2a7b6 / 1 / contradictory

흰색과 분홍색의 둥근 물건이고 MIDAS 글자는 없어요.

My object is round, white and pink, with no MIDAS marking.

```json
{
  "conditions": {
    "colors": [
      "white",
      "pink"
    ],
    "free_text": "Round with no MIDAS marking."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 4560b8a53f4b4eeb96718439dc8f595a / 0 / positive

검은 폰이고 검정 화면과 케이스가 있으며 스티커는 없어요.

My black phone is inside a protective cover, has a dark screen and no stickers.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "black"
    ],
    "sticker_status": "absent",
    "free_text": "Protective cover and a dark screen."
  },
  "decision": {
    "status": "needs_confirmation",
    "selected_id": null,
    "top_candidate_id": 0,
    "margin": null,
    "reasons": [
      "unknown_requested_attributes",
      "weak_attribute_match"
    ]
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.4429047405719757,
      "final_score": 0.6885809481143951,
      "attribute_scores": {
        "semantic": 0.4429047405719757,
        "color": 1.0,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": [
        "category"
      ]
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.625,
      "attribute_scores": {
        "category": 0.0,
        "color": 1.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "category_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 4560b8a53f4b4eeb96718439dc8f595a / 0 / contradictory

초록색 폰이고 화면이 켜져 있으며 케이스가 없어요.

My green phone has a lit screen and no protective cover.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "green"
    ],
    "free_text": "Lit screen and no protective cover."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": [
        "category"
      ]
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "category": 0.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "category_mismatch",
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 4560b8a53f4b4eeb96718439dc8f595a / 1 / positive

검은 가죽 지갑이고 오른쪽 아래 작은 정사각형 표시가 있어요.

My black leather wallet has a little square emblem at the bottom right.

```json
{
  "conditions": {
    "category": "wallet",
    "colors": [
      "black"
    ],
    "free_text": "Leather, little square emblem at the bottom right."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": 0.2498629225624932,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.5683501958847046,
      "final_score": 0.9040778213077121,
      "attribute_scores": {
        "semantic": 0.5683501958847046,
        "category": 1.0,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": 0.4439670443534851,
      "final_score": 0.6542148987452189,
      "attribute_scores": {
        "semantic": 0.4439670443534851,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## 4560b8a53f4b4eeb96718439dc8f595a / 1 / contradictory

노란 천 지갑이고 오른쪽 아래 표시가 없어요.

My yellow cloth wallet has no marking at the lower right.

```json
{
  "conditions": {
    "category": "wallet",
    "colors": [
      "yellow"
    ],
    "free_text": "Cloth with no marking at the lower right."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## 60fd6277bc07490fbefd8d4b9446093e / 0 / positive

검은 가죽 카드지갑이고 HONOR라는 글자와 카드 슬롯이 있어요.

My black leather card holder has HONOR lettering and a slot for a card.

```json
{
  "conditions": {
    "category": "card_wallet",
    "colors": [
      "black"
    ],
    "free_text": "Leather, HONOR lettering and a slot for a card."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": 0.2579141894976298,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.7124343514442444,
      "final_score": 0.8916520780987209,
      "attribute_scores": {
        "semantic": 0.7124343514442444,
        "category": 0.8,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": 0.3518204987049103,
      "final_score": 0.6337378886010911,
      "attribute_scores": {
        "semantic": 0.3518204987049103,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## 60fd6277bc07490fbefd8d4b9446093e / 0 / contradictory

흰색 천 지갑이고 VISA라고 적혀 있어요.

My wallet is white fabric with VISA lettering.

```json
{
  "conditions": {
    "category": "wallet",
    "colors": [
      "white"
    ],
    "free_text": "Fabric with VISA lettering."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## 60fd6277bc07490fbefd8d4b9446093e / 1 / positive

검정과 초록색의 직사각형 물건이고 MIDAS 글자와 위쪽 사각 스티커가 있어요.

My rectangular item is black and green, marked MIDAS, with a rectangular sticker at the top.

```json
{
  "conditions": {
    "colors": [
      "black",
      "green"
    ],
    "sticker_status": "present",
    "free_text": "Rectangular, MIDAS marking, rectangular sticker at the top."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": 0.5056027546525002,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.7541389465332031,
      "final_score": 0.9385347366333009,
      "attribute_scores": {
        "semantic": 0.7541389465332031,
        "color": 1.0,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": 0.4817279279232025,
      "final_score": 0.4329319819808007,
      "attribute_scores": {
        "semantic": 0.4817279279232025,
        "color": 0.5,
        "sticker": 0.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    }
  ]
}
```

## 60fd6277bc07490fbefd8d4b9446093e / 1 / contradictory

흰색과 분홍색의 둥근 물건이고 MIDAS 글자는 없어요.

My object is round, white and pink, with no MIDAS marking.

```json
{
  "conditions": {
    "colors": [
      "white",
      "pink"
    ],
    "free_text": "Round with no MIDAS marking."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## 94b94ac4e53c4314b2bfa42d96c4b34b / 0 / positive

검정 USB이고 테두리가 빨간색이며 SanDisk라고 적혀 있어요.

My black USB memory stick has a crimson border and SanDisk printed along the side.

```json
{
  "conditions": {
    "category": "usb",
    "colors": [
      "black",
      "red"
    ],
    "free_text": "SanDisk printed along the side."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.5306233763694763,
      "final_score": 0.8956940836376615,
      "attribute_scores": {
        "semantic": 0.5306233763694763,
        "category": 1.0,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    }
  ]
}
```

## 94b94ac4e53c4314b2bfa42d96c4b34b / 0 / contradictory

파란 금속 USB이고 Kingston이라고 적혀 있어요.

My blue metal USB drive is labelled Kingston.

```json
{
  "conditions": {
    "category": "usb",
    "colors": [
      "blue"
    ],
    "free_text": "Metal, labelled Kingston."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## cb97b414627b47d8a349c9ca3323d3f1 / 0 / positive

검은 가죽 카드지갑이고 HONOR라는 글자와 카드 슬롯이 있어요.

My black leather card holder has HONOR lettering and a slot for a card.

```json
{
  "conditions": {
    "category": "card_wallet",
    "colors": [
      "black"
    ],
    "free_text": "Leather, HONOR lettering and a slot for a card."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": 0.2579141894976298,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.7124343514442444,
      "final_score": 0.8916520780987209,
      "attribute_scores": {
        "semantic": 0.7124343514442444,
        "category": 0.8,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": 0.3518204987049103,
      "final_score": 0.6337378886010911,
      "attribute_scores": {
        "semantic": 0.3518204987049103,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## cb97b414627b47d8a349c9ca3323d3f1 / 0 / contradictory

흰색 천 지갑이고 VISA라고 적혀 있어요.

My wallet is white fabric with VISA lettering.

```json
{
  "conditions": {
    "category": "wallet",
    "colors": [
      "white"
    ],
    "free_text": "Fabric with VISA lettering."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": [
        "category"
      ]
    }
  ]
}
```

## cb97b414627b47d8a349c9ca3323d3f1 / 1 / positive

검정과 초록색의 직사각형 물건이고 MIDAS 글자와 위쪽 사각 스티커가 있어요.

My rectangular item is black and green, marked MIDAS, with a rectangular sticker at the top.

```json
{
  "conditions": {
    "colors": [
      "black",
      "green"
    ],
    "sticker_status": "present",
    "free_text": "Rectangular, MIDAS marking, rectangular sticker at the top."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": 0.5056027546525002,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.7541389465332031,
      "final_score": 0.9385347366333009,
      "attribute_scores": {
        "semantic": 0.7541389465332031,
        "color": 1.0,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": 0.4817279279232025,
      "final_score": 0.4329319819808007,
      "attribute_scores": {
        "semantic": 0.4817279279232025,
        "color": 0.5,
        "sticker": 0.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    }
  ]
}
```

## cb97b414627b47d8a349c9ca3323d3f1 / 1 / contradictory

흰색과 분홍색의 둥근 물건이고 MIDAS 글자는 없어요.

My object is round, white and pink, with no MIDAS marking.

```json
{
  "conditions": {
    "colors": [
      "white",
      "pink"
    ],
    "free_text": "Round with no MIDAS marking."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## d3dfa2e2135248a399780e4d21a08f0f / 0 / positive

진한 파란 물건이고 왼쪽 아래 포켓몬 캐릭터 스티커가 있어요.

My navy item has a Pokemon character decal near its bottom left corner.

```json
{
  "conditions": {
    "colors": [
      "navy"
    ],
    "sticker_status": "present",
    "free_text": "Pokemon character decal near the bottom left corner."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.5629241466522217,
      "final_score": 0.8282310366630554,
      "attribute_scores": {
        "semantic": 0.5629241466522217,
        "color": 0.9,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## d3dfa2e2135248a399780e4d21a08f0f / 0 / contradictory

노란 물건이고 캐릭터 스티커는 전혀 없어요.

My item is yellow with no character stickers or decals.

```json
{
  "conditions": {
    "colors": [
      "yellow"
    ],
    "sticker_status": "absent",
    "free_text": ""
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.16666666666666669,
      "attribute_scores": {
        "color": 0.0,
        "sticker": 1.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## d3dfa2e2135248a399780e4d21a08f0f / 1 / positive

흰색 물건이고 애플 로고와 카메라 부분이 있으며 손상된 곳이 있어요.

My white device bears an Apple emblem, a camera module and some damage.

```json
{
  "conditions": {
    "colors": [
      "white"
    ],
    "free_text": "Apple emblem, camera module and some damage."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.6033689975738525,
      "final_score": 0.8866768564496722,
      "attribute_scores": {
        "semantic": 0.6033689975738525,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## d3dfa2e2135248a399780e4d21a08f0f / 1 / contradictory

초록색 물건이고 애플 로고와 카메라가 없어요.

My green object has no Apple emblem and no camera module.

```json
{
  "conditions": {
    "colors": [
      "green"
    ],
    "free_text": "No Apple emblem and no camera module."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.0,
      "attribute_scores": {
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## ed1419ed60194204be814b8393c12a43 / 1 / positive

흰색 폰이고 카메라 두 개, 뒷면 금, 왼쪽 아래 작은 흠집이 있어요.

My white handset has two rear lenses, a fracture on its back, and a small nick near the lower left.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "white"
    ],
    "free_text": "Two rear lenses, fracture on the back and small nick near the lower left."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.37630370259284973,
      "final_score": 0.861400822798411,
      "attribute_scores": {
        "semantic": 0.37630370259284973,
        "category": 1.0,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    }
  ]
}
```

## ed1419ed60194204be814b8393c12a43 / 1 / contradictory

빨간 폰이고 렌즈가 하나이며 금이나 흠집이 없어요.

My red phone has one rear lens and no cracks, scratches or chips.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "red"
    ],
    "free_text": "One rear lens and no cracks, scratches or chips."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## f7e7af5f8fc742ea93d49212029ecb79 / 0 / positive

진한 파란색 폰이고 뒷면 왼쪽 아래에 캐릭터 스티커가 있어요.

My handset is navy blue and has an animated character decal near the lower left of its rear.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "navy"
    ],
    "sticker_status": "present",
    "free_text": "Animated character decal near the lower left of the rear."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.36617839336395264,
      "final_score": 0.8232356786727905,
      "attribute_scores": {
        "semantic": 0.36617839336395264,
        "category": 1.0,
        "color": 0.9,
        "sticker": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.3750000000000001,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0,
        "sticker": 1.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## f7e7af5f8fc742ea93d49212029ecb79 / 0 / contradictory

밝은 노란색이고 스티커가 전혀 없는 폰이에요.

My phone is bright yellow with no stickers or decals anywhere.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "yellow"
    ],
    "sticker_status": "absent",
    "free_text": ""
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.25000000000000006,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.25000000000000006,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0,
        "sticker": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## f7e7af5f8fc742ea93d49212029ecb79 / 1 / positive

흰색 폰이고 뒤에 카메라 두 개와 애플 로고가 있으며 금이 가 있어요.

I lost a white smartphone with a pair of rear cameras, an Apple emblem and a crack on its back.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "white"
    ],
    "free_text": "A pair of rear cameras, an Apple emblem and a crack on the back."
  },
  "decision": {
    "status": "matched",
    "selected_id": 1,
    "top_candidate_id": 1,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 1,
      "cosine_similarity": 0.5863776206970215,
      "final_score": 0.9080839157104492,
      "attribute_scores": {
        "semantic": 0.5863776206970215,
        "category": 1.0,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    },
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## f7e7af5f8fc742ea93d49212029ecb79 / 1 / contradictory

빨간 폰이고 카메라가 하나이며 뒷면 손상이 없어요.

My phone is red, has only one rear camera, and has no damage or cracks on the back.

```json
{
  "conditions": {
    "category": "phone",
    "colors": [
      "red"
    ],
    "free_text": "Only one rear camera and no damage or cracks on the back."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    },
    {
      "id": 1,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```

## qwen_only_2fcc3f870f2d4d1e8c84d528e95c5b10 / 0 / positive

주황색과 흰색 립밤이고 원통형이며 AVENZA라고 적혀 있어요.

My cylindrical lip balm is orange and white and carries AVENZA lettering.

```json
{
  "conditions": {
    "category": "lip_balm",
    "colors": [
      "orange",
      "white"
    ],
    "free_text": "Cylindrical, AVENZA lettering."
  },
  "decision": {
    "status": "matched",
    "selected_id": 0,
    "top_candidate_id": 0,
    "margin": null,
    "reasons": []
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": 0.6493476629257202,
      "final_score": 0.9220772584279379,
      "attribute_scores": {
        "semantic": 0.6493476629257202,
        "category": 1.0,
        "color": 1.0
      },
      "rejection_reasons": [],
      "unknown_attributes": []
    }
  ]
}
```

## qwen_only_2fcc3f870f2d4d1e8c84d528e95c5b10 / 0 / contradictory

파란색과 검정 립밤이고 네모난 모양이며 NIVEA라고 적혀 있어요.

My lip balm is blue and black, square shaped, and labelled NIVEA.

```json
{
  "conditions": {
    "category": "lip_balm",
    "colors": [
      "blue",
      "black"
    ],
    "free_text": "Square shaped, labelled NIVEA."
  },
  "decision": {
    "status": "no_match",
    "selected_id": null,
    "reason": "no_eligible_candidates"
  },
  "scores": [
    {
      "id": 0,
      "cosine_similarity": null,
      "final_score": 0.28571428571428575,
      "attribute_scores": {
        "category": 1.0,
        "color": 0.0
      },
      "rejection_reasons": [
        "color_mismatch"
      ],
      "unknown_attributes": []
    }
  ]
}
```