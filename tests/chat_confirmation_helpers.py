"""기존 대화 시험에서 화면이 받은 확인 값을 제출하는 동작을 흉내 낸다.

토큰 누락·재사용 거절 시험은 이 도우미를 쓰지 않고 원래 API를 직접 호출한다.
"""
from agents.chat_intake import YES


def ui_step(agent, sid, question, **kwargs):
    if kwargs.get('action') is None and YES.match(question.strip()):
        kwargs['action'] = agent.confirmation(sid)
    return agent.step(sid, question, **kwargs)


def ui_ask(bot, question, **kwargs):
    if kwargs.get('intake_action') is None and YES.match(question.strip()):
        kwargs['intake_action'] = bot.intake.confirmation(kwargs.get('session_id'))
    return bot.ask(question, **kwargs)
