"""11/9 agent 1개 = Langfuse 프롬프트 1개 = 모델 설정 1개 (LF-5 변재원) — 진짜 Langfuse·Ollama 는 부르지 않는다"""
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_chat_color_multiturn import setUpModule, tearDownModule  # noqa: E402,F401
from test_deerflow_langfuse import bot  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_LANGFUSE = {"LF_LANGFUSE": "0"}
OPS_DATA = {"returns": [{"decision": "returned", "seconds": 10}, {"decision": "rejected", "reason": "확인 질문 미통과", "seconds": 40}],
            "live": {"stories": [], "events": []}, "chat": None}


class FakePrompt:
    is_fallback = False

    def __init__(self, text, config):
        self.text, self.config = text, config

    def compile(self, **kw):
        from agents.prompts import _compile
        return _compile(self.text, kw)


class FakeClient:
    """Langfuse 대역: 이름별 config 를 돌려줌"""

    def __init__(self, configs):
        self.configs, self.asked = configs, []

    def get_prompt(self, name, **kw):
        from agents.prompts import DEFAULTS
        self.asked.append(name)
        return FakePrompt(DEFAULTS[name], self.configs.get(name, {}))


class Reader:
    def collect(self):
        return json.loads(json.dumps(OPS_DATA))


def model(answers, log):
    """대역 모델: 시스템 프롬프트 첫머리로 어느 칸인지 구분해 정해진 JSON 을 돌려줌. 모르는 칸이면 OSError(모델 꺼짐)"""
    def request(payload):
        system = payload["messages"][0]["content"]
        log.append(payload)
        for word, answer in answers.items():
            if word in system[:80]:
                return {"message": {"content": json.dumps(answer)}}
        raise OSError("down")
    return request


class OneToOneTest(unittest.TestCase):
    def test_agent_and_prompt_names_match(self):
        from agents import prompts
        self.assertEqual(len(prompts.AGENT_PROMPTS), 13)
        self.assertEqual(set(prompts.AGENT_PROMPTS.values()), set(prompts.DEFAULTS))
        self.assertEqual(len(set(prompts.AGENT_PROMPTS.values())), len(prompts.AGENT_PROMPTS))   # 프롬프트 하나를 두 칸이 같이 쓰지 않음
        self.assertEqual(set(prompts.DEFAULT_CONFIG), set(prompts.DEFAULTS))

    def test_every_graph_node_has_one_prompt(self):
        from agents import prompts
        with open(os.path.join(ROOT, "agents", "chatbot.py"), encoding="utf-8") as f:
            chat_nodes = set(re.findall(r"add_node\('(\w+)'", f.read()))
        chat_nodes.discard("ops_analyst")           # 관제 분석 그래프를 감싸는 껍데기(프롬프트 없음)
        ops_nodes = {f"ops-{n}" for n in ("coordinator", "planner", "supervisor", "researcher", "analyst", "reporter")}
        self.assertEqual(chat_nodes | ops_nodes, set(prompts.AGENT_PROMPTS))

    def test_code_calls_prompts_only_by_agent_name(self):
        from agents import prompts
        names = set()
        for fn in os.listdir(os.path.join(ROOT, "agents")):
            if not fn.endswith(".py") or fn == "prompts.py":
                continue
            with open(os.path.join(ROOT, "agents", fn), encoding="utf-8") as f:
                src = f.read()
            self.assertNotIn("prompts.get(", src, fn)                       # 이름 표를 거치지 않는 직접 호출 금지
            for name in [n for n in prompts.DEFAULTS if n.startswith("chat-")] + ["chat-guidance-answer", "chat-intake-extract"]:
                self.assertNotRegex(src, f"['\"]{name}['\"]", fn)           # 프롬프트 이름 글자를 코드에 따로 쓰지 않음(옛 이름 포함)
            names |= set(re.findall(r"(?:for_agent|settings|choose|_cfg|_pick)\(['\"]([\w-]+)['\"]", src))
        self.assertTrue(names)
        self.assertLessEqual(names, set(prompts.AGENT_PROMPTS))


