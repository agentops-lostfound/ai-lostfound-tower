# Qwen 저장 특징 전체 후보 매칭 점검

## 읽는 법

- 실행 폴더별로 후보 N개를 모아, 각 후보에 맞는 설명 N개와 모순되는 설명 N개를 만들었습니다. 각 질의는 해당 실행의 후보 N개 전체와 비교했습니다.
- 한국어 문장은 사람이 읽기 위한 설명이고 실제 모델 입력은 함께 표시한 영어 문장입니다. 한국어 번역 기능을 시험한 결과가 아닙니다.
- **정답은 사진이 아니라 저장된 Qwen JSON에 맞춘 약한 정답입니다.** 일부 HONOR/MIDAS/AVENZA 등의 글자는 기존 사진에서 오독이 확인됐습니다. Qwen 오류까지 따라 맞춘 것이 실제 물품 식별 성공은 아닙니다.
- 모순 설명은 대상 후보의 색상/글자/스티커 등과 일부러 다르게 썼습니다. 다른 후보와도 맞지 않을 수 있어 기대 결과는 자동 확정이 아니라 보류/재질문입니다.
- 현재 코드는 거절·추가질문 기능 없이 항상 순위를 반환합니다. 모순 설명의 높은 점수나 1위는 정답 판정이 아닙니다.
- 후보가 1개인 경우 맞는 설명도 틀린 설명도 무조건 1위입니다. 구별 성능으로 집계하면 안 됩니다.
- 같은 사진/특징이 여러 실행에 중복됩니다. 아래 건수는 독립된 평가 데이터 수가 아닙니다. 숫자는 확률이 아닌 -1~1 코사인 유사도입니다.

## 전체 요약

- 조사 실행 폴더: 13개 / 특징이 있는 실행: 10개
- 개별 Qwen 특징 파일: 17개 / 질의: 34개(후보별 긍정 1개 + 모순 1개)
- 복수 후보 실행의 긍정 설명에서 의도한 후보가 1위: **14/14건**. 손으로 만든 설명이며 일반 정확도로 해석하지 않습니다.

| 실행 폴더 | 실행 상태 | 후보 수 | 긍정 설명 목표 1위 | 비고 |
|---|---|---:|---:|---|
| `262a3fbb20e1489495aa30dd55cf18e9` | complete | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `2fa66a50d89e4a788480166975c2a7b6` | complete | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `4560b8a53f4b4eeb96718439dc8f595a` | complete | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `60fd6277bc07490fbefd8d4b9446093e` | complete | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `8e3576993aed441c9825e822d67209fc` | failed | 0 | 0/0 | 비교할 성공 특징 없음 |
| `94b94ac4e53c4314b2bfa42d96c4b34b` | complete | 1 | 1/1 | 단일 후보: 구별 평가 불가 |
| `9dc58e37e6814989bd48c3e5ae59c9bb` | running | 0 | 0/0 | 비교할 성공 특징 없음 |
| `cb97b414627b47d8a349c9ca3323d3f1` | 이전 형식 | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `cbedfdccb1504e1d81ea1c8ffc745219` | cancelled | 0 | 0/0 | 비교할 성공 특징 없음 |
| `d3dfa2e2135248a399780e4d21a08f0f` | complete | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `ed1419ed60194204be814b8393c12a43` | failed | 1 | 1/1 | 단일 후보: 구별 평가 불가; 실패 실행의 성공한 부분 결과만 사용 |
| `f7e7af5f8fc742ea93d49212029ecb79` | complete | 2 | 2/2 | 동일 실행 내 전체 후보 비교 |
| `qwen_only_2fcc3f870f2d4d1e8c84d528e95c5b10` | complete | 1 | 1/1 | 단일 후보: 구별 평가 불가 |

