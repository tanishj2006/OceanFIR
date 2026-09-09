"""
evidence_pdf.py — Lightweight placeholder stub for Lane D evidence generation
Allows Lane F smoke testing to pass until Lane D integrates ReportLab.
"""
from pathlib import Path

def build_pdf(doc: dict, out_path: str):
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    
    # Valid minimal PDF header and structure to pass MIME-type/byte checks
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
    )
    
    with open(p, "wb") as f:
        f.write(pdf_bytes)