#!/usr/bin/env python3
"""ORANGE — LN7 PEFT OpenAI-compat serve (WireGuard :11435).

Loads durable QLoRA adapter from /opt/ln7/adapters/<id> and exposes
POST /v1/chat/completions so GREEN LN7 harness can serve trained weights
instead of stock Ollama coder tags.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ADAPTER_DIR = Path(os.getenv("LN7_ADAPTER_DIR", "/opt/ln7/adapters/LN7-2026-07-28T054420Z"))
HF_BASE = os.getenv("LN7_QLORA_HF_BASE", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
MODEL_ID = os.getenv("LN7_PEFT_MODEL_ID", "ln7-peft")
HOST = os.getenv("LN7_PEFT_HOST", "10.13.13.5")
PORT = int(os.getenv("LN7_PEFT_PORT", "11435") or "11435")
AUTH = (os.getenv("LN7_PEFT_AUTH_TOKEN") or os.getenv("CLASSROOM_REMOTE_AUTH_TOKEN") or "").strip()
MAX_NEW = int(os.getenv("LN7_PEFT_MAX_NEW_TOKENS", "2048") or "2048")

_tokenizer = None
_model = None
_load_error: Optional[str] = None


def _check_auth(authorization: Optional[str]) -> None:
    if not AUTH:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer required")
    if authorization.split(" ", 1)[1].strip() != AUTH:
        raise HTTPException(403, "bad token")


def _load() -> None:
    global _tokenizer, _model, _load_error
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not ADAPTER_DIR.is_dir():
            raise FileNotFoundError(f"adapter missing: {ADAPTER_DIR}")
        tok = AutoTokenizer.from_pretrained(str(ADAPTER_DIR), trust_remote_code=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        base = AutoModelForCausalLM.from_pretrained(
            HF_BASE,
            torch_dtype=dtype,
            device_map="auto" if torch.cuda.is_available() else None,
            trust_remote_code=True,
        )
        if not torch.cuda.is_available():
            base = base.to("cpu")
        model = PeftModel.from_pretrained(base, str(ADAPTER_DIR))
        # Merge for lower latency on CPU/GPU serve
        try:
            model = model.merge_and_unload()
        except Exception:
            pass
        model.eval()
        _tokenizer = tok
        _model = model
        _load_error = None
    except Exception as exc:
        _load_error = str(exc)[:500]
        _tokenizer = None
        _model = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load()
    yield


app = FastAPI(title="LN7 PEFT Serve", lifespan=lifespan)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: List[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 1024
    stream: bool = False


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok" if _model is not None else "degraded",
        "model": MODEL_ID,
        "adapter_dir": str(ADAPTER_DIR),
        "hf_base": HF_BASE,
        "loaded": _model is not None,
        "error": _load_error,
    }


@app.post("/v1/chat/completions")
def chat_completions(
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    if body.stream:
        raise HTTPException(400, "stream not supported")
    if _model is None or _tokenizer is None:
        raise HTTPException(503, f"model_not_loaded:{_load_error}")

    import torch

    # Build chat prompt
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        text_in = _tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True,
        )
    except Exception:
        parts = []
        for m in msgs:
            parts.append(f"{m['role'].upper()}: {m['content']}")
        parts.append("ASSISTANT:")
        text_in = "\n".join(parts)

    inputs = _tokenizer(text_in, return_tensors="pt")
    device = next(_model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    max_new = max(16, min(int(body.max_tokens or 1024), MAX_NEW))
    t0 = time.time()
    with torch.no_grad():
        out = _model.generate(
            **inputs,
            max_new_tokens=max_new,
            do_sample=float(body.temperature or 0) > 0.05,
            temperature=max(float(body.temperature or 0.2), 0.05),
            pad_token_id=_tokenizer.pad_token_id,
            eos_token_id=_tokenizer.eos_token_id,
        )
    gen = out[0][inputs["input_ids"].shape[-1] :]
    text = _tokenizer.decode(gen, skip_special_tokens=True).strip()
    latency_ms = int((time.time() - t0) * 1000)
    n_in = int(inputs["input_ids"].shape[-1])
    n_out = int(gen.shape[-1])
    return {
        "id": f"ln7-peft-{int(time.time())}",
        "object": "chat.completion",
        "model": body.model or MODEL_ID,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": n_in,
            "completion_tokens": n_out,
            "total_tokens": n_in + n_out,
        },
        "ln7": {
            "adapter_dir": str(ADAPTER_DIR),
            "latency_ms": latency_ms,
            "provider": "ln7_peft",
        },
    }


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
