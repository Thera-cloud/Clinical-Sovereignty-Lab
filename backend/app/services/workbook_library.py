import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional

# PDF support - try multiple libraries
try:
    from pypdf import PdfReader
    PDF_SUPPORT = "pypdf"
except ImportError:
    try:
        from PyPDF2 import PdfReader
        PDF_SUPPORT = "PyPDF2"
    except ImportError:
        PdfReader = None
        PDF_SUPPORT = None

_WORD_RE = re.compile(r"[a-zA-Z]{3,}")


def _normalize_words(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _extract_pdf_text(pdf_path: Path, max_pages: int = 50) -> str:
    """Extract text from a PDF file."""
    if not PdfReader:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
        pages = reader.pages[:max_pages]
        text_parts = []
        for page in pages:
            try:
                text = page.extract_text() or ""
                if text.strip():
                    text_parts.append(text)
            except Exception:
                continue
        return "\n\n".join(text_parts)
    except Exception as e:
        print(f"[WorkbookLibrary] PDF extraction failed for {pdf_path.name}: {e}")
        return ""


@dataclass(frozen=True)
class WorkbookChunk:
    source: str
    text: str
    words: Tuple[str, ...]


class WorkbookLibrary:
    """
    Lightweight local retrieval over `Workbooks/*.txt`, `.md`, and `.pdf` files.

    Goals:
    - Keep prompt injection short and relevant
    - Avoid huge verbatim dumps (we cap output)
    - Work offline with minimal dependencies
    -     Support PDF files for coaching-method materials (not therapy)
    """

    def __init__(self, workbooks_dir: Path):
        self.workbooks_dir = Path(workbooks_dir)
        self._chunks: List[WorkbookChunk] = []
        self._last_index_mtime: Optional[float] = None
        if PDF_SUPPORT:
            print(f"[WorkbookLibrary] PDF support enabled via {PDF_SUPPORT}")
        else:
            print("[WorkbookLibrary] PDF support disabled - install pypdf or PyPDF2")

    def _iter_workbook_files(self) -> List[Path]:
        """Recursively find all workbook files including in subdirectories."""
        if not self.workbooks_dir.exists():
            return []
        files = []
        supported_extensions = [".txt", ".md"]
        if PDF_SUPPORT:
            supported_extensions.append(".pdf")
        
        # Recursively walk directory tree
        for p in self.workbooks_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in supported_extensions:
                files.append(p)
        return sorted(files, key=lambda x: x.name.lower())

    def index(self) -> None:
        files = self._iter_workbook_files()
        latest_mtime = max((f.stat().st_mtime for f in files), default=None)
        self._last_index_mtime = latest_mtime

        chunks: List[WorkbookChunk] = []
        pdf_count = 0
        text_count = 0
        
        for f in files:
            try:
                # Handle PDF files separately
                if f.suffix.lower() == ".pdf":
                    raw = _extract_pdf_text(f)
                    if raw:
                        pdf_count += 1
                else:
                    raw = f.read_text(encoding="utf-8", errors="ignore")
                    text_count += 1
            except Exception as e:
                print(f"[WorkbookLibrary] Error reading {f.name}: {e}")
                continue

            if not raw or not raw.strip():
                continue

            # Use relative path from workbooks_dir for better source labeling
            try:
                rel_path = f.relative_to(self.workbooks_dir)
                source_name = str(rel_path)
            except ValueError:
                source_name = f.name

            # Split into paragraphs, then sub-chunk very long paragraphs.
            paras = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
            for para in paras:
                # Skip tiny / low-signal bits
                if len(para) < 80:
                    continue

                if len(para) > 900:
                    # Break large paragraphs into ~450-char windows
                    step = 450
                    for i in range(0, len(para), step):
                        sub = para[i : i + step].strip()
                        if len(sub) < 80:
                            continue
                        words = tuple(_normalize_words(sub))
                        if len(words) < 12:
                            continue
                        chunks.append(WorkbookChunk(source=source_name, text=sub, words=words))
                else:
                    words = tuple(_normalize_words(para))
                    if len(words) < 12:
                        continue
                    chunks.append(WorkbookChunk(source=source_name, text=para, words=words))

        self._chunks = chunks
        print(f"[WorkbookLibrary] Indexed {len(chunks)} chunks from {text_count} text + {pdf_count} PDF files")

    def ensure_indexed(self) -> None:
        files = self._iter_workbook_files()
        latest_mtime = max((f.stat().st_mtime for f in files), default=None)

        # Index if never indexed or workbook files changed.
        if self._last_index_mtime is None or latest_mtime != self._last_index_mtime:
            self.index()

    def query(self, query_text: str, max_chars: int = 1200, max_chunks: int = 6) -> str:
        """
        Return short, relevant excerpts for prompt injection.
        """
        self.ensure_indexed()
        if not self._chunks:
            return ""

        q_words = set(_normalize_words(query_text))
        if not q_words:
            return ""

        scored: List[Tuple[float, WorkbookChunk]] = []
        for ch in self._chunks:
            wset = set(ch.words)
            overlap = len(q_words & wset)
            if overlap <= 1:
                continue

            # Favor tighter chunks: overlap normalized by chunk size.
            score = overlap / (len(wset) + 20)

            # Small boost if filename indicates modality mentioned in query.
            fname = ch.source.lower()
            if "eft" in fname and ("eft" in q_words or "attachment" in q_words):
                score += 0.02
            if "ifs" in fname and ("parts" in q_words or "ifs" in q_words):
                score += 0.02
            if "polyvagal" in fname and ("nervous" in q_words or "polyvagal" in q_words):
                score += 0.02
            if "reconsolidation" in fname and ("memory" in q_words or "reconsolidation" in q_words):
                score += 0.02
            if "gestalt" in fname and (
                "gestalt" in q_words or "chair" in q_words or "unfinished" in q_words
            ):
                score += 0.03

            scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [ch for _, ch in scored[: max_chunks * 2]]  # overfetch, then fit to chars

        out_lines: List[str] = []
        used = 0
        used_sources = set()

        for ch in top:
            snippet = ch.text.strip()
            if not snippet:
                continue

            # Prefix each chunk with a short source tag (once per source).
            if ch.source not in used_sources:
                header = f"[WORKBOOK: {ch.source}]"
                if used + len(header) + 1 > max_chars:
                    break
                out_lines.append(header)
                used += len(header) + 1
                used_sources.add(ch.source)

            # Hard cap individual chunk size.
            if len(snippet) > 420:
                snippet = snippet[:420].rstrip() + "…"

            line = f"- {snippet}"
            if used + len(line) + 1 > max_chars:
                break
            out_lines.append(line)
            used += len(line) + 1

            if len([l for l in out_lines if l.startswith("- ")]) >= max_chunks:
                break

        body = "\n".join(out_lines).strip()
        if not body:
            return ""
        return (
            "COACHING TOOLS (not therapy — client may consider these methods):\n"
            + body
        )

