import os
import io
import base64
import logging
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
import numpy as np
from openai import OpenAI

logger = logging.getLogger(__name__)

# Lazy-initialize OpenAI client to avoid startup failures if key is missing
_client = None

def get_openai_client():
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            _client = OpenAI(api_key=api_key)
    return _client

def enhance_image(image_file):
    """
    Natural, professional image enhancement for e-commerce
    - Subtle improvements that look real
    - Clean white background
    - Professional but natural appearance
    - No over-processing or artifacts
    """
    try:
        # Open image
        image = Image.open(image_file)
        
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Step 1: Gentle noise reduction (denoise before any processing)
        enhanced = image.filter(ImageFilter.MedianFilter(size=3))
        
        # Step 2: Convert light backgrounds to pure white
        img_array = np.array(enhanced).astype(np.float32)
        lightness = np.mean(img_array, axis=2)
        
        # Be selective - only convert very light pixels (235+) to white
        # This preserves product colors while cleaning background
        background_mask = lightness > 235
        for i in range(3):
            img_array[:,:,i][background_mask] = 255
        
        enhanced = Image.fromarray(img_array.astype(np.uint8))
        
        # Step 3: Gentle auto-contrast for better exposure
        enhanced = ImageOps.autocontrast(enhanced, cutoff=1)
        
        # Step 4: Subtle brightness boost (only 10%)
        enhancer = ImageEnhance.Brightness(enhanced)
        enhanced = enhancer.enhance(1.1)
        
        # Step 5: Very gentle color enhancement (only 15%)
        enhancer = ImageEnhance.Color(enhanced)
        enhanced = enhancer.enhance(1.15)
        
        # Step 6: Subtle contrast (only 10%)
        enhancer = ImageEnhance.Contrast(enhanced)
        enhanced = enhancer.enhance(1.1)
        
        # Step 7: Professional sharpening (single pass, moderate settings)
        enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))
        
        # Step 8: Clean up any remaining light gray background pixels
        result_array = np.array(enhanced).astype(np.uint8)
        lightness = np.mean(result_array, axis=2)
        final_bg_mask = lightness > 240
        
        for i in range(3):
            result_array[:,:,i][final_bg_mask] = 255
        
        result_image = Image.fromarray(result_array)
        
        # Save to bytes
        img_io = io.BytesIO()
        result_image.save(img_io, format='PNG', quality=95)
        img_io.seek(0)
        
        return {
            'success': True,
            'image_data': img_io.getvalue(),
            'format': 'PNG'
        }
        
    except Exception as e:
        logger.error(f"Image enhancement failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def remove_background(image_file):
    """
    Remove background from product image using simple color-based approach
    Creates white background for marketplace compliance
    """
    try:
        # Open image
        image = Image.open(image_file)
        
        # Convert to RGBA if not already
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Get image data
        data = image.getdata()
        
        # Create new image data with white background
        new_data = []
        for item in data:
            # Change all nearly white or light pixels (likely background) to transparent
            # This is a simple heuristic - works best with products on white/light backgrounds
            if item[0] > 220 and item[1] > 220 and item[2] > 220:
                new_data.append((255, 255, 255, 0))  # Transparent
            else:
                new_data.append(item)
        
        # Update image data
        image.putdata(new_data)
        
        # Create white background
        white_bg = Image.new('RGBA', image.size, (255, 255, 255, 255))
        white_bg.paste(image, (0, 0), image)
        
        # Convert back to RGB
        result_image = white_bg.convert('RGB')
        
        # Save to bytes
        img_io = io.BytesIO()
        result_image.save(img_io, format='PNG', quality=95)
        img_io.seek(0)
        
        return {
            'success': True,
            'image_data': img_io.getvalue(),
            'format': 'PNG'
        }
        
    except Exception as e:
        logger.error(f"Background removal failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def generate_lifestyle_image(product_name, product_description, style="professional product photography", reference_image=None):
    """
    Generate AI lifestyle image using OpenAI DALL-E
    
    Args:
        product_name: Name of the product
        product_description: Description of the product/scene
        style: Style of the image (default: professional product photography)
        reference_image: Optional file object with reference product photo
    
    Returns:
        dict with success status and image URL or error
    """
    try:
        # Analyze reference image if provided
        reference_details = ""
        if reference_image:
            try:
                img = Image.open(reference_image)
                
                # Get dominant colors
                img_small = img.resize((100, 100))
                if img_small.mode != 'RGB':
                    img_small = img_small.convert('RGB')
                
                pixels = list(img_small.getdata())
                avg_color = tuple(int(sum(channel)/len(pixels)) for channel in zip(*pixels))
                
                # Determine color description
                r, g, b = avg_color
                if r > 200 and g > 200 and b > 200:
                    color_desc = "white or light colored"
                elif r > 150 and g < 100 and b < 100:
                    color_desc = "red"
                elif r < 100 and g > 150 and b < 100:
                    color_desc = "green"
                elif r < 100 and g < 100 and b > 150:
                    color_desc = "blue"
                elif r > 150 and g > 150 and b < 100:
                    color_desc = "yellow"
                else:
                    color_desc = "multicolored"
                
                reference_details = f"The product is {color_desc}. "
                logger.info(f"Reference image analyzed: {reference_details}")
            except Exception as e:
                logger.warning(f"Could not analyze reference image: {str(e)}")
        
        # Create marketplace-compliant prompt
        prompt = f"""Professional product photography of {product_name}. {reference_details}{product_description}. 
        Clean white background, high quality, well-lit, centered composition, commercial product shot, 
        no people, no text overlays, {style}. Professional studio lighting, sharp focus, product-only image 
        suitable for e-commerce marketplaces like Amazon and eBay."""
        
        # Limit prompt length
        if len(prompt) > 1000:
            prompt = prompt[:1000]
        
        logger.info(f"Generating image with prompt: {prompt[:200]}...")
        
        # Call OpenAI DALL-E API
        openai_client = get_openai_client()
        if not openai_client:
            return {
                'success': False,
                'error': 'OpenAI API key not configured'
            }
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        image_url = response.data[0].url
        
        return {
            'success': True,
            'image_url': image_url,
            'revised_prompt': response.data[0].revised_prompt
        }
        
    except Exception as e:
        logger.error(f"AI image generation failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def check_marketplace_compliance(image_file):
    """
    Check if image meets Amazon/eBay marketplace policies
    
    Amazon/eBay Requirements:
    - Minimum 1000px on longest side (recommended 2000px+)
    - White or light background preferred
    - Product must fill 85%+ of frame
    - No text overlays, logos, or watermarks
    - No people (unless modeling clothing/accessories)
    - High resolution and clarity
    """
    try:
        # Open image
        image = Image.open(image_file)
        width, height = image.size
        
        issues = []
        warnings = []
        
        # Check minimum size
        longest_side = max(width, height)
        if longest_side < 1000:
            issues.append(f"Image too small: {longest_side}px. Minimum 1000px required.")
        elif longest_side < 2000:
            warnings.append(f"Image size {longest_side}px is acceptable but 2000px+ recommended for zoom.")
        
        # Check aspect ratio (should be reasonable)
        aspect_ratio = max(width, height) / min(width, height)
        if aspect_ratio > 3:
            warnings.append(f"Unusual aspect ratio: {aspect_ratio:.1f}:1. Consider cropping to square or 4:3.")
        
        # Convert to numpy for analysis
        img_array = np.array(image)
        
        # Check if background is mostly white/light
        if len(img_array.shape) == 3:
            # Calculate average brightness of edges (likely background)
            edge_pixels = np.concatenate([
                img_array[0, :],  # top edge
                img_array[-1, :],  # bottom edge
                img_array[:, 0],  # left edge
                img_array[:, -1]  # right edge
            ])
            avg_brightness = np.mean(edge_pixels)
            
            if avg_brightness < 200:  # Not white/light background
                warnings.append("Background is not white or light colored. Amazon/eBay prefer white backgrounds.")
        
        # Check file format
        if image.format not in ['JPEG', 'PNG', 'TIFF']:
            issues.append(f"Format {image.format} may not be supported. Use JPEG or PNG.")
        
        compliance_status = 'compliant' if not issues else 'non_compliant'
        if not issues and warnings:
            compliance_status = 'compliant_with_warnings'
        
        return {
            'success': True,
            'compliant': len(issues) == 0,
            'status': compliance_status,
            'issues': issues,
            'warnings': warnings,
            'dimensions': f"{width}x{height}",
            'format': image.format
        }
        
    except Exception as e:
        logger.error(f"Compliance check failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
