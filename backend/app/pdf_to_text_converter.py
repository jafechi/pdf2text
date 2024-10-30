from typing import Optional
from PIL import Image
import pytesseract
import pdf2image
import PyPDF2


class PDFToTextConverter:
    def __init__(self, tesseract_path='/usr/bin/tesseract', poppler_path='/usr/bin'):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        self.poppler_path = poppler_path

    def _is_page_image_based(self, page: PyPDF2.PageObject) -> bool:
        """
        Assume a page is image-based if the extracted text is very short, in this case, less than 10 characters.
        """
        text = page.extract_text().strip()
        return len(text) < 10

    def convert_pdf_page_to_image(self, pdf_path: str, page_number: int) -> Optional[Image.Image]:
        try:
            images = pdf2image.convert_from_path(
                pdf_path,
                first_page=page_number + 1,
                last_page=page_number + 1,
                dpi=300,
                poppler_path=self.poppler_path
            )
            return images[0]
        except Exception as e:
            print(f"Error converting page {page_number} to image: {str(e)}")
            return None

    def _extract_text_from_image(self, image: Image.Image) -> str:
        """
        Extract text from an image using OCR.
        """
        try:
            extracted_text = pytesseract.image_to_string(image)
            return extracted_text.strip()
        except Exception as e:
            print(f"OCR Error: {str(e)}")
            return ""

    def _process_single_page(self, pdf_path: str, page_num: int, pdf_reader: PyPDF2.PdfReader) -> str:
        page = pdf_reader.pages[page_num]

        if self._is_page_image_based(page):
            image = self.convert_pdf_page_to_image(pdf_path, page_num)
            if image:
                text = self._extract_text_from_image(image)
            else:
                text = ""
        else:
            # The page is text-based, so we can just extract the text directly
            text = page.extract_text()

        return text

    def convert_pdf(self, pdf_path: str, output_path: str) -> str:
        """
        Process a PDF file to extract text from it.
        We use OCR for image-based pages and direct text extraction for text-based pages.
        """
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            full_text = []
            total_pages = len(pdf_reader.pages)

            for page_num in range(total_pages):
                text = self._process_single_page(pdf_path, page_num, pdf_reader)
                full_text.append(text)

                print(f"Processed page {page_num + 1}/{total_pages}")

            result = "\n\n".join(full_text)

            with open(output_path, 'w', encoding='utf-8') as out_file:
                out_file.write(result)

            return result
