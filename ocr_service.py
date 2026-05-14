import re
import pytesseract
from PIL import Image
import cv2
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def preprocess_image(image):
    """
    Preprocess image for better OCR results
    """
    # Convert PIL Image to numpy array
    img_array = np.array(image)
    
    # Convert to grayscale if needed
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    
    # Apply thresholding to get better contrast
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Denoise
    denoised = cv2.fastNlMeansDenoising(thresh)
    
    return Image.fromarray(denoised)

def extract_invoice_data(image_file):
    """
    Extract invoice data from uploaded image using OCR
    
    Returns dict with: invoice_number, invoice_date, total_amount, supplier_name, raw_text
    """
    try:
        # Open and preprocess image
        image = Image.open(image_file)
        processed_image = preprocess_image(image)
        
        # Perform OCR
        raw_text = pytesseract.image_to_string(processed_image)
        logger.info(f"OCR extracted text: {raw_text[:200]}...")
        
        # Parse extracted text
        result = {
            'invoice_number': extract_invoice_number(raw_text),
            'invoice_date': extract_date(raw_text),
            'total_amount': extract_amount(raw_text),
            'supplier_name': extract_supplier(raw_text),
            'raw_text': raw_text,
            'success': True
        }
        
        return result
        
    except Exception as e:
        logger.error(f"OCR extraction failed: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'invoice_number': None,
            'invoice_date': None,
            'total_amount': None,
            'supplier_name': None,
            'raw_text': None
        }

def extract_invoice_number(text):
    """
    Extract invoice number from text
    Common patterns: Invoice #123, INV-456, Invoice No: 789
    """
    patterns = [
        r'Invoice\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'INV\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'Invoice\s*No\.?\s*:?\s*([A-Z0-9\-]+)',
        r'Bill\s*No\.?\s*:?\s*([A-Z0-9\-]+)',
        r'Reference\s*:?\s*([A-Z0-9\-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return None

def extract_date(text):
    """
    Extract date from text
    Common formats: DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-MM-YYYY
    """
    date_patterns = [
        (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', '%d/%m/%Y'),  # DD/MM/YYYY
        (r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', '%Y/%m/%d'),  # YYYY-MM-DD
        (r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})', '%d %b %Y'),
    ]
    
    for pattern, date_format in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                date_str = match.group(0)
                # Try to parse the date
                parsed_date = datetime.strptime(date_str, date_format)
                return parsed_date.strftime('%Y-%m-%d')
            except:
                continue
    
    return None

def extract_amount(text):
    """
    Extract total amount from text
    Common patterns: Total: $123.45, Amount: 456.78, Total Due: £789.00
    """
    patterns = [
        r'Total\s*:?\s*[$£€]?\s*(\d{1,10}[,.]?\d{0,2})',
        r'Amount\s*:?\s*[$£€]?\s*(\d{1,10}[,.]?\d{0,2})',
        r'Total\s*Due\s*:?\s*[$£€]?\s*(\d{1,10}[,.]?\d{0,2})',
        r'Grand\s*Total\s*:?\s*[$£€]?\s*(\d{1,10}[,.]?\d{0,2})',
        r'Balance\s*:?\s*[$£€]?\s*(\d{1,10}[,.]?\d{0,2})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '')
            try:
                return float(amount_str)
            except:
                continue
    
    return None

def extract_supplier(text):
    """
    Extract supplier name - typically at the top of the invoice
    Take first few lines and clean them up
    """
    lines = text.split('\n')
    
    # Look for common supplier indicators
    supplier_keywords = ['supplier', 'vendor', 'from', 'sold by', 'company']
    
    for i, line in enumerate(lines[:10]):  # Check first 10 lines
        line_lower = line.lower()
        for keyword in supplier_keywords:
            if keyword in line_lower:
                # Return the next non-empty line after the keyword
                for j in range(i, min(i+3, len(lines))):
                    potential_name = lines[j].strip()
                    if potential_name and len(potential_name) > 3:
                        return potential_name[:100]  # Limit length
    
    # If no keyword found, return first substantial line
    for line in lines[:5]:
        cleaned = line.strip()
        if cleaned and len(cleaned) > 3 and not cleaned.lower().startswith('invoice'):
            return cleaned[:100]
    
    return None
