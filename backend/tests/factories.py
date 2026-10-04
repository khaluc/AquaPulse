"""Synthetic photos for tests: real photos cannot live in the repo."""

import io
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


def noise_photo(size=(800, 600), seed=0, blur=0.0, brightness=1.0):
    """Noise stands in for a sharp photo: plenty of high-frequency detail, no structure."""
    rng = random.Random(seed)
    image = Image.new("RGB", size)
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                   for _ in range(size[0] * size[1])])
    return _degrade(image, blur, brightness)


def scene_photo(size=(800, 600), seed=0, blur=0.0, brightness=1.0):
    """Shapes on a gradient: structured like a real photo, so perceptual hashes are stable."""
    rng = random.Random(seed)
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        draw.line([(0, y), (size[0], y)], fill=(40 + y % 120, 90, 140))
    for _ in range(12):
        x, y = rng.randrange(size[0] - 120), rng.randrange(size[1] - 120)
        draw.ellipse([x, y, x + rng.randrange(40, 120), y + rng.randrange(40, 120)],
                     fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    return _degrade(image, blur, brightness)


def _degrade(image, blur, brightness):
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if brightness != 1.0:
        image = ImageEnhance.Brightness(image).enhance(brightness)
    return image


def jpeg_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()
