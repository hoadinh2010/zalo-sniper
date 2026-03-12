import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from zalosniper.core.config import AIConfig, RepoConfig
from zalosniper.models.message import Message

logger = logging.getLogger(__name__)


def _messages_to_text(messages: List[Message]) -> str:
    return "\n".join(
        f"[{m.timestamp.strftime('%H:%M')}] {m.sender}: {m.content}"
        for m in messages
    )


class AIAnalyzer:
    def __init__(self, config: AIConfig) -> None:
        self._config = config
        self._provider = config.provider
        self._model = config.model
        api_key = config.resolved_api_key()

        if self._provider == "gemini":
            from google import genai
            self._gemini_client = genai.Client(api_key=api_key)
        else:
            # zai or any openai_compatible provider
            from openai import AsyncOpenAI
            base_url = config.base_url
            if not base_url and self._provider == "zai":
                base_url = "https://api.z.ai/api/paas/v4/"
            self._openai_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _call(self, system: str, user: str) -> str:
        if self._provider == "gemini":
            from google.genai import types as genai_types
            response = await self._gemini_client.aio.models.generate_content(
                model=self._model,
                contents=f"{system}\n\n{user}",
                config=genai_types.GenerateContentConfig(max_output_tokens=4096),
            )
            return response.text
        else:
            response = await self._openai_client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=4096,
            )
            return response.choices[0].message.content

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from Claude response (may have surrounding text)."""
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found in Claude response: {text[:200]!r}")
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in Claude response: {exc}") from exc

    async def triage_messages(self, messages: List[Message]) -> Dict[str, Any]:
        """Single call: summarize + classify + extract issues with solutions.

        Returns: {
            "type": "bug_report" | "noise",
            "summary": str,           # overall Vietnamese summary
            "affected_feature": str,
            "issues": [               # list of distinct problems found
                {
                    "title": str,
                    "description": str,
                    "proposed_solution": str
                }
            ]
        }
        """
        chat = _messages_to_text(messages)
        system = (
            "You are a bug triage assistant for a Vietnamese software team. "
            "Analyze the Zalo group chat messages carefully and respond ONLY with valid JSON (no markdown, no extra text).\n\n"
            "JSON schema:\n"
            '{\n'
            '  "type": "bug_report" or "noise",\n'
            '  "summary": "<1-3 sentence Vietnamese summary of what was discussed>",\n'
            '  "affected_feature": "<feature or component name, empty string if noise>",\n'
            '  "issues": [\n'
            '    {\n'
            '      "title": "<short Vietnamese title of the issue>",\n'
            '      "description": "<detailed Vietnamese description>",\n'
            '      "proposed_solution": "<concrete suggestion to fix or investigate>"\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            'Rules:\n'
            '- If type is "noise", issues must be an empty array [].\n'
            '- Split distinct problems into separate issue objects.\n'
            '- proposed_solution must be actionable (e.g. "Kiểm tra null check ở hàm login()", not "cần xem lại code").\n'
            '- Respond in Vietnamese for all text fields.'
        )
        text = await self._call(system, f"Messages:\n{chat}")
        result = self._parse_json(text)
        if "issues" not in result:
            result["issues"] = []
        return result

    async def classify_messages(self, messages: List[Message]) -> Dict[str, Any]:
        """Classify messages as bug_report or noise. Prefer triage_messages() to save API calls."""
        result = await self.triage_messages(messages)
        return result

    async def select_repo(
        self, messages: List[Message], repos: List[RepoConfig]
    ) -> Tuple[str, str, str]:
        """Select the most likely affected repo. Returns (owner, name, reason)."""
        if not repos:
            raise ValueError("select_repo called with empty repos list")
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