## 실행 262a3fbb20e1489495aa30dd55cf18e9

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "phone",
  "colors": [
    "dark blue"
  ],
  "shape": "rectangular",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "cartoon",
      "position": "lower left"
    }
  ],
  "distinctive_features": [
    "a cartoon sticker of a Pokémon character on the back of the phone"
  ]
}
```


**맞는 설명**

> 진한 파란색 폰이고 뒷면 왼쪽 아래에 캐릭터 스티커가 있어요.

영어 입력: `My handset is navy blue and has an animated character decal near the lower left of its rear.`

- 전체 후보 순위: **object_0: 0.4320 → object_1: 0.3988**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.0332 (판정 기준 미설정)

**일부러 다른 설명**

> 밝은 노란색이고 스티커가 전혀 없는 폰이에요.

영어 입력: `My phone is bright yellow with no stickers or decals anywhere.`

- 전체 후보 순위: **object_1: 0.4488 → object_0: 0.4052**
- object_0 순위: 2위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.0435 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "phone",
  "colors": [
    "white"
  ],
  "shape": "rectangular",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "Apple logo"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "triangle",
      "position": "center"
    }
  ],
  "distinctive_features": [
    "crack on the back",
    "damaged Apple logo",
    "camera module with two lenses"
  ]
}
```


**맞는 설명**

> 흰색 폰이고 뒤에 카메라 두 개와 애플 로고가 있으며 금이 가 있어요.

영어 입력: `I lost a white smartphone with a pair of rear cameras, an Apple emblem and a crack on its back.`

- 전체 후보 순위: **object_1: 0.5324 → object_0: 0.3253**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.2071 (판정 기준 미설정)

**일부러 다른 설명**

> 빨간 폰이고 카메라가 하나이며 뒷면 손상이 없어요.

영어 입력: `My phone is red, has only one rear camera, and has no damage or cracks on the back.`

- 전체 후보 순위: **object_1: 0.3730 → object_0: 0.1800**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1930 (판정 기준 미설정)

## 실행 2fa66a50d89e4a788480166975c2a7b6

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "wallet",
  "colors": [
    "black"
  ],
  "shape": "rectangle",
  "wallet_type": "cardholder",
  "materials": [
    "leather"
  ],
  "logos_or_text": [
    "HONOR"
  ],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": [
    "camera module",
    "card slot"
  ]
}
```


**맞는 설명**

> 검은 가죽 카드지갑이고 HONOR라는 글자와 카드 슬롯이 있어요.

영어 입력: `My black leather card holder has HONOR lettering and a slot for a card.`

- 전체 후보 순위: **object_0: 0.6293 → object_1: 0.3243**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.3049 (판정 기준 미설정)

**일부러 다른 설명**

> 흰색 천 지갑이고 VISA라고 적혀 있어요.

영어 입력: `My wallet is white fabric with VISA lettering.`

- 전체 후보 순위: **object_0: 0.4611 → object_1: 0.2739**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1872 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "other",
  "colors": [
    "black",
    "green"
  ],
  "shape": "rectangular",
  "wallet_type": null,
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "MIDAS"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "rectangular",
      "position": "top"
    }
  ],
  "distinctive_features": [
    "logo"
  ]
}
```


**맞는 설명**

> 검정과 초록색의 직사각형 물건이고 MIDAS 글자와 위쪽 사각 스티커가 있어요.

영어 입력: `My rectangular item is black and green, marked MIDAS, with a rectangular sticker at the top.`

- 전체 후보 순위: **object_1: 0.6384 → object_0: 0.4980**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.1404 (판정 기준 미설정)

**일부러 다른 설명**

> 흰색과 분홍색의 둥근 물건이고 MIDAS 글자는 없어요.

영어 입력: `My object is round, white and pink, with no MIDAS marking.`

- 전체 후보 순위: **object_1: 0.3961 → object_0: 0.2610**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1351 (판정 기준 미설정)

## 실행 4560b8a53f4b4eeb96718439dc8f595a

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "other",
  "colors": [
    "black"
  ],
  "shape": "rectangle",
  "wallet_type": null,
  "materials": [
    "plastic"
  ],
  "logos_or_text": [],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": [
    "screen is black",
    "phone is in a case"
  ]
}
```


**맞는 설명**

> 검은 폰이고 검정 화면과 케이스가 있으며 스티커는 없어요.

영어 입력: `My black phone is inside a protective cover, has a dark screen and no stickers.`

- 전체 후보 순위: **object_0: 0.5806 → object_1: 0.2876**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.2930 (판정 기준 미설정)

**일부러 다른 설명**

> 초록색 폰이고 화면이 켜져 있으며 케이스가 없어요.

영어 입력: `My green phone has a lit screen and no protective cover.`

- 전체 후보 순위: **object_0: 0.3740 → object_1: 0.0839**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.2901 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "wallet",
  "colors": [
    "black"
  ],
  "shape": "rectangle",
  "wallet_type": "personal",
  "materials": [
    "leather"
  ],
  "logos_or_text": [
    "logo"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "square",
      "position": "bottom-right"
    }
  ],
  "distinctive_features": [
    "small square logo"
  ]
}
```


