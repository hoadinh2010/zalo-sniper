import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from zalosniper.core.config import RepoConfig
from zalosniper.models.message import Message

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def _messages_to_text(messages: List[Message]) -> str:
    return "\n".join(
        f"[{m.timestamp.strftime('%H:%M')}] {m.sender}: {m.content}"
        for m in messages
    )


class AIAnalyzer:
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        # Use AsyncAnthropic to avoid blocking the event loop
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def _call(self, system: str, user: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from Claude response (may have surrounding text)."""
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])

    async def classify_messages(self, messages: List[Message]) -> Dict[str, Any]:
        """Classify messages as bug_report or noise."""
        chat = _messages_to_text(messages)
        system = (
            "You are a bug triage assistant. Analyze the Zalo chat messages and determine "
            "if they contain a bug report from users. "
            "Respond ONLY with JSON: {\"type\": \"bug_report\"|\"noise\", \"summary\": str, \"affected_feature\": str}"
        )
        text = await self._call(system, f"Messages:\n{chat}")
        return self._parse_json(text)

    async def select_repo(
        self, messages: List[Message], repos: List[RepoConfig]
    ) -> Tuple[str, str, str]:
        """Select the most likely affected repo. Returns (owner, name, reason)."""
        chat = _messages_to_text(messages)
        repo_list = "\n".join(
            f"- {r.name}: {r.description}" for r in repos
        )
        system = (
            "You are a software engineer. Based on the bug report, select the most likely "
            "affected repository from the list. "
            'Respond ONLY with JSON: {"selected_repo": "<repo_name>", "reason": "matched"|"ambiguous"}'
        )
        user = f"Bug report:\n{chat}\n\nAvailable repos:\n{repo_list}"
        text = await self._call(system, user)
        result = self._parse_json(text)

        selected_name = result.get("selected_repo", repos[0].name)
        reason = result.get("reason", "ambiguous")
        repo = next((r for r in repos if r.name == selected_name), repos[0])
        if repo.name != selected_name:
            reason = "ambiguous"
        return repo.owner, repo.name, reason

    async def analyze_root_cause(
        self, messages: List[Message], code_context: str
    ) -> Dict[str, Any]:
        """Analyze root cause using messages + code context."""
        chat = _messages_to_text(messages)
        system = (
            "You are a senior software engineer doing code review. "
            "Given a bug report from users and the relevant source code, identify the root cause. "
            "Respond ONLY with JSON: {\"root_cause\": str, \"affected_files\": [str], \"proposed_fix_description\": str}"
        )
        user = f"Bug report:\n{chat}\n\nSource code:\n{code_context}"
        text = await self._call(system, user)
        return self._parse_json(text)

    async def generate_patch(
        self, root_cause: str, code_context: str
    ) -> str:
        """Generate a unified diff patch to fix the bug."""
        system = (
            "You are a senior software engineer. Generate a minimal unified diff patch to fix the bug. "
            "Respond ONLY with JSON: {\"patch\": \"<unified diff string>\"}"
        )
        user = f"Root cause: {root_cause}\n\nSource code:\n{code_context}"
        text = await self._call(system, user)
        result = self._parse_json(text)
        return result.get("patch", "")

    async def summarize_messages(self, messages: List[Message]) -> str:
        """Summarize group messages as bullet points."""
        chat = _messages_to_text(messages)
        system = "Summarize the following Zalo group messages as bullet points in Vietnamese."
        return await self._call(system, chat)

    async def answer_question(self, messages: List[Message], question: str) -> str:
        """Answer a free-form question about message history."""
        chat = _messages_to_text(messages)
        system = (
            "You are a helpful assistant. Answer the question based on the Zalo chat history. "
            "Respond in Vietnamese."
        )
        return await self._call(system, f"Chat history:\n{chat}\n\nQuestion: {question}")
