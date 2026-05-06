"""
features/document_extraction/pdf_reader.py — Lecture multi-stratégie de PDF.

Stratégies (dans l'ordre) :
  1. pdfplumber  → texte + tables (priorité, qualité)
  2. PyMuPDF     → fallback rapide si pdfplumber échoue
  3. Tesseract   → OCR si le PDF est scanné (peu/pas de texte extractible)

Retourne un dict structuré exploitable par question_builder.py.
"""

import io
import logging
from typing import Dict, List, Optional

from config.settings import PDF_CONFIG

logger = logging.getLogger(__name__)


# Seuil sous lequel on considère qu'un PDF est probablement scanné
# (= très peu de texte natif extractible)
_OCR_TRIGGER_CHARS_PER_PAGE = 50


class PDFReader:
    """
    Lecteur PDF combinant 3 stratégies pour maximiser l'extraction.
    """

    def __init__(
        self,
        ocr_enabled: bool = None,
        ocr_language: str = None,
        max_pages: int = None,
    ):
        self.ocr_enabled  = ocr_enabled  if ocr_enabled is not None  else PDF_CONFIG["ocr_enabled"]
        self.ocr_language = ocr_language or PDF_CONFIG["ocr_language"]
        self.max_pages    = max_pages    or PDF_CONFIG["max_pages"]

    # ──────────────────────────────────────────────────────────────────────────
    # API publique
    # ──────────────────────────────────────────────────────────────────────────

    def read(self, pdf_bytes: bytes) -> Dict:
        """
        Extrait texte + tables d'un PDF.
        
        Returns:
            {
                "text":       str,           # texte concaténé de toutes les pages
                "tables":     List[List[List[str]]],  # tables par page
                "page_count": int,
                "used_ocr":   bool,
                "has_tables": bool,
            }
        """
        # ── 1. Tentative pdfplumber (texte + tables) ────────────────────────
        result = self._read_with_pdfplumber(pdf_bytes)

        # ── 2. Si peu/pas de texte → bascule OCR ─────────────────────────────
        text_density = (
            len(result["text"]) / max(result["page_count"], 1)
            if result["page_count"] > 0
            else 0
        )

        if text_density < _OCR_TRIGGER_CHARS_PER_PAGE and self.ocr_enabled:
            logger.info(
                f"PDF semble scanné ({text_density:.0f} chars/page) → bascule OCR"
            )
            ocr_result = self._read_with_ocr(pdf_bytes)
            if ocr_result and ocr_result["text"]:
                # On garde les tables de pdfplumber si elles existent
                ocr_result["tables"] = result["tables"]
                ocr_result["has_tables"] = result["has_tables"]
                return ocr_result

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Stratégie 1 : pdfplumber (priorité)
    # ──────────────────────────────────────────────────────────────────────────

    def _read_with_pdfplumber(self, pdf_bytes: bytes) -> Dict:
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber non installé, fallback PyMuPDF")
            return self._read_with_pymupdf(pdf_bytes)

        text_parts: List[str] = []
        tables: List[List[List[str]]] = []
        page_count = 0

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages_to_read = pdf.pages[: self.max_pages]
                page_count = len(pages_to_read)

                for i, page in enumerate(pages_to_read, start=1):
                    # Extraction texte
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"--- Page {i} ---\n{page_text}")

                    # Extraction tables (peut être vide)
                    page_tables = page.extract_tables() or []
                    for tbl in page_tables:
                        if tbl and any(any(cell for cell in row) for row in tbl):
                            tables.append(tbl)

        except Exception as exc:
            logger.warning(f"pdfplumber a échoué : {exc}, fallback PyMuPDF")
            return self._read_with_pymupdf(pdf_bytes)

        return {
            "text":       "\n\n".join(text_parts),
            "tables":     tables,
            "page_count": page_count,
            "used_ocr":   False,
            "has_tables": len(tables) > 0,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Stratégie 2 : PyMuPDF (fallback rapide)
    # ──────────────────────────────────────────────────────────────────────────

    def _read_with_pymupdf(self, pdf_bytes: bytes) -> Dict:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.error("PyMuPDF non installé non plus")
            return {
                "text": "", "tables": [], "page_count": 0,
                "used_ocr": False, "has_tables": False,
            }

        text_parts: List[str] = []
        page_count = 0

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = min(len(doc), self.max_pages)

            for i in range(page_count):
                page = doc[i]
                page_text = page.get_text() or ""
                if page_text.strip():
                    text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

            doc.close()

        except Exception as exc:
            logger.error(f"PyMuPDF a échoué : {exc}")
            return {
                "text": "", "tables": [], "page_count": 0,
                "used_ocr": False, "has_tables": False,
            }

        return {
            "text":       "\n\n".join(text_parts),
            "tables":     [],
            "page_count": page_count,
            "used_ocr":   False,
            "has_tables": False,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Stratégie 3 : OCR Tesseract (PDF scannés)
    # ──────────────────────────────────────────────────────────────────────────

    def _read_with_ocr(self, pdf_bytes: bytes) -> Optional[Dict]:
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            logger.error(
                f"OCR indisponible : {exc}. "
                "Installez pytesseract + pdf2image + binaires (tesseract-ocr, poppler-utils)"
            )
            return None

        try:
            # Conversion PDF → liste d'images PIL (1 par page)
            images = convert_from_bytes(
                pdf_bytes,
                dpi=200,  # Compromis qualité/vitesse
                fmt="png",
                first_page=1,
                last_page=self.max_pages,
            )
        except Exception as exc:
            logger.error(f"pdf2image a échoué (poppler manquant ?) : {exc}")
            return None

        text_parts: List[str] = []
        for i, img in enumerate(images, start=1):
            try:
                page_text = pytesseract.image_to_string(img, lang=self.ocr_language)
                if page_text.strip():
                    text_parts.append(f"--- Page {i} (OCR) ---\n{page_text}")
            except Exception as exc:
                logger.warning(f"OCR page {i} échouée : {exc}")

        return {
            "text":       "\n\n".join(text_parts),
            "tables":     [],
            "page_count": len(images),
            "used_ocr":   True,
            "has_tables": False,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Health
    # ──────────────────────────────────────────────────────────────────────────

    def is_ocr_available(self) -> bool:
        """Tesseract est-il installé et fonctionnel ?"""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
