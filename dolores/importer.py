"""Multi-format personal data importer — scan folder, extract text, store in mempalace."""

import hashlib
import json
import os
from pathlib import Path

from .config import DEFAULT_CONFIG_DIR

IMPORT_HASH_PATH = os.path.join(DEFAULT_CONFIG_DIR, "imported_hashes.json")

SUPPORTED_EXTENSIONS = {
    ".txt", ".md",
    ".pdf",
    ".docx",
    ".csv", ".xlsx",
    ".json", ".jsonl",
    ".png", ".jpg", ".jpeg",
}


def _file_hash(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_hashes() -> dict:
    if os.path.exists(IMPORT_HASH_PATH):
        with open(IMPORT_HASH_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_hashes(hashes: dict):
    Path(IMPORT_HASH_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(IMPORT_HASH_PATH, "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=2)


def import_file(path: str) -> str:
    """Read a single file and return extracted plain text."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="ignore")

    if ext == ".pdf":
        return _read_pdf(path)

    if ext == ".docx":
        return _read_docx(path)

    if ext == ".csv":
        return _read_csv(path)

    if ext == ".xlsx":
        return _read_xlsx(path)

    if ext in (".json", ".jsonl"):
        return _read_json(path)

    if ext in (".png", ".jpg", ".jpeg"):
        return _read_image_ocr(path)

    return ""


def _read_pdf(path: str) -> str:
    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except ImportError:
        return f"[PDF import requires pymupdf: {path}]"
    except Exception as e:
        return f"[PDF read error: {e}]"


def _read_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        return f"[DOCX import requires python-docx: {path}]"
    except Exception as e:
        return f"[DOCX read error: {e}]"


def _read_csv(path: str) -> str:
    import csv
    rows = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(", ".join(row))
        return "\n".join(rows)
    except Exception as e:
        return f"[CSV read error: {e}]"


def _read_xlsx(path: str) -> str:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True)
        lines = []
        for ws in wb.worksheets:
            lines.append(f"[Sheet: {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                lines.append(", ".join(cells))
        wb.close()
        return "\n".join(lines)
    except ImportError:
        return f"[XLSX import requires openpyxl: {path}]"
    except Exception as e:
        return f"[XLSX read error: {e}]"


def _read_json(path: str) -> str:
    """Handle ChatGPT/Claude/LINE JSON exports and generic JSONL."""
    lines = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        if path.endswith(".jsonl"):
            for line in text.strip().split("\n"):
                try:
                    obj = json.loads(line)
                    msg = obj.get("content") or obj.get("text") or obj.get("message") or str(obj)
                    lines.append(msg)
                except json.JSONDecodeError:
                    lines.append(line)
        else:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        msg = item.get("content") or item.get("text") or item.get("message") or str(item)
                        lines.append(msg)
                    else:
                        lines.append(str(item))
            elif isinstance(data, dict):
                lines.append(json.dumps(data, ensure_ascii=False, indent=2))
        return "\n".join(lines)
    except Exception as e:
        return f"[JSON read error: {e}]"


def _read_image_ocr(path: str) -> str:
    """Extract embedded/visible text from image via PyMuPDF (not full OCR for photos)."""
    try:
        import fitz
        doc = fitz.open(path)
        page = doc[0]
        text = page.get_text()
        doc.close()
        return text.strip() if text.strip() else f"[No text found in image: {Path(path).name}]"
    except Exception:
        return f"[Image OCR failed: {Path(path).name}]"


def scan_and_import(folder_path: str, callback=None) -> list[dict]:
    """
    Recursively scan a folder, import all supported files into mempalace.

    Args:
        folder_path: Directory to scan.
        callback: Optional callable(filename, status) for progress reporting.

    Returns:
        List of dicts with import results.
    """
    try:
        from mempalace.layers import MemoryStack
        import chromadb
        HAS_MEMPALACE = True
    except ImportError:
        HAS_MEMPALACE = False

    folder = Path(folder_path)
    if not folder.is_dir():
        return []

    hashes = _load_hashes()
    results = []

    files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]

    for filepath in sorted(files):
        fname = str(filepath)
        fhash = _file_hash(fname)

        if hashes.get(fname) == fhash:
            results.append({"file": filepath.name, "status": "skipped", "reason": "already imported"})
            if callback:
                callback(filepath.name, "skipped")
            continue

        text = import_file(fname)
        if not text or text.startswith("["):
            results.append({"file": filepath.name, "status": "error", "reason": text})
            if callback:
                callback(filepath.name, "error")
            continue

        if HAS_MEMPALACE:
            try:
                stack = MemoryStack()
                client = chromadb.PersistentClient(path=stack.palace_path)
                col = client.get_or_create_collection("mempalace_drawers")

                chunks = _chunk_text(text, max_chars=800)
                for i, chunk in enumerate(chunks):
                    doc_id = f"dolores_import_{fhash}_{i}"
                    col.upsert(
                        ids=[doc_id],
                        documents=[chunk],
                        metadatas=[{
                            "wing": "dolores_personal",
                            "room": "imported",
                            "source_file": fname,
                            "chunk_index": str(i),
                            "added_by": "dolores_importer",
                        }],
                    )
                results.append({"file": filepath.name, "status": "imported", "chunks": len(chunks)})
                if callback:
                    callback(filepath.name, f"imported ({len(chunks)} chunks)")
            except Exception as e:
                results.append({"file": filepath.name, "status": "error", "reason": str(e)})
                if callback:
                    callback(filepath.name, "error")
                continue
        else:
            results.append({"file": filepath.name, "status": "no_mempalace", "text_length": len(text)})
            if callback:
                callback(filepath.name, "no mempalace")

        hashes[fname] = fhash

    _save_hashes(hashes)
    return results


def _chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
