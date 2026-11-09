"""가상 시연 무작위 시험(tools/sim_fuzz.py)을 자동 시험에 넣음 (LF-29 · 11/9 변재원)

11/9 저녁 발견: 보관함 꽉 참(칸 대기·직원 보관 선반, 9e589a7) 뒤로 sim_fuzz 가 '위반 85건'을 냈는데 자동 시험에 없어 아무도 몰랐다.
원인은 검사 규칙이 선반(shelf)·칸 대기를 몰랐던 것(동작은 정상) — 규칙을 고치고, 앞으로 깨지면 바로 알도록 여기서 돌린다.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


class SimFuzzTest(unittest.TestCase):
    def test_random_stories_keep_rules(self):
        import sim_fuzz
        for seed in (0, 7):                                   # 200회면 보관함이 차서 칸 대기·선반 장면까지 지나감(약 1초)
            r = sim_fuzz.run(200, seed)
            self.assertEqual(r["problems"], 0, f"seed {seed} 위반 {r['problems']}건 — python tools/sim_fuzz.py --runs 200 --seed {seed} -v")
            self.assertGreater(r["stats"].get("칸 대기(결과 보류)", 0), 0)


if __name__ == "__main__":
    unittest.main()