**맞는 설명**

> 검은 가죽 지갑이고 오른쪽 아래 작은 정사각형 표시가 있어요.

영어 입력: `My black leather wallet has a little square emblem at the bottom right.`

- 전체 후보 순위: **object_1: 0.6396 → object_0: 0.3832**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.2564 (판정 기준 미설정)

**일부러 다른 설명**

> 노란 천 지갑이고 오른쪽 아래 표시가 없어요.

영어 입력: `My yellow cloth wallet has no marking at the lower right.`

- 전체 후보 순위: **object_1: 0.4504 → object_0: 0.2567**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1936 (판정 기준 미설정)

## 실행 60fd6277bc07490fbefd8d4b9446093e

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "wallet",
  "colors": [
    "black"
  ],
  "shape": "rectangle",
  "wallet_type": "cardholder",
  "materials": [
    "leather"
  ],
  "logos_or_text": [
    "HONOR"
  ],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": [
    "camera module",
    "card slot"
  ]
}
```


**맞는 설명**

> 검은 가죽 카드지갑이고 HONOR라는 글자와 카드 슬롯이 있어요.

영어 입력: `My black leather card holder has HONOR lettering and a slot for a card.`

- 전체 후보 순위: **object_0: 0.6293 → object_1: 0.3243**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.3049 (판정 기준 미설정)

**일부러 다른 설명**

> 흰색 천 지갑이고 VISA라고 적혀 있어요.

영어 입력: `My wallet is white fabric with VISA lettering.`

- 전체 후보 순위: **object_0: 0.4611 → object_1: 0.2739**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1872 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "other",
  "colors": [
    "black",
    "green"
  ],
  "shape": "rectangular",
  "wallet_type": null,
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "MIDAS"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "rectangular",
      "position": "top"
    }
  ],
  "distinctive_features": [
    "logo"
  ]
}
```


**맞는 설명**

> 검정과 초록색의 직사각형 물건이고 MIDAS 글자와 위쪽 사각 스티커가 있어요.

영어 입력: `My rectangular item is black and green, marked MIDAS, with a rectangular sticker at the top.`

- 전체 후보 순위: **object_1: 0.6384 → object_0: 0.4980**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.1404 (판정 기준 미설정)

**일부러 다른 설명**

> 흰색과 분홍색의 둥근 물건이고 MIDAS 글자는 없어요.

영어 입력: `My object is round, white and pink, with no MIDAS marking.`

- 전체 후보 순위: **object_1: 0.3961 → object_0: 0.2610**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1351 (판정 기준 미설정)

## 실행 94b94ac4e53c4314b2bfa42d96c4b34b

후보 1개 / 긍정 1개 + 모순 1개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "usb",
  "colors": [
    "black",
    "red"
  ],
  "shape": "rectangular",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "SanDisk"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "rectangle",
      "position": "top"
    }
  ],
  "distinctive_features": [
    "text on the side",
    "red edge"
  ]
}
```


**맞는 설명**

> 검정 USB이고 테두리가 빨간색이며 SanDisk라고 적혀 있어요.

영어 입력: `My black USB memory stick has a crimson border and SanDisk printed along the side.`

- 전체 후보 순위: **object_0: 0.5829**
- object_0 순위: 1위
- 해석: 목표 후보 1위 / 단일 후보라 순위로 구별 불가

**일부러 다른 설명**

> 파란 금속 USB이고 Kingston이라고 적혀 있어요.

영어 입력: `My blue metal USB drive is labelled Kingston.`

- 전체 후보 순위: **object_0: 0.4549**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환 / 단일 후보라 순위로 구별 불가

## 실행 cb97b414627b47d8a349c9ca3323d3f1

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "wallet",
  "colors": [
    "black"
  ],
  "shape": "rectangle",
  "wallet_type": "cardholder",
  "materials": [
    "leather"
  ],
  "logos_or_text": [
    "HONOR"
  ],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": [
    "camera module",
    "card slot"
  ]
}
```


**맞는 설명**

> 검은 가죽 카드지갑이고 HONOR라는 글자와 카드 슬롯이 있어요.

영어 입력: `My black leather card holder has HONOR lettering and a slot for a card.`

