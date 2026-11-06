# web/intake — 습득물 등록기계 화면 (LF-2, 김재민)

> 11/5: `intake_machine/` 에서 이 폴더로 옮겼다(화면 지도 `web/README.md`). 화면 파일은 `index.html`

습득자가 역의 등록기계(태블릿 웹 화면)에서 물건을 맡기는 화면이다. 관제탑 API 와 연결 방법은 아래가 기준이다(11/3, 변재원).
화면 흐름 그림: 팀 공유 아티팩트 "지갑 한 개의 여정" 2번 역.

## 1. 화면 4장 (최대한 간단하게)
| 순서 | 화면 | 받는 값 | 필수 |
| --- | --- | --- | --- |
| 1 | 물건을 상자에 넣고 문 닫기 → 사진 찍기 | 사진(파일 위치) | 자동 |
| 2 | 어디서 주우셨나요? 추천 칩 + 직접 입력 | 장소 | **필수** |
| 3 | 연락처를 남기시겠어요? 이름·전화번호 | 둘 다 **선택**(건너뛰기 가능) | 선택 |
| 4 | 접수 완료 — 접수 번호 크게 표시, 10초 뒤 처음 화면 | - | - |

- 물건 종류·색·재질은 습득자가 입력하지 않는다 → 사진을 Qwen 이 분석해 뒤에서 채운다(물건당 수십 초라 습득자를 기다리게 하지 않음)
- 발견 시각은 받지 않는다(접수 시각 자동 저장, MVP)
- 연락처 화면 안내 문구: "주인이 찾아가면 감사 연락에만 씁니다. 인계 30일 뒤 자동 삭제됩니다."
- 1번 화면에 "현금·위험물은 역무실로" 안내

## 2. 관제탑 API (관제탑 PC `http://<관제탑 PC 주소>:8100`)
### 추천 장소 — 2번 화면
```
GET /places?machine_id=KIOSK-A
→ [{"place_id": 1, "label": "해운대역 승강장"}, {"place_id": 3, "label": "화장실"}, ...]   (많이 고른 순)
```
### 접수 — 4번 화면으로 넘어갈 때
```
POST /items
{
  "machine_id": "KIOSK-A",              // 필수: 기계 번호(KIOSK-A 해운대, KIOSK-C 서면, CENTER 부산역 본센터)
  "place_id": 3,                         // 추천 칩을 골랐을 때만
  "place_text": "화장실",                 // 필수: 고른 칩 글자 또는 직접 입력(128자 이하)
  "finder": {"name": "김습득", "phone": "010-1234-5678"},   // 선택: 둘 다 비우면 저장 안 함(저장 = 동의)
  "photo": "data:image/jpeg;base64,/9j/4AAQ..."             // 선택(11/4): 찍은 사진 data URL 그대로(jpeg·png·webp, 5MB 이하)
}
→ {"item_id": "A-20261103-0001", "received_at": "...", "status": "등록기계 보관",
   "place_text": "화장실", "contact_saved": true}
```
- 받지 않는 칸(물건 특징, 발견 시각 등)을 보내면 422 와 이유가 돌아온다
- `photo` 는 관제탑이 형식·크기·실제 파일 종류를 확인하고 `data/photos/기계번호/` 에 저장, DB 에는 경로만 남긴다(사진은 Git 에 안 올림). 이미 저장된 사진 경로를 줄 때만 `photo_path`(둘 중 하나)
- 응답에는 연락처가 나오지 않는다(`contact_saved` 로 저장 여부만)

### 특징 채우기 — 뒤에서 도는 Qwen 작업(김건태 LF-3)
```
POST /items/A-20261103-0001/features
{"qwen": { ...general_items_v1 특징(result_with_qwen.json 의 objects[].qwen.features)... }, "confidence": 0.9}
→ {"item_id": "...", "category": "지갑", "features": {"color": "갈색", "shape": "...", "material": "...", "confidence": 0.9}}
```
- 공개 특징(색·모양·재질)과 비공개 특징(표시·글자 = 확인 질문 정답)을 나눠 저장한다. 응답에는 공개 특징만

## 2-1. 화면 연결 방법 (11/5 — `web/intake/index.html`)
**화면은 관제탑이 직접 열어 준다**: `http://<관제탑 PC 주소>:8100/intake?machine=KIOSK-A`
- 같은 주소에서 열리므로 `fetch("/places?...")` 처럼 앞부분 없이 부르면 된다(다른 주소에서 열면 브라우저가 막음)
- 관제탑은 `web/intake/index.html` 을 연다(파일을 고치면 새로 고침만 하면 됨)

시안에서 바꿀 곳(위 1장 결정 기준)
| 지금 | 바꿀 것 |
| --- | --- |
| 물건 종류(`category`)·상세 설명(`description`) 칸 | 삭제 — Qwen 이 사진으로 채움(보내면 422) |
| 장소 빠른 버튼(고정) | `GET /places?machine_id=…` 결과로 칩 만들기, 고르면 `place_id`·`place_text` |
| 이름·전화 `required` | `required` 빼고 [건너뛰기] — 비우면 `finder` 를 보내지 않음 |
| 접수 번호를 화면이 만듦(`A-YYMMDD-무작위`) | `POST /items` 응답의 `item_id` 를 크게 표시(중복 없음) |
| JSON 다운로드(전화번호·사진 포함) | 삭제 — 개인정보가 파일로 남지 않게 |
| 접수 완료 화면 | 10초 뒤 처음 화면, 연락처는 다시 보여 주지 않음 |

제출 부분 예시(그대로 붙여 써도 됨)
```js
const machine = new URLSearchParams(location.search).get('machine') || 'KIOSK-A';
// 추천 장소 칩
const places = await fetch('/places?machine_id=' + encodeURIComponent(machine)).then(r => r.json());
// 접수
const body = { machine_id: machine, place_text: $('location').value.trim(), photo: selectedPhotoData };
if (chosenPlaceId) body.place_id = chosenPlaceId;
const name = $('finder-name').value.trim(), phone = $('finder-phone').value.trim();
if (name || phone) body.finder = { name: name || null, phone: phone || null };
const res = await fetch('/items', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const data = await res.json();
if (res.ok) showReceipt(data.item_id);                         // 접수 번호 = 서버가 준 값
else if (res.status === 422) showError(data.detail);           // 이유 그대로 보여 주기
else showError('잠시 후 다시 해 주세요. 급하면 역무실로 와 주세요.');   // 503 등
```

## 3. 오류
| 코드 | 뜻 | 화면에서 |
| --- | --- | --- |
| 422 | 입력 형식이 틀림(장소 비움, 전화번호 형식 등) | 이유를 보여 주고 다시 입력 |
| 404 | 없는 접수 번호(특징 채우기) | Qwen 작업 쪽 확인 |
| 503 | DB 연결 실패 | "잠시 후 다시" + 역무실 안내 |

## 4. 확인 방법
- 관제탑 켜기 → 브라우저 `http://127.0.0.1:8100/docs` 에서 `POST /items` 를 직접 눌러 볼 수 있다
- 화면: `http://127.0.0.1:8100/intake?machine=KIOSK-A` → 접수 후 직원 화면·DB 에 접수 번호가 생기는지
- 같은 교육원 안의 다른 기기(태블릿)에서 열려면 관제탑을 `--host 0.0.0.0` 으로 켜야 함(외부 공개는 TBD, 지금은 관제탑 PC 에서만)
- 시험: `python -m unittest tests.test_intake`
