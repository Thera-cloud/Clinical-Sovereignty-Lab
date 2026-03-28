"""
Structured User Questions — Capability 1
Sovereign Sanctuary · Little Nate Infrastructure

When LN hits an ambiguity, instead of guessing or asking in free text,
it emits an ask_user tool call with structured options. The extension
renders buttons/radio/checkbox, the user's selection goes back as the
tool result.

Every other capability depends on this one — build it first.

File: backend/app/websocket/tools/ask_user.py
Dependencies: None (pure Python, no external packages)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional


class QuestionType(str, Enum):
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    CONFIRM = "confirm"
    TEXT_INPUT = "text_input"


@dataclass
class QuestionOption:
    label: str
    value: str
    description: str = ""
    is_default: bool = False
    is_destructive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"label": self.label, "value": self.value}
        if self.description:
            d["description"] = self.description
        if self.is_default:
            d["is_default"] = True
        if self.is_destructive:
            d["is_destructive"] = True
        return d


@dataclass
class StructuredQuestion:
    question_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    question: str = ""
    question_type: QuestionType = QuestionType.SINGLE_SELECT
    options: List[QuestionOption] = field(default_factory=list)
    context: str = ""
    timeout_seconds: int = 300
    allow_skip: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "question_type": self.question_type.value,
            "options": [o.to_dict() for o in self.options],
            "context": self.context,
            "timeout_seconds": self.timeout_seconds,
            "allow_skip": self.allow_skip,
        }


@dataclass
class QuestionResponse:
    question_id: str
    selected_values: List[str]
    skipped: bool = False
    timed_out: bool = False
    text_input: str = ""
    responded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_tool_result(self) -> str:
        if self.timed_out:
            return "[USER DID NOT RESPOND — timed out. Proceed with safest default or stop.]"
        if self.skipped:
            return "[USER SKIPPED — chose not to answer. Do not assume any option.]"
        if self.text_input:
            return f"[USER RESPONSE]: {self.text_input}"
        if len(self.selected_values) == 1:
            return f"[USER SELECTED]: {self.selected_values[0]}"
        return f"[USER SELECTED]: {', '.join(self.selected_values)}"


# ---------------------------------------------------------------------------
# Tool definition — available in ALL modes (asking is always safe)
# ---------------------------------------------------------------------------

ASK_USER_TOOL_DEF = {
    "name": "ask_user",
    "description": (
        "Ask the user a structured question with predefined options. "
        "Use when you need clarification, confirmation before a destructive "
        "operation, or when multiple valid approaches exist. "
        "The user sees clickable buttons — much faster than typing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask. Be specific and concise.",
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Button text"},
                        "value": {"type": "string", "description": "Value returned when selected"},
                        "description": {"type": "string", "description": "Optional subtext"},
                    },
                    "required": ["label", "value"],
                },
                "description": "2-6 options for the user to choose from",
            },
            "question_type": {
                "type": "string",
                "enum": ["single_select", "multi_select", "confirm"],
                "description": "single_select: pick one. multi_select: pick many. confirm: yes/no.",
                "default": "single_select",
            },
            "context": {
                "type": "string",
                "description": "Why you're asking — shown as subtitle under the question",
            },
        },
        "required": ["question", "options"],
    },
}


# ---------------------------------------------------------------------------
# Pending questions waiting for user response
# ---------------------------------------------------------------------------

_pending_questions: Dict[str, asyncio.Future] = {}


async def handle_ask_user(
    params: Dict[str, Any],
    send_to_extension: Callable[[Dict], Coroutine],
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Execute the ask_user tool call.

    1. Build StructuredQuestion from params
    2. Send to extension via WebSocket
    3. Wait for user response (or timeout)
    4. Return formatted result
    """
    q_type = params.get("question_type", "single_select")

    if q_type == "confirm":
        options = [
            QuestionOption(label="Yes", value="yes"),
            QuestionOption(label="No", value="no", is_default=True),
        ]
    else:
        options = [
            QuestionOption(
                label=o["label"],
                value=o["value"],
                description=o.get("description", ""),
            )
            for o in params.get("options", [])
        ]

    question = StructuredQuestion(
        question=params.get("question", ""),
        question_type=QuestionType(q_type),
        options=options,
        context=params.get("context", ""),
        timeout_seconds=timeout,
    )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending_questions[question.question_id] = future

    await send_to_extension({
        "type": "ask_user_prompt",
        **question.to_dict(),
    })

    print(f">>> [ASK_USER] Question sent: {question.question} "
          f"({len(options)} options, timeout={timeout}s)")

    try:
        response_data = await asyncio.wait_for(future, timeout=timeout)
        response = QuestionResponse(
            question_id=question.question_id,
            selected_values=response_data.get("selected_values", []),
            skipped=response_data.get("skipped", False),
            text_input=response_data.get("text_input", ""),
        )
    except asyncio.TimeoutError:
        response = QuestionResponse(
            question_id=question.question_id,
            selected_values=[],
            timed_out=True,
        )
        print(f">>> [ASK_USER] Question timed out: {question.question}")
    finally:
        _pending_questions.pop(question.question_id, None)

    return {
        "success": True,
        "result": response.to_tool_result(),
        "question_id": question.question_id,
        "selected": response.selected_values,
        "skipped": response.skipped,
        "timed_out": response.timed_out,
    }


