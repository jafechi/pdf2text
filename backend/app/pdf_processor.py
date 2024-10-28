from PIL import Image
import pytesseract
import pdf2image
import PyPDF2


class PDFProcessor:
    def __init__(self, tesseract_path='/usr/bin/tesseract', poppler_path='/usr/bin'):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        self.poppler_path = poppler_path

    def is_page_image_based(self, page: PyPDF2._page.PageObject) -> bool:
        """
        Assume a page is image-based if the extracted text is very short.
        """
        text = page.extract_text().strip()
        return len(text) < 10

    def convert_pdf_page_to_image(self, pdf_path: str, page_number: int) -> Image.Image:
        """
        Convert a single PDF page to an image.
        """
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
            print(f"Error converting page {page_number}: {str(e)}")
            return None

    def extract_text_from_image(self, image: Image.Image) -> str:
        """
        Extract text from an image using OCR.
        """
        try:
            extracted_text = pytesseract.image_to_string(image)
            return extracted_text.strip()
        except Exception as e:
            print(f"OCR Error: {str(e)}")
            return ""

    def process_pdf(self, pdf_path, output_path=None):
        """
        Process a PDF file, using OCR for scanned pages and direct extraction for digital text.
        Returns the extracted text and optionally saves it to a file.
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                full_text = []

                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]

                    # Check if the page is image-based
                    if self.is_page_image_based(page):
                        # Convert page to image and perform OCR
                        image = self.convert_pdf_page_to_image(pdf_path, page_num)

                        if image:
                            text = self.extract_text_from_image(image)
                        else:
                            text = ""
                    else:
                        # Extract text directly from PDF
                        text = page.extract_text()

                    full_text.append(text)
                    print(f"Processed page {page_num + 1}/{len(pdf_reader.pages)}")

                result = "\n\n".join(full_text)

                # Save to file if an output path is provided
                if output_path:
                    with open(output_path, 'w', encoding='utf-8') as out_file:
                        out_file.write(result)

                return result

        except Exception as e:
            print(f"Error processing PDF: {str(e)}")
            return None
