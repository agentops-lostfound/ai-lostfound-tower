"""One engine selection policy for tower, description input and standalone preview."""


def build_chatbot(guidance, database=None, *, engine=None, model=None, rag_model=None):
    engine = (engine or 'legacy').strip()
    if engine not in ('legacy', 'model'):
        raise ValueError('LF_CHAT_ENGINE은 legacy 또는 model이어야 합니다')
    from agents.chat_search import SearchAgent
    search = SearchAgent(database)
    if engine == 'model':
        from agents.model_chatbot import DEFAULT_CHAT_MODEL, ModelChatbot
        selected = next((value.strip() for value in (model, rag_model)
                         if isinstance(value, str) and value.strip()), DEFAULT_CHAT_MODEL)
        return ModelChatbot(guidance, selected, search=search)
    from agents.chatbot import Chatbot
    from agents.chat_rag import GroundedRag
    return Chatbot(guidance, rag=GroundedRag(guidance, model=rag_model or None), search=search)