def handle_user_response(question_id: str, response_data: Dict[str, Any]) -> bool:
    """
    Called by bridge_server.py when the extension sends back ask_user_response.

    Bridge handler:
        elif t == "ask_user_response":
            from app.websocket.tools.ask_user import handle_user_response
            handle_user_response(data["question_id"], data)
    """
    future = _pending_questions.get(question_id)
    if future and not future.done():
        future.set_result(response_data)
        return True
    return False


# ---------------------------------------------------------------------------
# Extension JS handler + CSS (embed in chatPanel or dashboard)
# ---------------------------------------------------------------------------

EXTENSION_HANDLER_JS = """
case "ask_user_prompt": {
    const { question_id, question, question_type, options, context, allow_skip } = msg;
    const promptDiv = document.createElement("div");
    promptDiv.className = "ask-user-prompt";
    promptDiv.dataset.questionId = question_id;

    const qText = document.createElement("p");
    qText.className = "ask-user-question";
    qText.textContent = question;
    promptDiv.appendChild(qText);

    if (context) {
        const ctx = document.createElement("p");
        ctx.className = "ask-user-context";
        ctx.textContent = context;
        promptDiv.appendChild(ctx);
    }

    const optContainer = document.createElement("div");
    optContainer.className = "ask-user-options";

    if (question_type === "confirm") {
        ["Yes", "No"].forEach(label => {
            const btn = document.createElement("button");
            btn.className = `ask-user-btn ${label === "No" ? "ask-user-btn-secondary" : "ask-user-btn-primary"}`;
            btn.textContent = label;
            btn.onclick = () => sendAskUserResponse(question_id, [label.toLowerCase()]);
            optContainer.appendChild(btn);
        });
    } else {
        options.forEach(opt => {
            const btn = document.createElement("button");
            btn.className = `ask-user-btn ${opt.is_destructive ? "ask-user-btn-danger" : "ask-user-btn-primary"}`;
            btn.innerHTML = opt.description
                ? `<strong>${opt.label}</strong><br><small>${opt.description}</small>`
                : opt.label;
            btn.onclick = () => {
                if (question_type === "single_select") {
                    sendAskUserResponse(question_id, [opt.value]);
                } else {
                    btn.classList.toggle("selected");
                }
            };
            optContainer.appendChild(btn);
        });
        if (question_type === "multi_select") {
            const submit = document.createElement("button");
            submit.className = "ask-user-btn ask-user-btn-submit";
            submit.textContent = "Submit Selection";
            submit.onclick = () => {
                const selected = [...optContainer.querySelectorAll(".selected")]
                    .map(b => options[Array.from(optContainer.children).indexOf(b)].value);
                sendAskUserResponse(question_id, selected);
            };
            optContainer.appendChild(submit);
        }
    }
    promptDiv.appendChild(optContainer);

    if (allow_skip) {
        const skip = document.createElement("button");
        skip.className = "ask-user-btn ask-user-btn-skip";
        skip.textContent = "Skip";
        skip.onclick = () => sendAskUserResponse(question_id, [], true);
        promptDiv.appendChild(skip);
    }
    chatContainer.appendChild(promptDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    break;
}

function sendAskUserResponse(questionId, selectedValues, skipped = false) {
    ws.send(JSON.stringify({
        type: "ask_user_response",
        question_id: questionId,
        selected_values: selectedValues,
        skipped: skipped,
    }));
    const prompt = document.querySelector(`[data-question-id="${questionId}"]`);
    if (prompt) {
        prompt.classList.add("ask-user-answered");
        prompt.querySelectorAll("button").forEach(b => b.disabled = true);
    }
}
"""

EXTENSION_CSS = """
.ask-user-prompt {
    background: #111;
    border: 1px solid #C9A962;
    border-radius: 10px;
    padding: 16px;
    margin: 12px 0;
}
.ask-user-question {
    font-size: 14px;
    font-weight: 600;
    color: #E5E5E5;
    margin: 0 0 4px;
}
.ask-user-context {
    font-size: 12px;
    color: #888;
    margin: 0 0 12px;
}
.ask-user-options {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.ask-user-btn {
    padding: 10px 16px;
    border-radius: 8px;
    border: 1px solid #333;
    background: #1A1A1A;
    color: #E5E5E5;
    font-size: 13px;
    cursor: pointer;
    text-align: left;
    transition: all 0.15s;
}
.ask-user-btn:hover { background: #222; border-color: #C9A962; }
.ask-user-btn-primary { border-color: #444; }
.ask-user-btn-secondary { border-color: #333; color: #999; }
.ask-user-btn-danger { border-color: #E24B4A33; color: #E24B4A; }
.ask-user-btn-danger:hover { background: #2A1515; border-color: #E24B4A; }
.ask-user-btn-submit {
    background: #C9A96222; border-color: #C9A962; color: #C9A962;
    margin-top: 4px; text-align: center;
}
.ask-user-btn-skip {
    background: transparent; border: none; color: #666;
    font-size: 11px; margin-top: 8px; text-align: center;
}
.ask-user-btn.selected { background: #C9A96222; border-color: #C9A962; }
.ask-user-answered { opacity: 0.5; pointer-events: none; }
"""