class SettingsTest(unittest.TestCase):
    def tearDown(self):
        from agents import observability
        observability.reset_for_tests()

    def test_defaults_without_langfuse(self):
        from agents import observability, prompts
        with mock.patch.dict(os.environ, NO_LANGFUSE):
            observability.reset_for_tests()
            s = prompts.settings("planner", model="m", temperature=0)
            self.assertEqual((s["model"], s["temperature"], s["use_llm"]), ("m", 0, True))
            for agent in ("supervisor", "item_search", "reporter", "ops-coordinator", "ops-supervisor", "ops-researcher", "ops-analyst"):
                self.assertFalse(prompts.settings(agent)["use_llm"], agent)       # 규칙 칸은 기본 끔
            text, obj = prompts.for_agent("researcher", clarify_rule="")
            self.assertIsNone(obj)
            self.assertEqual(text, prompts.DEFAULTS["chat-researcher"].replace("{{clarify_rule}}", ""))

    def test_priority_langfuse_then_env_then_code(self):
        from agents import observability, prompts
        env = {"LF_AGENT_PLANNER_MODEL": "env-model", "LF_AGENT_PLANNER_TEMPERATURE": "0.5"}
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, **env}):
            observability.reset_for_tests()
            s = prompts.settings("planner", model="m", temperature=0)
            self.assertEqual((s["model"], s["temperature"]), ("env-model", 0.5))
            fake = FakeClient({"chat-planner": {"model": "lf-model", "temperature": 9, "use_llm": "maybe"}})
            with mock.patch.object(observability, "client", lambda: fake):
                s = prompts.settings("planner", model="m", temperature=0)
        # Langfuse model 이 먼저, 범위 밖 temperature·참거짓 아닌 use_llm 은 건너뛰고 다음 순서(환경값·코드)
        self.assertEqual((s["model"], s["temperature"], s["use_llm"]), ("lf-model", 0.5, True))
        self.assertEqual(s["source"], {"model": "langfuse", "temperature": "env", "use_llm": "code"})

    def test_langfuse_config_model_reaches_agent_call(self):
        from agents import observability, prompts
        from agents.chat_agents import AgentBrain
        from agents.ops_analyst import OpsAnalyst
        log = []
        fake = FakeClient({"chat-planner": {"model": "lf-planner", "temperature": 0.3},
                           "ops-reporter": {"model": "lf-reporter"}})
        with mock.patch.object(observability, "client", lambda: fake):
            brain = AgentBrain("m", request=model({"planner": {"steps": ["guidance"]}}, log))
            self.assertEqual(brain.plan("물건 수령 절차 알려줘"), ["guidance"])
            self.assertEqual((log[-1]["model"], log[-1]["options"]["temperature"]), ("lf-planner", 0.3))
            calls = []

            def llm(payload):
                calls.append(payload)
                raise OSError("down")
            OpsAnalyst(reader=Reader(), llm=llm, model="m").run("오늘 반환 실패 원인")
            self.assertEqual([c["model"] for c in calls], ["m", "lf-reporter"])     # 계획자는 코드 모델, 보고자는 Langfuse config
            st = prompts.status()
        self.assertEqual(st["total"], 13)
        self.assertGreaterEqual(st["from_langfuse"], 2)
        self.assertNotIn("key", json.dumps(st).lower())

    def test_use_llm_off_in_langfuse_turns_model_agent_into_rule(self):
        from agents import observability
        from agents.chat_agents import AgentBrain
        log = []
        fake = FakeClient({"chat-planner": {"use_llm": False}})
        with mock.patch.object(observability, "client", lambda: fake):
            self.assertIsNone(AgentBrain("m", request=model({"planner": {"steps": ["guidance"]}}, log)).plan("수령 절차"))
        self.assertEqual(log, [])


class FetchCacheTest(unittest.TestCase):
    """리뷰 지적: Langfuse 가 죽었거나 새 이름이 아직 없으면(404) 한 질문에 칸마다 다시 요청해 최대 2초씩 늦어졌다"""

    def test_failed_fetch_is_remembered_within_ttl(self):
        from agents import observability, prompts

        class Down:
            def __init__(self):
                self.asked = []

            def get_prompt(self, name, **kw):
                self.asked.append(name)
                raise OSError("down")

        down = Down()
        prompts._CACHE.clear()
        with mock.patch.object(observability, "client", lambda: down):
            for _ in range(3):
                text, obj = prompts.for_agent("supervisor")
                prompts.settings("supervisor")
        self.assertEqual(down.asked, ["chat-supervisor"])      # 6번 불러도 요청은 1번
        self.assertIsNone(obj)
        self.assertEqual(text, prompts.DEFAULTS["chat-supervisor"])
        prompts._CACHE.clear()

    def test_new_client_is_not_served_from_old_cache(self):
        from agents import observability, prompts
        prompts._CACHE.clear()
        a, b = FakeClient({}), FakeClient({})
        with mock.patch.object(observability, "client", lambda: a):
            prompts.settings("planner")
        with mock.patch.object(observability, "client", lambda: b):
            prompts.settings("planner")
        self.assertEqual((a.asked, b.asked), (["chat-planner"], ["chat-planner"]))
        prompts._CACHE.clear()


