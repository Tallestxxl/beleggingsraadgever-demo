"""Text extraction for knowledge document imports."""

from __future__ import annotations

import re
import os
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SUPPORTED_FILE_SUFFIXES = SUPPORTED_TEXT_SUFFIXES | {".pdf"} | SUPPORTED_IMAGE_SUFFIXES
OCR_LANGUAGE = "nld+eng"


def extract_text_from_file(path: Path) -> str:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ValueError(f"Bestand niet gevonden: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Pad is geen bestand: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return _read_text_file(file_path)
    if suffix == ".pdf":
        try:
            return extract_text_from_pdf(file_path.read_bytes())
        except ValueError:
            return _ocr_pdf(file_path)
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return _ocr_image(file_path)
    raise ValueError("Ondersteunde bestandsformaten zijn .txt, .md, digitale .pdf en OCR-afbeeldingen.")


def ocr_engine_status() -> str:
    ocrmypdf = _tool_path("ocrmypdf", "BELEGGINGSRAADGEVER_OCRMYPDF")
    tesseract = _tool_path("tesseract", "BELEGGINGSRAADGEVER_TESSERACT")
    if ocrmypdf:
        return "OCR beschikbaar voor gescande PDF's via OCRmyPDF."
    if tesseract:
        return "OCR beschikbaar voor losse afbeeldingen via Tesseract; gescande PDF's vragen OCRmyPDF."
    return "OCR-engine ontbreekt: installeer OCRmyPDF voor gescande PDF's of Tesseract voor losse afbeeldingen."


def extract_text_from_pdf(data: bytes) -> str:
    parts = []
    for stream in _pdf_streams(data):
        text = _text_from_pdf_content_stream(stream)
        if text:
            parts.append(text)
    extracted = "\n".join(parts)
    extracted = re.sub(r"[ \t]+", " ", extracted)
    extracted = re.sub(r"\n{3,}", "\n\n", extracted).strip()
    if not extracted:
        raise ValueError("Geen tekst gevonden in PDF. Mogelijk is dit een scan; daarvoor is OCR nodig.")
    return extracted


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            return text.strip()
        except UnicodeDecodeError:
            continue
    raise ValueError("Tekstbestand kon niet worden gelezen.")


def _ocr_pdf(path: Path) -> str:
    ocrmypdf = _tool_path("ocrmypdf", "BELEGGINGSRAADGEVER_OCRMYPDF")
    if not ocrmypdf:
        raise ValueError(
            "Geen tekst gevonden in PDF. Voor gescande PDF's is OCRmyPDF nodig; "
            "digitale PDF's blijven zonder OCR werken."
        )
    with tempfile.TemporaryDirectory() as tmp:
        sidecar = Path(tmp) / "ocr.txt"
        output_pdf = Path(tmp) / "ocr.pdf"
        command = [
            ocrmypdf,
            "--skip-text",
            "-l",
            OCR_LANGUAGE,
            "--sidecar",
            str(sidecar),
            str(path),
            str(output_pdf),
        ]
        result = subprocess.run(command, text=True, capture_output=True, timeout=240)
        if result.returncode != 0:
            raise ValueError(_ocr_error("OCRmyPDF", result.stderr))
        text = sidecar.read_text(encoding="utf-8", errors="ignore").strip() if sidecar.exists() else ""
        if not text:
            raise ValueError("OCRmyPDF heeft geen tekst uit de PDF gehaald.")
        return text


def _ocr_image(path: Path) -> str:
    tesseract = _tool_path("tesseract", "BELEGGINGSRAADGEVER_TESSERACT")
    if not tesseract:
        raise ValueError("OCR voor afbeeldingen vereist Tesseract.")
    attempts = [
        [tesseract, str(path), "stdout", "-l", OCR_LANGUAGE],
        [tesseract, str(path), "stdout"],
    ]
    last_error = ""
    for command in attempts:
        result = subprocess.run(command, text=True, capture_output=True, timeout=120)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        last_error = result.stderr
    raise ValueError(_ocr_error("Tesseract", last_error))


def _tool_path(name: str, env_var: str) -> str | None:
    override = os.environ.get(env_var, "").strip()
    if override:
        return override
    return shutil.which(name)


def _ocr_error(tool_name: str, stderr: str) -> str:
    detail = stderr.strip().splitlines()[-1] if stderr.strip() else "geen tekst gevonden"
    return f"{tool_name} kon geen OCR-tekst maken: {detail}"


def _pdf_streams(data: bytes) -> list[bytes]:
    streams = []
    pattern = re.compile(rb"<<(?P<dict>.*?)>>\s*stream\r?\n(?P<body>.*?)\r?\nendstream", re.DOTALL)
    for match in pattern.finditer(data):
        dictionary = match.group("dict")
        body = match.group("body")
        if b"/FlateDecode" in dictionary:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        streams.append(body)
    return streams


def _text_from_pdf_content_stream(stream: bytes) -> str:
    text = stream.decode("latin-1", errors="ignore")
    output: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "(":
            value, index = _read_pdf_literal_string(text, index)
            next_token = _next_operator_token(text, index)
            if next_token in {"Tj", "'", '"'}:
                output.append(value)
            elif next_token is None and value:
                output.append(value)
            continue
        if char == "[":
            array_end = _find_pdf_array_end(text, index)
            if array_end > index:
                candidate = _extract_array_text(text[index + 1 : array_end])
                next_token = _next_operator_token(text, array_end + 1)
                if candidate and next_token == "TJ":
                    output.append(candidate)
                index = array_end + 1
                continue
        if text.startswith("T*", index) or text.startswith("Td", index) or text.startswith("TD", index):
            output.append("\n")
        index += 1
    return _clean_extracted_text(" ".join(output))


def _read_pdf_literal_string(text: str, start: int) -> tuple[str, int]:
    result = []
    index = start + 1
    depth = 1
    while index < len(text) and depth:
        char = text[index]
        if char == "\\":
            value, index = _read_pdf_escape(text, index)
            result.append(value)
            continue
        if char == "(":
            depth += 1
            result.append(char)
        elif char == ")":
            depth -= 1
            if depth:
                result.append(char)
        else:
            result.append(char)
        index += 1
    return "".join(result), index


def _read_pdf_escape(text: str, index: int) -> tuple[str, int]:
    if index + 1 >= len(text):
        return "", index + 1
    escaped = text[index + 1]
    escapes = {"n": "\n", "r": "\n", "t": "\t", "b": "", "f": "", "(": "(", ")": ")", "\\": "\\"}
    if escaped in escapes:
        return escapes[escaped], index + 2
    if escaped in "\r\n":
        next_index = index + 2
        if escaped == "\r" and next_index < len(text) and text[next_index] == "\n":
            next_index += 1
        return "", next_index
    if escaped.isdigit():
        digits = escaped
        next_index = index + 2
        while next_index < len(text) and len(digits) < 3 and text[next_index].isdigit():
            digits += text[next_index]
            next_index += 1
        try:
            return chr(int(digits, 8)), next_index
        except ValueError:
            return "", next_index
    return escaped, index + 2


def _next_operator_token(text: str, index: int) -> str | None:
    match = re.match(r"\s*(Tj|TJ|'|\")", text[index:])
    return match.group(1) if match else None


def _find_pdf_array_end(text: str, start: int) -> int:
    index = start + 1
    while index < len(text):
        if text[index] == "(":
            _, index = _read_pdf_literal_string(text, index)
            continue
        if text[index] == "]":
            return index
        index += 1
    return -1


def _extract_array_text(value: str) -> str:
    pieces = []
    index = 0
    while index < len(value):
        if value[index] == "(":
            piece, index = _read_pdf_literal_string(value, index)
            pieces.append(piece)
            continue
        index += 1
    return "".join(pieces)


def _clean_extracted_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n +", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
