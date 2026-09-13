"""LLM construction helpers."""

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel


@lru_cache(maxsize=16)
def get_chat_model(model_name: str) -> BaseChatModel:
    return init_chat_model(model_name, temperature=0.0)
