from PIL import Image

import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

print(pytesseract.image_to_data(Image.open('data/test.jpg')))

# Should I only use OCR when the PDF is image-based? I guess. I will need to detect this.
# Although, the PDF might be image based in some pages and text based in others.
# The easiest approach is to always use OCR.
