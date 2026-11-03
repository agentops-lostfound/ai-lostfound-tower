// 분실인 화면 시안: 8단계 흐름. 서버 연결 없이 mock-data.js 만 사용한다.
(function () {
  "use strict";
  var M = window.MOCK;
  var STEPS = ["필수 동의", "신분증 OCR", "물건 등록", "물건 특징", "후보 3", "확인 질문", "승인", "수령 예약"];
  var state = { step: 0, consent: {}, ocr: null, category: "", lostDate: "", place: "",
                features: "", picked: null, answers: ["", ""], approved: false, slot: "" };

  var screen = document.getElementById("screen");
  var stepsEl = document.getElementById("steps");
  var prev = document.getElementById("prev");
  var next = document.getElementById("next");

  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  function field(label, input) {
    var l = el("label", { text: label });
    l.appendChild(input);
    return l;
  }
  function bind(input, key, idx) {
    input.addEventListener("input", function () {
      if (idx === undefined) state[key] = input.value; else state[key][idx] = input.value;
      refresh();
    });
    return input;
  }

  function canNext() {
    switch (state.step) {
      case 0: return M.consents.every(function (c) { return state.consent[c.id]; });
      case 1: return !!state.ocr;
      case 2: return !!state.category && !!state.lostDate && state.place.trim() !== "";
      case 3: return state.features.trim() !== "";
      case 4: return !!state.picked;
      case 5: return state.answers.every(function (a) { return a.trim() !== ""; });
      case 6: return state.approved;
      default: return false;
    }
  }

  var views = [
    function () { // 0 필수 동의
      var s = el("section", {}, [el("h2", { text: "필수 동의" })]);
      M.consents.forEach(function (c) {
        var box = el("input", { type: "checkbox" });
        box.checked = !!state.consent[c.id];
        box.addEventListener("change", function () { state.consent[c.id] = box.checked; refresh(); });
        s.appendChild(el("label", { "class": "check" }, [box, el("span", { text: c.text })]));
      });
      return s;
    },
    function () { // 1 신분증 OCR (가상)
      var s = el("section", {}, [el("h2", { text: "신분증 사진 등록 (OCR)" }),
        el("p", { "class": "warn", text: "가상 신분증 이미지만 올려 주세요. 시안에서는 사진을 읽지 않고 가짜 결과를 보여 줍니다." })]);
      var f = el("input", { type: "file", accept: "image/*" });
      f.addEventListener("change", function () { state.ocr = f.files.length ? M.fakeOcr : null; render(); });
      s.appendChild(field("신분증 사진", f));
      if (state.ocr) {
        var kv = el("div", { "class": "kv" });
        Object.keys(state.ocr).forEach(function (k) {
          kv.appendChild(el("b", { text: k })); kv.appendChild(el("span", { text: state.ocr[k] }));
        });
        s.appendChild(el("h3", { text: "OCR 결과(가상)" })); s.appendChild(kv);
      }
      return s;
    },
    function () { // 2 찾을 물건 등록
      var sel = el("select");
      sel.appendChild(el("option", { value: "", text: "선택" }));
      M.categories.forEach(function (c) { sel.appendChild(el("option", { value: c, text: c })); });
      sel.value = state.category;
      var d = el("input", { type: "date", value: state.lostDate });
      var p = el("input", { type: "text", value: state.place, placeholder: "예: 도서관 2층" });
      return el("section", {}, [el("h2", { text: "찾을 분실물 등록" }),
        field("종류", bind(sel, "category")), field("잃어버린 날짜", bind(d, "lostDate")),
        field("잃어버린 장소", bind(p, "place"))]);
    },
    function () { // 3 특징
      var t = el("textarea", { rows: "4", placeholder: "색·재질·브랜드·흠집·내용물 등 (음성·사진 입력은 이후 연결)" });
      t.value = state.features;
      return el("section", {}, [el("h2", { text: "분실물 특징" }), field("특징 설명", bind(t, "features"))]);
    },
    function () { // 4 후보 3
      var s = el("section", {}, [el("h2", { text: "분실물 후보 3" }),
        el("p", { "class": "warn", text: "일치도는 참고용입니다. 확실하지 않으면 자동 반환되지 않습니다." })]);
      M.candidates.forEach(function (c) {
        var card = el("div", { "class": "cand" + (state.picked === c.id ? " sel" : ""), tabindex: "0", role: "button" }, [
          el("span", { "class": "score", text: "일치도 " + Math.round(c.score * 100) + "%" }),
          el("b", { text: c.id + " · " + c.name }), el("div", { text: c.place }), el("div", { text: c.features })]);
        function pick() { state.picked = c.id; render(); }
        card.addEventListener("click", pick);
        card.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
        s.appendChild(card);
      });
      return s;
    },
    function () { // 5 확인 질문
      var s = el("section", {}, [el("h2", { text: "확인 질문" }),
        el("p", { text: "선택한 후보: " + state.picked })]);
      M.questions.forEach(function (q, i) {
        var a = el("input", { type: "text", value: state.answers[i] });
        s.appendChild(field(q, bind(a, "answers", i)));
      });
      return s;
    },
    function () { // 6 승인
      var box = el("input", { type: "checkbox" });
      box.checked = state.approved;
      box.addEventListener("change", function () { state.approved = box.checked; refresh(); });
      return el("section", {}, [el("h2", { text: "승인" }),
        el("p", { text: "후보 " + state.picked + " 이(가) 내 물건이 맞습니다." }),
        el("label", { "class": "check" }, [box, el("span", { text: "맞습니다. 이 물건의 수령을 승인합니다." })])]);
    },
    function () { // 7 수령 예약
      var s = el("section", {}, [el("h2", { text: "수령 예약" })]);
      var sel = el("select");
      sel.appendChild(el("option", { value: "", text: "시간 선택" }));
      M.slots.forEach(function (x) { sel.appendChild(el("option", { value: x, text: x })); });
      sel.value = state.slot;
      sel.addEventListener("change", function () { state.slot = sel.value; render(); });
      s.appendChild(field("수령 시간", sel));
      if (state.slot) s.appendChild(el("p", { text: "✅ 예약 완료(시안): " + state.picked + " · " + state.slot }));
      return s;
    }
  ];

  function refresh() { next.disabled = !canNext() || state.step === STEPS.length - 1; }
  function render() {
    stepsEl.textContent = "";
    STEPS.forEach(function (n, i) {
      stepsEl.appendChild(el("li", { "class": i === state.step ? "on" : (i < state.step ? "done" : ""), text: (i + 1) + ". " + n }));
    });
    screen.textContent = "";
    screen.appendChild(views[state.step]());
    prev.disabled = state.step === 0;
    refresh();
  }
  prev.addEventListener("click", function () { if (state.step > 0) { state.step--; render(); } });
  next.addEventListener("click", function () { if (canNext() && state.step < STEPS.length - 1) { state.step++; render(); } });
  render();
})();