- 전체 후보 순위: **object_0: 0.6293 → object_1: 0.3243**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.3049 (판정 기준 미설정)

**일부러 다른 설명**

> 흰색 천 지갑이고 VISA라고 적혀 있어요.

영어 입력: `My wallet is white fabric with VISA lettering.`

- 전체 후보 순위: **object_0: 0.4611 → object_1: 0.2739**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1872 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "other",
  "colors": [
    "black",
    "green"
  ],
  "shape": "rectangular",
  "wallet_type": null,
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "MIDAS"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "rectangular",
      "position": "top"
    }
  ],
  "distinctive_features": [
    "logo"
  ]
}
```


**맞는 설명**

> 검정과 초록색의 직사각형 물건이고 MIDAS 글자와 위쪽 사각 스티커가 있어요.

영어 입력: `My rectangular item is black and green, marked MIDAS, with a rectangular sticker at the top.`

- 전체 후보 순위: **object_1: 0.6384 → object_0: 0.4980**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.1404 (판정 기준 미설정)

**일부러 다른 설명**

> 흰색과 분홍색의 둥근 물건이고 MIDAS 글자는 없어요.

영어 입력: `My object is round, white and pink, with no MIDAS marking.`

- 전체 후보 순위: **object_1: 0.3961 → object_0: 0.2610**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1351 (판정 기준 미설정)

## 실행 d3dfa2e2135248a399780e4d21a08f0f

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "other",
  "colors": [
    "dark blue"
  ],
  "shape": "rectangle",
  "wallet_type": null,
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "pokemon"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "cartoon",
      "position": "bottom left"
    }
  ],
  "distinctive_features": [
    "pokemon sticker"
  ]
}
```


**맞는 설명**

> 진한 파란 물건이고 왼쪽 아래 포켓몬 캐릭터 스티커가 있어요.

영어 입력: `My navy item has a Pokemon character decal near its bottom left corner.`

- 전체 후보 순위: **object_0: 0.5369 → object_1: 0.2645**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.2724 (판정 기준 미설정)

**일부러 다른 설명**

> 노란 물건이고 캐릭터 스티커는 전혀 없어요.

영어 입력: `My item is yellow with no character stickers or decals.`

- 전체 후보 순위: **object_0: 0.4809 → object_1: 0.4707**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.0102 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "other",
  "colors": [
    "white"
  ],
  "shape": "rectangle",
  "wallet_type": null,
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "Apple logo"
  ],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": [
    "camera module",
    "damaged area"
  ]
}
```


**맞는 설명**

> 흰색 물건이고 애플 로고와 카메라 부분이 있으며 손상된 곳이 있어요.

영어 입력: `My white device bears an Apple emblem, a camera module and some damage.`

- 전체 후보 순위: **object_1: 0.6212 → object_0: 0.2928**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.3284 (판정 기준 미설정)

**일부러 다른 설명**

> 초록색 물건이고 애플 로고와 카메라가 없어요.

영어 입력: `My green object has no Apple emblem and no camera module.`

- 전체 후보 순위: **object_1: 0.5336 → object_0: 0.2709**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.2627 (판정 기준 미설정)

## 실행 ed1419ed60194204be814b8393c12a43

후보 1개 / 긍정 1개 + 모순 1개.

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "phone",
  "colors": [
    "white"
  ],
  "shape": "rectangular",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "Apple logo"
  ],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": [
    "camera module with two lenses",
    "single visible crack on the back",
    "small chip or scratch near the bottom left corner"
  ]
}
```


**맞는 설명**

> 흰색 폰이고 카메라 두 개, 뒷면 금, 왼쪽 아래 작은 흠집이 있어요.

영어 입력: `My white handset has two rear lenses, a fracture on its back, and a small nick near the lower left.`

- 전체 후보 순위: **object_1: 0.3571**
- object_1 순위: 1위
- 해석: 목표 후보 1위 / 단일 후보라 순위로 구별 불가

**일부러 다른 설명**

> 빨간 폰이고 렌즈가 하나이며 금이나 흠집이 없어요.

영어 입력: `My red phone has one rear lens and no cracks, scratches or chips.`

- 전체 후보 순위: **object_1: 0.4048**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환 / 단일 후보라 순위로 구별 불가

## 실행 f7e7af5f8fc742ea93d49212029ecb79

