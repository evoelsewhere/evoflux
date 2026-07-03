"""MemoryContextHook — inject small query-relevant Memory v2 excerpts."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.services.memory import MemorySearchResult
from app.services.memory import memory_root
from app.services.memory import search_memory_facts

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
    )

MAX_MEMORY_QUERY_CHARS = 500
MAX_MEMORY_CONTEXT_CHARS = 2_000
MEMORY_CONTEXT_TOP_K = 3
_AUTO_MEMORY_STOPWORDS = {
    "a",
    "an",
    "and",
    "do",
    "does",
    "how",
    "is",
    "me",
    "my",
    "of",
    "s",
    "should",
    "the",
    "to",
    "what",
    "you",
}
_AUTO_MEMORY_QUERY_ALIASES = {
    "do": "support",
    "does": "support",
    "want": "support",
    "wants": "support",
}
_AUTO_MEMORY_TEXT_ALIASES = {
    "help": "support",
    "helps": "support",
}
_AUTO_MEMORY_ALIASES = {
    "answer": "answer",
    "answers": "answer",
    "answered": "answer",
    "answering": "answer",
    "respond": "answer",
    "response": "answer",
    "responses": "answer",
    "personalization": "personalization",
    "personalisation": "personalization",
    "personalize": "personalization",
    "personalized": "personalization",
    "prefer": "preferences",
    "preferred": "preferences",
    "prefers": "preferences",
    "preference": "preferences",
    "preferences": "preferences",
    "want": "want",
    "wants": "want",
}
_AUTO_MEMORY_TOPIC_ALIASES = {
    "do": "support",
    "does": "support",
    "help": "support",
    "helps": "support",
    "want": "support",
    "wants": "support",
    "answer": "response-style",
    "answers": "response-style",
    "answering": "response-style",
    "direct": "response-style",
    "fact": "response-style",
    "facts": "response-style",
    "respond": "response-style",
    "response": "response-style",
    "responses": "response-style",
    "personalization": "personalization",
    "personalisation": "personalization",
    "personalize": "personalization",
    "personalized": "personalization",
    "deploy": "deployment",
    "deployment": "deployment",
    "deployments": "deployments",
    "prefer": "preferences",
    "preferred": "preferences",
    "preference": "preferences",
    "preferences": "preferences",
    "prefers": "preferences",
}
_AUTO_MEMORY_GENERIC_TOPICS = {"memory", "EvoFlux", "preferences"}
_AUTO_MEMORY_DOMAIN_TERMS = {"kubernetes", "scheduler", "plugin"}
_AUTO_MEMORY_BROAD_PRODUCT_TERMS = {"memory", "EvoFlux", "v2"}
_AUTO_MEMORY_UNANSWERED_QUERY_TERMS = {
    "cloud",
    "database",
    "deployment",
    "deployments",
    "mandatory",
    "ontology",
    "plugin",
    "region",
    "root",
    "scheduler",
    "taxonomy",
    "user.md",
    "vector",
}
_AUTO_MEMORY_HIGH_INTENT_TOKENS = {
    "answer",
    "direct",
    "personalization",
    "preferences",
    "response",
    "style",
    "support",
}


class MemoryContextHook(BaseAgentHook):
    """Inject relevant Memory v2 snippets for the current user turn.

    This is intentionally conservative: it searches only from the latest user
    message, injects a small cited block, and never blocks the model call if
    memory search fails.
    """

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        query = self._latest_user_text(request)
        if not query:
            return await handler(request)

        try:
            results = search_memory_facts(
                query,
                limit=MEMORY_CONTEXT_TOP_K,
            )
        except Exception as exc:
            logger.warning("memory_context_search_failed error={}", exc)
            return await handler(request)

        results = self._filter_relevant_results(query, results)
        if not results:
            return await handler(request)

        lines = [
            "## Relevant memory",
            "",
            "Cited active memory facts that may help personalize this answer. Use only if relevant; do not overfit.",
        ]
        for result in results:
            location = f" path={result.path}" if result.path else ""
            lines.append(
                f"- source={result.source_ref}{location} score={result.score:.3f}: "
                f"{result.excerpt}"
            )
        block = "\n".join(lines)
        if len(block) > MAX_MEMORY_CONTEXT_CHARS:
            block = block[:MAX_MEMORY_CONTEXT_CHARS].rstrip() + "\n[truncated]"

        new_prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=new_prompt))

    def _filter_relevant_results(
        self, query: str, results: list[MemorySearchResult]
    ) -> list[MemorySearchResult]:
        query_tokens = self._meaningful_tokens(query, query=True)
        if not query_tokens:
            return []
        filtered: list[MemorySearchResult] = []
        for result in results:
            result_tokens = self._meaningful_tokens(result.excerpt)
            overlap = query_tokens & result_tokens
            query_only = query_tokens - result_tokens
            if not overlap:
                continue
            if len(overlap) == 1 and len(query_only) >= 2:
                continue
            if not self._has_answerable_overlap(query_tokens, overlap, query_only):
                continue
            if not self._metadata_allows_injection(query, result):
                continue
            filtered.append(result)
        return filtered

    def _has_answerable_overlap(
        self,
        query_tokens: set[str],
        overlap: set[str],
        query_only: set[str],
    ) -> bool:
        if not query_only:
            return True
        non_generic_overlap = overlap - _AUTO_MEMORY_BROAD_PRODUCT_TERMS
        if non_generic_overlap:
            unanswered = query_only & _AUTO_MEMORY_UNANSWERED_QUERY_TERMS
            return not unanswered
        if overlap & _AUTO_MEMORY_HIGH_INTENT_TOKENS:
            return True
        return False

    def _metadata_allows_injection(
        self, query: str, result: MemorySearchResult
    ) -> bool:
        if not result.path:
            return False
        if result.diagnostics.get("fact_section") not in {None, "active"}:
            return False
        metadata = self._memory_metadata(result.path)
        topics = metadata.get("topics")
        if not isinstance(topics, set) or not topics:
            return True

        query_topics = self._query_topics(query)
        topic_overlap = topics & query_topics
        non_generic_topic_overlap = topic_overlap - _AUTO_MEMORY_GENERIC_TOPICS
        if non_generic_topic_overlap:
            return True
        if "response-style" in topic_overlap:
            return True
        if query_topics & _AUTO_MEMORY_DOMAIN_TERMS:
            return bool(topic_overlap & (query_topics - _AUTO_MEMORY_GENERIC_TOPICS))
        if query_topics <= _AUTO_MEMORY_BROAD_PRODUCT_TERMS:
            return bool(topic_overlap)
        if query_topics & _AUTO_MEMORY_HIGH_INTENT_TOKENS and topic_overlap:
            return True
        non_generic_query_topics = query_topics - _AUTO_MEMORY_GENERIC_TOPICS
        return bool(topic_overlap & non_generic_query_topics)

    def _memory_metadata(self, rel_path: str) -> dict[str, object]:
        try:
            raw = (memory_root() / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {}
        if not raw.lstrip().startswith("---"):
            return {}
        match = raw.split("---", 2)
        if len(match) < 3:
            return {}
        try:
            import yaml

            data = yaml.safe_load(match[1]) or {}
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        raw_topics = data.get("topics")
        topics: set[str] = set()
        if isinstance(raw_topics, list):
            topics = {
                str(topic).strip().lower() for topic in raw_topics if str(topic).strip()
            }
        return {
            "memory_kind": str(data.get("memory_kind", "")).strip().lower(),
            "scope": str(data.get("scope", "")).strip().lower(),
            "topics": topics,
        }

    def _query_topics(self, text: str) -> set[str]:
        topics: set[str] = set()
        for raw in re.findall(r"[a-z0-9]+", text.lower()):
            token = _AUTO_MEMORY_TOPIC_ALIASES.get(raw, raw)
            if token in _AUTO_MEMORY_STOPWORDS:
                continue
            topics.add(token)
        return topics

    def _meaningful_tokens(self, text: str, *, query: bool = False) -> set[str]:
        text = re.sub(r"\[[^\]]+:[^\]]+\]", " ", text)
        tokens: set[str] = set()
        for raw in re.findall(r"[a-z0-9]+", text.lower()):
            alias = _AUTO_MEMORY_QUERY_ALIASES if query else _AUTO_MEMORY_TEXT_ALIASES
            token = alias.get(raw, _AUTO_MEMORY_ALIASES.get(raw, raw))
            if token in _AUTO_MEMORY_STOPWORDS:
                continue
            tokens.add(token)
        return tokens

    def _latest_user_text(self, request: "ModelRequest") -> str:
        for message in reversed(request.messages):
            if isinstance(message, HumanMessage):
                content = message.text_content() or ""
                return " ".join(content.split())[:MAX_MEMORY_QUERY_CHARS]
            if isinstance(message, AssistantMessage) and message.tool_calls:
                return ""
            if isinstance(message, ToolMessage):
                return ""
        return ""


default_memory_context_hook = MemoryContextHook()


__all__ = ["MemoryContextHook", "default_memory_context_hook"]
