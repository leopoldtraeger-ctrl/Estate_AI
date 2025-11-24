import pytesseract
from PIL import Image

def extract_text_from_image(path: str) -> str:
    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang="eng")
        return text
    except Exception as e:
        return f"OCR_ERROR: {str(e)}"