class SameBehaviourTest(unittest.TestCase):
    """기본(규칙 칸 use_llm 끔)에서는 모델 보조 호출이 하나도 없고 결과가 규칙과 같다"""

    def setUp(self):
        from agents import observability
        self._env = mock.patch.dict(os.environ, NO_LANGFUSE)
        self._env.start()
        observability.reset_for_tests()

    def tearDown(self):
        from agents import observability
        self._env.stop()
        observability.reset_for_tests()

    def test_chatbot_rule_agents_not_called_by_default(self):
        from agents.chat_agents import AgentBrain
        log = []
        answers = {"coordinator": {"intent": "service"}, "planner": {"steps": ["item_search", "guidance"]},
                   "supervisor": {"choice": "reporter"}}
        r = bot(AgentBrain("m", request=model(answers, log))).ask("검정 지갑 찾고 본센터 가는 법도 알려줘")
        self.assertIn("researcher", r["agent_path"])
        self.assertFalse(any("supervisor" in p["messages"][0]["content"][:80] for p in log))
        self.assertNotIn("reporter_llm", r)

    def test_ops_rule_agents_not_called_by_default(self):
        from agents.ops_analyst import OpsAnalyst
        calls = []

        def llm(payload):
            calls.append(payload["messages"][0]["content"][:40])
            raise OSError("down")
        out = OpsAnalyst(reader=Reader(), llm=llm, model="m").run("오늘 반환 실패 원인")
        self.assertEqual(len(calls), 2)                                     # 계획자·보고자만(예전과 같음)
        self.assertEqual((out["used_llm"], out["llm_hooks"]), ([], []))
        self.assertFalse(OpsAnalyst(reader=Reader(), llm=llm, model="m").run("안녕")["accepted"])


class RuleVetoTest(unittest.TestCase):
    """use_llm 을 켠 규칙 칸: 허용 목록 밖·실패면 규칙 결과, 안이면 그 값"""

    def tearDown(self):
        from agents import observability
        observability.reset_for_tests()

    def _ask(self, choice, question="검정 지갑 찾고 본센터 가는 법도 알려줘"):
        from agents import observability
        from agents.chat_agents import AgentBrain
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, "LF_AGENT_SUPERVISOR_USE_LLM": "1",
                                          "LF_AGENT_ITEM_SEARCH_USE_LLM": "1", "LF_AGENT_REPORTER_USE_LLM": "1"}):
            observability.reset_for_tests()
            answers = {"coordinator": {"intent": "service"}, "planner": {"steps": ["item_search", "guidance"]},
                       "supervisor": {"choice": choice}}
            return bot(AgentBrain("m", request=model(answers, []))).ask(question)

    def test_supervisor_out_of_list_falls_back_to_rule(self):
        for bad in ("intake", "ops", "end", "아무거나"):
            r = self._ask(bad)
            self.assertIn("researcher", r["agent_path"], bad)
            self.assertNotIn("intake", r["agent_path"], bad)
            self.assertFalse(any(d["decide"].startswith("model_next") for d in r["decisions"]), bad)
        self.assertIn(r.get("report_order"), ("guidance_first", "search_first"))   # 11/9 reporter 는 순서만 모델이 고름(내용은 그대로)

    def test_supervisor_choice_inside_list_is_used_and_recorded(self):
        r = self._ask("reporter")
        self.assertIn("item_search", r["agent_path"])
        self.assertNotIn("researcher", r["agent_path"])                     # 모델이 정리를 먼저 고름(허용 목록 안)
        self.assertTrue(any(d["decide"] == "model_next:reporter" for d in r["decisions"]))

    def test_supervisor_never_opens_intake(self):
        from agents import observability
        from agents.chat_agents import AgentBrain
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, "LF_AGENT_SUPERVISOR_USE_LLM": "1"}):
            observability.reset_for_tests()
            log = []
            r = bot(AgentBrain("m", request=model({"supervisor": {"choice": "reporter"}}, log))).ask("분실 접수하기")
        self.assertEqual(r["agent_path"][:3], ["coordinator", "planner", "supervisor"])
        self.assertIn("intake", r["agent_path"])                             # 접수 길은 규칙 그대로
        self.assertFalse(any("supervisor" in p["messages"][0]["content"][:80] for p in log))

    def test_ops_analyst_and_coordinator_veto(self):
        from agents import observability
        from agents.ops_analyst import OpsAnalyst, analyze
        rule = analyze(json.loads(json.dumps(OPS_DATA)), "failures")["findings"]
        self.assertGreaterEqual(len(rule), 2)

        def run(answer, question="오늘 반환 실패 원인"):
            def llm(payload):
                if "analyst" in payload["messages"][0]["content"][:60] or "coordinator" in payload["messages"][0]["content"][:60]:
                    return {"message": {"content": json.dumps(answer)}}
                raise OSError("down")
            return OpsAnalyst(reader=Reader(), llm=llm, model="m").run(question)
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, "LF_AGENT_OPS_ANALYST_USE_LLM": "1", "LF_AGENT_OPS_COORDINATOR_USE_LLM": "1",
                                          "LF_AGENT_OPS_SUPERVISOR_USE_LLM": "1", "LF_AGENT_OPS_RESEARCHER_USE_LLM": "1"}):
            observability.reset_for_tests()
            out = run({"top": 99})                                           # 목록 밖 번호 → 규칙 순서
            self.assertEqual(out["facts"]["findings"], rule)
            self.assertEqual(out["used_llm"], [])
            self.assertEqual(out["llm_hooks"], ["ops-supervisor", "ops-researcher"])   # 훅만
            out = run({"top": 1})
            self.assertEqual(out["facts"]["findings"][0], rule[1])           # 숫자는 그대로, 순서만
            self.assertEqual(sorted(out["facts"]["findings"]), sorted(rule))
            self.assertIn("analyst", out["used_llm"])
            self.assertFalse(run({"choice": "maybe"}, "안녕하세요")["accepted"])   # 목록 밖 → 규칙(거절)
            self.assertTrue(run({"choice": "ops"}, "어제 무슨 일 있었어?")["accepted"])