후보 2개 / 긍정 2개 + 모순 2개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "phone",
  "colors": [
    "dark blue"
  ],
  "shape": "rectangular",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "cartoon",
      "position": "lower left"
    }
  ],
  "distinctive_features": [
    "a cartoon sticker of a Pokémon character on the back of the phone"
  ]
}
```


**맞는 설명**

> 진한 파란색 폰이고 뒷면 왼쪽 아래에 캐릭터 스티커가 있어요.

영어 입력: `My handset is navy blue and has an animated character decal near the lower left of its rear.`

- 전체 후보 순위: **object_0: 0.4320 → object_1: 0.3988**
- object_0 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.0332 (판정 기준 미설정)

**일부러 다른 설명**

> 밝은 노란색이고 스티커가 전혀 없는 폰이에요.

영어 입력: `My phone is bright yellow with no stickers or decals anywhere.`

- 전체 후보 순위: **object_1: 0.4488 → object_0: 0.4052**
- object_0 순위: 2위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.0435 (판정 기준 미설정)

### object_1

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "phone",
  "colors": [
    "white"
  ],
  "shape": "rectangular",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "Apple logo"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "triangle",
      "position": "center"
    }
  ],
  "distinctive_features": [
    "crack on the back",
    "damaged Apple logo",
    "camera module with two lenses"
  ]
}
```


**맞는 설명**

> 흰색 폰이고 뒤에 카메라 두 개와 애플 로고가 있으며 금이 가 있어요.

영어 입력: `I lost a white smartphone with a pair of rear cameras, an Apple emblem and a crack on its back.`

- 전체 후보 순위: **object_1: 0.5324 → object_0: 0.3253**
- object_1 순위: 1위
- 해석: 목표 후보 1위
- 1·2위 차이: 0.2071 (판정 기준 미설정)

**일부러 다른 설명**

> 빨간 폰이고 카메라가 하나이며 뒷면 손상이 없어요.

영어 입력: `My phone is red, has only one rear camera, and has no damage or cracks on the back.`

- 전체 후보 순위: **object_1: 0.3730 → object_0: 0.1800**
- object_1 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환
- 1·2위 차이: 0.1930 (판정 기준 미설정)

## 실행 qwen_only_2fcc3f870f2d4d1e8c84d528e95c5b10

후보 1개 / 긍정 1개 + 모순 1개.

### object_0

[원본 특징Original feature JSON and crop images are local-only; extracted features are listed below.

```json
{
  "category": "lip_balm",
  "colors": [
    "orange",
    "white"
  ],
  "shape": "cylinder",
  "materials": [
    "plastic"
  ],
  "logos_or_text": [
    "AVENZA"
  ],
  "sticker_status": "present",
  "stickers": [
    {
      "shape": "rectangle",
      "position": "side"
    }
  ],
  "distinctive_features": [
    "orange cap",
    "white cap",
    "text on cap"
  ]
}
```

**맞는 설명**

> 주황색과 흰색 립밤이고 원통형이며 AVENZA라고 적혀 있어요.

영어 입력: `My cylindrical lip balm is orange and white and carries AVENZA lettering.`

- 전체 후보 순위: **object_0: 0.6539**
- object_0 순위: 1위
- 해석: 목표 후보 1위 / 단일 후보라 순위로 구별 불가

**일부러 다른 설명**

> 파란색과 검정 립밤이고 네모난 모양이며 NIVEA라고 적혀 있어요.

영어 입력: `My lip balm is blue and black, square shaped, and labelled NIVEA.`

- 전체 후보 순위: **object_0: 0.5043**
- object_0 순위: 1위
- 해석: 의도적 모순 입력. 현재 거절 기능 없어 순위만 반환 / 단일 후보라 순위로 구별 불가

## 다음에 확인할 것

1. 모순·무관 설명에도 1위가 나오는 구조라, 실제 정답이 없는 질의로 보류/추가질문 기준을 따로 정해야 합니다.
2. 임베딩은 색상·글자·부정문을 완벽히 구분하지 않습니다. 서로 모순되는 관찰은 별도 비교 근거로 표시하는 기능이 필요합니다.
3. 중복 실행을 제거하고, 더 많은 실제 물품과 사람이 독립적으로 작성한 설명으로 평가해야 합니다.
4. Qwen의 잘못 읽은 글자를 기준으로 잘 맞췄더라도 실제 물품과는 다를 수 있습니다. 사진/사람 정답과의 별도 평가가 필요합니다.
