import streamlit as st
import tempfile
import os
import logging
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
import fitz  # PyMuPDF
import re

# --- ContactPIIMasker class (focused on per-page redaction) ---
class ContactPIIMasker:
    """PDF masker for emails, phone numbers, LinkedIn URLs and photos."""
    def __init__(self, confidence_threshold: float = 0.35, enable_logging: bool = False):
        self.confidence_threshold = confidence_threshold
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()
        if enable_logging:
            logging.basicConfig(level=logging.INFO,
                                format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def fix_contact_formatting(self, text: str) -> str:
        # normalize broken emails and phones
        text = re.sub(r'([\w._%+-]+)@([\w.-]+)[\s\n]*\.?[\s\n]*([A-Za-z]{2,})', r'\1@\2.\3', text)
        text = re.sub(r'(\(?\d{3}\)?)[.\s\n-]?(\d{3})[.\s\n-]?(\d{4})', r'\1-\2-\3', text)
        text = re.sub(r'(\+\d{1,3})[\s\n-]?(\d{3,4})[\s\n-]?(\d{3,4})[\s\n-]?(\d{3,4})', r'\1-\2-\3-\4', text)
        return text

    def mask_contact_info_in_pdf(self, pdf_path: str, output_path: str,
                                 remove_photos: bool = True)
        """
        Redacts emails, phones, LinkedIn URLs, and optionally removes images.
        Returns (total_redactions, report_text).
        """
        doc = fitz.open(pdf_path)
        total_redactions = 0

        # compile patterns
        email_re    = re.compile(r'\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b')
        phone_re    = re.compile(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
        linkedin_re = re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+', re.IGNORECASE)

        report_lines = []
        
        for page_num, page in enumerate(doc, start=1):
            page_redactions = 0
            page_dict = page.get_text("dict")

            # remove images if requested
            if remove_photos:
                for img in page.get_images():
                    for rect in page.get_image_rects(img[0]):
                        page.add_redact_annot(rect, fill=(1,1,1))
                        page_redactions += 1
            
            # redact text by span
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

                    # email or phone
                    if email_re.search(txt_i) or phone_re.search(txt_i):
                        spans_to_redact = spans_i
                    else:
                        # two-line linkedin URL
                        if idx + 1 < len(lines):
                            spans_j = lines[idx+1].get("spans", [])
                            txt_j = "".join(s["text"] for s in spans_j)
                            if linkedin_re.search(txt_i + txt_j):
                                spans_to_redact = spans_i + spans_j
                                skip_next = True

                    for span in spans_to_redact:
                        bbox = fitz.Rect(span["bbox"])
                        page.add_redact_annot(bbox, fill=(0,0,0))
                        page_redactions += 1

            if page_redactions:
                page.apply_redactions()
                self.logger.info(f"Page {page_num}: redacted {page_redactions} items")
                total_redactions += page_redactions

        # save output
        doc.save(output_path)
        doc.close()

        report = (
            f"Contact Masking Report\n"
            f"Total items redacted: {total_redactions}\n"
        )
        return total_redactions, report

# --- Streamlit App ---
def main():
    st.set_page_config(page_title="PII Redaction App", layout="wide")
    st.title("🔒 Contact PII Redaction")
    st.write("Upload a PDF and automatically mask emails, phone numbers, LinkedIn URLs, and remove images.")

    # sidebar settings
    st.sidebar.header("Options")
    remove_photos   = st.sidebar.checkbox("Remove images/photos", True)
    confidence_val  = st.sidebar.slider("Detection confidence (unused for regex)", 0.0, 1.0, 0.35)

    uploaded = st.file_uploader("Choose a PDF file", type=["pdf"] )

    if uploaded:
        tmp_dir = tempfile.mkdtemp()
        input_path = os.path.join(tmp_dir, uploaded.name)
        with open(input_path, "wb") as f:
            f.write(uploaded.getbuffer())

        output_name = f"masked_{uploaded.name}"
        output_path = os.path.join(tmp_dir, output_name)

        if st.button("Start Redaction"):
            masker = ContactPIIMasker(confidence_threshold=confidence_val)
            with st.spinner("Processing PDF..."):
                redacted_count, report_text = masker.mask_contact_info_in_pdf(
                    input_path, output_path, remove_photos=remove_photos
                )

            st.success(f"✅ Redaction complete — {redacted_count} items masked.")
            with open(output_path, "rb") as out_f:
                st.download_button(
                    label="Download Masked PDF",
                    data=out_f,
                    file_name=output_name,
                    mime="application/pdf"
                )

            st.subheader("Masking Report")
            st.text(report_text)
            st.download_button(
                label="Download Report",
                data=report_text,
                file_name=output_name.replace('.pdf', '_report.txt'),
                mime="text/plain"
            )

if __name__ == "__main__":
    main()
