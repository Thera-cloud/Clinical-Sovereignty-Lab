"""
Voice Pipeline Optimizer — Sentence-level TTS streaming and STT overlap.

Reduces end-to-end voice response latency by:
1. Splitting LLM output at sentence boundaries
2. Starting TTS on the first sentence while the LLM generates the rest
3. Streaming audio chunks back to the client as they become available

Without this: User speaks → STT → LLM (full response) → TTS (full response) → Audio
With this:    User speaks → STT → LLM sentence 1 → TTS sentence 1 → Audio
                                   └→ LLM sentence 2 → TTS sentence 2 → Audio (overlapped)

Expected improvement: 4-5s → 2-2.5s for first audio chunk.
"""

import asyncio
import logging
import re
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SENTENCE_BOUNDARIES = re.compile(r'(?<=[.!?])\s+')
MIN_SENTENCE_LENGTH = 20
MAX_BUFFER_CHARS = 500


class SentenceChunker:
    """Accumulates streaming LLM text and yields complete sentences."""

    def __init__(self):
        self._buffer = ""
        self._sentences_yielded = 0

    def feed(self, text_delta: str) -> List[str]:
        self._buffer += text_delta
        sentences = []

        while True:
            match = SENTENCE_BOUNDARIES.search(self._buffer)
            if not match:
                break

            end = match.end()
            sentence = self._buffer[:end].strip()

            if len(sentence) >= MIN_SENTENCE_LENGTH:
                sentences.append(sentence)
                self._sentences_yielded += 1

            self._buffer = self._buffer[end:]

        if len(self._buffer) > MAX_BUFFER_CHARS:
            sentences.append(self._buffer.strip())
            self._sentences_yielded += 1
            self._buffer = ""

        return sentences

    def flush(self) -> Optional[str]:
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining and len(remaining) >= 5:
            self._sentences_yielded += 1
            return remaining
        return None


class VoicePipelineOptimizer:
    """Orchestrates overlapped LLM generation and TTS synthesis."""

    def __init__(self, tts_fn: Optional[Callable] = None):
        self._tts_fn = tts_fn
        self._metrics: Dict[str, Any] = {
            "total_requests": 0,
            "avg_first_chunk_ms": 0.0,
            "avg_total_ms": 0.0,
        }

    async def stream_voice_response(
        self,
        llm_stream: AsyncGenerator[str, None],
        tts_fn: Optional[Callable] = None,
        voice_id: str = "father",
        language: str = "en",
    ) -> AsyncGenerator[Tuple[bytes, int], None]:
        """
        Consume an LLM text stream, split into sentences, and yield
        (audio_bytes, sentence_index) tuples as soon as each sentence's
        TTS is complete.

        Args:
            llm_stream: Async generator yielding text deltas from the LLM
            tts_fn: async callable(text, voice_id, language) -> bytes
            voice_id: Voice reference ID for TTS
            language: Language code
        """
        synthesize = tts_fn or self._tts_fn
        if not synthesize:
            logger.warning("VoicePipelineOptimizer: no TTS function, yielding text only")
            return

        start = time.monotonic()
        chunker = SentenceChunker()
        first_chunk_time = None
        sentence_idx = 0
        tts_tasks: List[asyncio.Task] = []

        async def _synth_sentence(text: str, idx: int) -> Tuple[bytes, int]:
            audio = await synthesize(text, voice_id=voice_id, language=language)
            return (audio, idx)

        async for delta in llm_stream:
            sentences = chunker.feed(delta)
            for sentence in sentences:
                task = asyncio.create_task(_synth_sentence(sentence, sentence_idx))
                tts_tasks.append(task)
                sentence_idx += 1

            for task in list(tts_tasks):
                if task.done():
                    tts_tasks.remove(task)
                    result = task.result()
                    if first_chunk_time is None:
                        first_chunk_time = time.monotonic() - start
                    yield result

        remaining = chunker.flush()
        if remaining:
            task = asyncio.create_task(_synth_sentence(remaining, sentence_idx))
            tts_tasks.append(task)

        for task in tts_tasks:
            result = await task
            if first_chunk_time is None:
                first_chunk_time = time.monotonic() - start
            yield result

        total_ms = (time.monotonic() - start) * 1000
        first_ms = (first_chunk_time or 0) * 1000
        self._metrics["total_requests"] += 1

        n = self._metrics["total_requests"]
        self._metrics["avg_first_chunk_ms"] = (
            self._metrics["avg_first_chunk_ms"] * (n - 1) + first_ms
        ) / n
        self._metrics["avg_total_ms"] = (
            self._metrics["avg_total_ms"] * (n - 1) + total_ms
        ) / n

        logger.info(
            "VoicePipeline: %d sentences, first_chunk=%.0fms, total=%.0fms",
            sentence_idx + (1 if remaining else 0),
            first_ms,
            total_ms,
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_requests": self._metrics["total_requests"],
            "avg_first_chunk_ms": round(self._metrics["avg_first_chunk_ms"], 1),
            "avg_total_ms": round(self._metrics["avg_total_ms"], 1),
        }
