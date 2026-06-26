"""
Thumbnail Watermark Utility.
Adds watermark text to thumbnail images.
"""
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config import THUMBNAIL_TEXT
from util.logging import log


def add_watermark(
    thumb_path: str,
    text: Optional[str] = None,
    font_size: int = 18,
    opacity: int = 200
) -> str:
    """
    Add watermark text to a thumbnail image.
    
    Args:
        thumb_path: Path to the thumbnail image
        text: Watermark text (defaults to THUMBNAIL_TEXT from config)
        font_size: Size of the watermark text
        opacity: Text opacity (0-255)
    
    Returns:
        Path to the watermarked image (same as input, modified in place)
    """
    if not text:
        text = THUMBNAIL_TEXT
    
    if not text or not text.strip():
        return thumb_path  # No watermark text configured
    
    if not os.path.exists(thumb_path):
        log.warning(f"[Watermark] Thumbnail not found: {thumb_path}")
        return thumb_path
    
    try:
        # Open the image
        img = Image.open(thumb_path)
        
        # Convert to RGBA for transparency support
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Create a transparent overlay for the watermark
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Try to use a nice font, fall back to default
        font = None
        try:
            # Try common system fonts
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    font = ImageFont.truetype(font_path, font_size)
                    break
        except Exception:
            pass
        
        if font is None:
            # Use default font (smaller)
            font = ImageFont.load_default()
        
        # Get text bounding box
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Calculate center position
        x = (img.width - text_width) // 2
        y = (img.height - text_height) // 2 - 70
         
        # Draw black outline (stroke effect)
        outline_color = (0, 0, 0, opacity)
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        
        # Draw white text on top
        text_color = (255, 255, 255, opacity)
        draw.text((x, y), text, font=font, fill=text_color)
        
        # Composite the overlay onto the original image
        img = Image.alpha_composite(img, overlay)
        
        # Convert back to RGB for JPEG compatibility
        img = img.convert('RGB')
        
        # Save back to the same path
        img.save(thumb_path, 'JPEG', quality=85)
        
        log.debug(f"[Watermark] ✓ Added '{text}' to {thumb_path}")
        return thumb_path
        
    except Exception as e:
        log.error(f"[Watermark] Failed to add watermark: {e}")
        return thumb_path  # Return original path on error