if __name__ == "__main__":
    unittest.main()


class PlanStepsTest(unittest.TestCase):
    """11/9 planner 단계별 지시서 → supervisor 가 한 단계씩 넘기고(task), 끝나면 완료·건너뜀을 적는다"""

    def tearDown(self):
        from agents import observability
        observability.reset_for_tests()

    def test_steps_follow_plan_and_tasks_reach_workers(self):
        from agents import observability
        seen = {}

        class Obs:
            def __init__(self, name):
                self.name = name

            def update(self, **kw):
                seen.setdefault(self.name, []).append(kw.get("output"))

        class CM:
            def __init__(self, name, kw):
                self.name = name
                seen.setdefault(name + ":in", []).append(kw.get("input"))

            def __enter__(self):
                return Obs(self.name)

            def __exit__(self, *a):
                return False

        class FakeClient:
            def start_as_current_observation(self, name, as_type="span", **kw):
                return CM(name, kw)

            def update_current_span(self, **kw):
                pass
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, "LF_LANGFUSE_CALLBACK": "0"}), \
                mock.patch.object(observability, "client", lambda: FakeClient()):
            r = bot().ask("갈색 지갑 찾아줘 그리고 받을 때 뭐 필요해?")
        self.assertEqual([x.split("]")[0] for x in r["plan_steps"]], ["1. [완료", "2. [완료"])
        self.assertIn("품목 지갑 · 색 갈색", r["plan_steps"][0])
        self.assertIn("researcher", r["plan_steps"][1])
        runs = [o["run_step"] for o in seen["supervisor"] if o and o.get("run_step")]
        self.assertEqual([x["step"] for x in runs], ["1/2", "2/2", "report"])
        self.assertEqual(runs[0]["why"], "planner 계획 순서")
        self.assertIn("품목 지갑", seen["item_search:in"][0]["task"])          # 일꾼 입력에 지시가 보임

    def test_supervisor_added_step_and_skipped_on_stop(self):
        from agents.chat_intake import IntakeAgent
        b = bot()
        b.intake = IntakeAgent()
        b.ask("분실 접수하고 싶어요", session_id="s-steps-0001")
        r = b.ask("본센터 몇 시까지 해요?", session_id="s-steps-0001")
        self.assertEqual(len(r["plan_steps"]), 2)
        self.assertIn("researcher", r["plan_steps"][1])                       # supervisor 가 더한 안내 단계

    def test_item_search_model_fills_only_listed_values(self):
        from agents.chat_agents import AgentBrain
        answers = {"coordinator": {"intent": "service"}, "planner": {"steps": ["item_search"]},
                   "item_search": {"category": "보조배터리", "color": "흰색"}}
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, "LF_AGENT_ITEM_SEARCH_USE_LLM": "1"}):
            r = bot(AgentBrain("m", request=model(answers, []))).ask("밧데리 흰색 찾아줘")
        self.assertEqual(r["status"], "items_not_found" if not r.get("candidates") else r["status"])
        self.assertIn("보조배터리", r["answer"])                                   # 규칙이 못 읽은 '밧데리'를 모델이 품목으로
        with mock.patch.dict(os.environ, {**NO_LANGFUSE, "LF_AGENT_ITEM_SEARCH_USE_LLM": "1"}):
            r = bot(AgentBrain("m", request=model({**answers, "item_search": {"category": "보조배터리", "color": "빨강"}}, []))).ask("밧데리 찾아줘")
        self.assertNotIn("빨강", r["answer"])                                       # 말에 색이 없으면 모델 색은 버림
