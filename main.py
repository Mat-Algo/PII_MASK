import streamlit as st
import tempfile
import os
import logging
import fitz  # PyMuPDF
import re

# --- ContactPIIMasker class ---
class ContactPIIMasker:
    def __init__(self, confidence_threshold: float = 0.35):
        self.confidence_threshold = confidence_threshold
        self.logger = logging.getLogger(__name__)

    def fix_contact_formatting(self, text: str) -> str:
        text = re.sub(r'([\w._%+-]+)@([\w.-]+)[\s\n]*\.?[\s\n]*([A-Za-z]{2,})', r'\1@\2.\3', text)
        text = re.sub(r'(\(?\d{3}\)?)[.\s\n-]?(\d{3})[.\s\n-]?(\d{4})', r'\1-\2-\3', text)
        text = re.sub(r'(\+\d{1,3})[\s\n-]?(\d{3,4})[\s\n-]?(\d{3,4})[\s\n-]?(\d{3,4})', r'\1-\2-\3-\4', text)
        return text

    def mask_contact_info_in_pdf(self, pdf_path: str, output_path: str) -> tuple:
        doc = fitz.open(pdf_path)
        total_redactions = 0

        email_re = re.compile(r'\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b')
        phone_re = re.compile(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
        linkedin_re = re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+', re.IGNORECASE)

        for page_num, page in enumerate(doc, start=1):
            page_redactions = 0
            page_dict = page.get_text("dict")

            for img in page.get_images():
                for rect in page.get_image_rects(img[0]):
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page_redactions += 1

            for block in page_dict["blocks"]:
                lines = block.get("lines", [])
                skip_next = False
                for idx, line in enumerate(lines):
                    if skip_next:
                        skip_next = False
                        continue
                    spans_i = line.get("spans", [])
                    txt_i = "".join(s["text"] for s in spans_i)
                    spans_to_redact = []

                    if email_re.search(txt_i) or phone_re.search(txt_i):
                        spans_to_redact = spans_i
                    else:
                        if idx + 1 < len(lines):
                            spans_j = lines[idx + 1].get("spans", [])
                            txt_j = "".join(s["text"] for s in spans_j)
                            if linkedin_re.search(txt_i + txt_j):
                                spans_to_redact = spans_i + spans_j
                                skip_next = True

                    for span in spans_to_redact:
                        bbox = fitz.Rect(span["bbox"])
                        page.add_redact_annot(bbox, fill=(0, 0, 0))
                        page_redactions += 1

            if page_redactions:
                page.apply_redactions()
                total_redactions += page_redactions

        doc.save(output_path)
        doc.close()

        report = (
            f"📋 Masking Report\n"
            f"Total items redacted: {total_redactions}\n"
        )
        return total_redactions, report

# --- Streamlit App ---
def main():
    st.set_page_config(page_title="EXPERT HIRE", layout="centered")
    st.markdown("<h1 style='text-align: center;'>EXPERT HIRE</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Smart redaction of contact details from candidate resumes</p>", unsafe_allow_html=True)
    
    uploaded = st.file_uploader("📄 Upload a resume PDF", type=["pdf"])
    
    if uploaded:
        tmp_dir = tempfile.mkdtemp()
        input_path = os.path.join(tmp_dir, uploaded.name)
        with open(input_path, "wb") as f:
            f.write(uploaded.getbuffer())

        output_name = f"masked_{uploaded.name}"
        output_path = os.path.join(tmp_dir, output_name)

        masker = ContactPIIMasker()

        with st.spinner("🔍 Redacting contact details... please wait..."):
            redacted_count, report_text = masker.mask_contact_info_in_pdf(
                input_path, output_path
            )

        st.success(f"✅ Redaction complete — {redacted_count} items masked.")
        st.download_button(
            label="⬇️ Download Masked PDF",
            data=open(output_path, "rb"),
            file_name=output_name,
            mime="application/pdf"
        )

        st.markdown("---")
        st.markdown("### 📑 Redaction Summary")
        st.code(report_text)
        st.download_button(
            label="📥 Download Report",
            data=report_text,
            file_name=output_name.replace('.pdf', '_report.txt'),
            mime="text/plain"
        )
    else:
        st.info("Please upload a PDF file to begin redaction.")

if __name__ == "__main__":
    main()
