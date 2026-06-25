"""
Pexels API Integration Module
==============================
Provides integration with the Pexels API for searching and downloading
high-quality images and videos for presentations.

CHANGE LOG (v2.0):
- FIX: get_color_palette_from_image now handles RGBA images safely (not just RGB)
- No other logic changes — all existing functionality preserved.
"""

import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

# ============================================================
# Load environment variables (API keys from .env)
# ============================================================
load_dotenv()

# Pexels API Configuration
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
if not PEXELS_API_KEY:
    print("⚠ WARNING: PEXELS_API_KEY not found in .env file")
    print("   Presentations will fall back to no-image mode")
    print("   Add this to .env: PEXELS_API_KEY=your_pexels_api_key_here")
PEXELS_BASE_URL = "https://api.pexels.com/v1"
PEXELS_VIDEO_URL = "https://api.pexels.com/videos"

MEDIA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "generated_files", "pexels_media"
)
os.makedirs(MEDIA_DIR, exist_ok=True)


class PexelsClient:
    """Client for interacting with the Pexels API."""

    def __init__(self, api_key: str = PEXELS_API_KEY):
        self.api_key = api_key
        self.headers = {
            "Authorization": api_key,
            "User-Agent": "AI-Assistant/1.0",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def search_photos(
        self,
        query: str,
        per_page: int = 10,
        page: int = 1,
        orientation: str = "landscape",
        size: str = "large",
    ) -> List[Dict]:
        try:
            url = f"{PEXELS_BASE_URL}/search"
            params = {
                "query": query,
                "per_page": min(per_page, 80),
                "page": page,
                "orientation": orientation,
            }
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            photos = []
            for photo in data.get("photos", []):
                photo_info = {
                    "id": photo["id"],
                    "photographer": photo["photographer"],
                    "url": photo["url"],
                    "src": self._get_best_image_url(photo["src"], size),
                    "width": photo["width"],
                    "height": photo["height"],
                    "avg_color": photo.get("avg_color", "#333333"),
                    "alt": photo.get("alt", query),
                }
                photos.append(photo_info)
            return photos
        except Exception as e:
            print(f"[Pexels Photo Search Error]: {e}")
            return []

    def _get_best_image_url(self, src: Dict, size: str) -> str:
        size_mapping = {
            "large": ["large2x", "large", "medium", "small", "original"],
            "medium": ["medium", "small", "large2x", "large", "original"],
            "small": ["small", "thumbnail", "medium", "large", "original"],
        }
        preferred_sizes = size_mapping.get(size, ["original"])
        for size_key in preferred_sizes:
            if size_key in src and src[size_key]:
                return src[size_key]
        return src.get("original", src.get("large2x", ""))

    def search_videos(
        self, query: str, per_page: int = 10, page: int = 1
    ) -> List[Dict]:
        try:
            url = f"{PEXELS_VIDEO_URL}/search"
            params = {"query": query, "per_page": min(per_page, 80), "page": page}
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            videos = []
            for video in data.get("videos", []):
                video_files = video.get("video_files", [])
                best_video_url = ""
                for quality in [1080, 720, 540, 360, 268, 148]:
                    for vf in video_files:
                        if (
                            vf.get("quality") == quality
                            and vf.get("file_type") == "video/mp4"
                        ):
                            best_video_url = vf.get("link", "")
                            break
                    if best_video_url:
                        break
                if not best_video_url and video_files:
                    for vf in video_files:
                        if vf.get("file_type") == "video/mp4":
                            best_video_url = vf.get("link", "")
                            break
                video_info = {
                    "id": video["id"],
                    "title": video.get("title", query),
                    "duration": video.get("duration", 0),
                    "url": video["url"],
                    "video_url": best_video_url,
                    "thumbnail": video.get("image", ""),
                    "width": video.get("width", 1920),
                    "height": video.get("height", 1080),
                    "full_res": video.get("full_res", False),
                }
                videos.append(video_info)
            return videos
        except Exception as e:
            print(f"[Pexels Video Search Error]: {e}")
            return []

    def download_photo(
        self, photo_url: str, save_path: str, timeout: int = 30
    ) -> Optional[str]:
        try:
            response = self.session.get(photo_url, timeout=timeout, stream=True)
            response.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return save_path
        except Exception as e:
            print(f"[Pexels Download Error]: {e}")
            return None

    def download_video(
        self, video_url: str, save_path: str, timeout: int = 60
    ) -> Optional[str]:
        try:
            response = self.session.get(video_url, timeout=timeout, stream=True)
            response.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return save_path
        except Exception as e:
            print(f"[Pexels Video Download Error]: {e}")
            return None

    def get_photo_of_the_day(self) -> Optional[Dict]:
        try:
            url = f"{PEXELS_BASE_URL}/curated"
            params = {"per_page": 1}
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("photos"):
                photo = data["photos"][0]
                return {
                    "id": photo["id"],
                    "photographer": photo["photographer"],
                    "url": photo["url"],
                    "src": photo["src"].get(
                        "large2x", photo["src"].get("original", "")
                    ),
                    "width": photo["width"],
                    "height": photo["height"],
                    "avg_color": photo.get("avg_color", "#333333"),
                }
            return None
        except Exception as e:
            print(f"[Pexels Curated Error]: {e}")
            return None

    def search_for_presentation(self, query: str, count: int = 5) -> List[Dict]:
        enhanced_queries = [
            f"{query} background",
            f"{query} wallpaper",
            f"{query} abstract",
            query,
        ]
        all_photos = []
        for eq in enhanced_queries:
            photos = self.search_photos(
                eq, per_page=count, orientation="landscape", size="large"
            )
            all_photos.extend(photos)
            if len(all_photos) >= count:
                break
        seen_ids = set()
        unique_photos = []
        for photo in all_photos:
            if photo["id"] not in seen_ids:
                seen_ids.add(photo["id"])
                unique_photos.append(photo)
        return unique_photos[:count]


_pexels_client = None


def get_pexels_client() -> PexelsClient:
    global _pexels_client
    if _pexels_client is None:
        _pexels_client = PexelsClient()
    return _pexels_client


def search_images(
    query: str, count: int = 5, orientation: str = "landscape"
) -> List[Dict]:
    client = get_pexels_client()
    return client.search_photos(query, per_page=count, orientation=orientation)


def search_videos_for_presentation(query: str, count: int = 3) -> List[Dict]:
    client = get_pexels_client()
    return client.search_videos(query, per_page=count)


def download_background_image(query: str, slide_number: int = 0) -> Optional[str]:
    client = get_pexels_client()
    photos = client.search_for_presentation(query, count=3)
    if not photos:
        photos = client.search_photos(
            query, per_page=3, orientation="landscape", size="large"
        )
    if photos:
        photo = photos[0]
        filename = f"slide_{slide_number}_background_{photo['id']}.jpg"
        save_path = os.path.join(MEDIA_DIR, filename)
        downloaded = client.download_photo(photo["src"], save_path)
        if downloaded:
            print(f"  ✓ Downloaded background: {query} → {save_path}")
            return downloaded
    return None


def get_color_palette_from_image(image_path: str) -> Dict:
    """
    Extract color palette from image.
    FIX: Handles both RGB and RGBA images safely to prevent pixel-unpacking errors.
    """
    try:
        from PIL import Image

        img = Image.open(image_path)

        # ── FIX: Convert to RGB to guarantee 3-channel pixels ──────────────
        img = img.convert("RGB")
        # ────────────────────────────────────────────────────────────────────

        img = img.resize((100, 100))
        pixels = list(img.getdata())

        color_count = {}
        for r, g, b in pixels:
            rq, gq, bq = r // 32 * 32, g // 32 * 32, b // 32 * 32
            color = (rq, gq, bq)
            color_count[color] = color_count.get(color, 0) + 1

        sorted_colors = sorted(color_count.items(), key=lambda x: x[1], reverse=True)
        dominant_colors = [c[0] for c in sorted_colors[:5]]

        avg_brightness = (
            sum(
                (r * 299 + g * 587 + b * 114) / 1000 for r, g, b in dominant_colors
            )
            / len(dominant_colors)
        )

        text_color = (255, 255, 255) if avg_brightness < 128 else (0, 0, 0)

        return {
            "dominant_colors": dominant_colors,
            "text_color": text_color,
            "is_dark_background": avg_brightness < 128,
        }

    except Exception as e:
        print(f"[Color Palette Error]: {e}")
        return {
            "dominant_colors": [(0, 0, 0), (255, 255, 255)],
            "text_color": (255, 255, 255),
            "is_dark_background": True,
        }


def create_background_with_overlay(
    background_image_path: str,
    overlay_color: Tuple[int, int, int, int] = (0, 0, 0, 128),
    output_path: str = None,
) -> str:
    try:
        from PIL import Image

        bg = Image.open(background_image_path).convert("RGBA")
        bg = bg.resize((1920, 1080))
        overlay = Image.new("RGBA", bg.size, overlay_color)
        composite = Image.alpha_composite(bg, overlay)

        if output_path is None:
            base_name = os.path.splitext(
                os.path.basename(background_image_path)
            )[0]
            output_path = os.path.join(MEDIA_DIR, f"{base_name}_overlay.png")

        composite.convert("RGB").save(output_path, "JPEG", quality=95)
        return output_path

    except Exception as e:
        print(f"[Background Overlay Error]: {e}")
        return background_image_path


if __name__ == "__main__":
    print("Testing Pexels API Integration...")
    client = get_pexels_client()

    print("\n1. Testing photo search for 'technology'...")
    photos = client.search_photos("technology", per_page=3, orientation="landscape")
    for photo in photos:
        print(f"   - {photo['alt']} by {photo['photographer']}")

    print("\n2. Testing video search for 'nature'...")
    videos = client.search_videos("nature", per_page=3)
    for video in videos:
        print(f"   - {video['title']} ({video['duration']}s)")

    print("\n3. Testing presentation background search for 'business'...")
    bg_photos = client.search_for_presentation("business", count=3)
    for photo in bg_photos:
        print(f"   - {photo['alt']} ({photo['width']}x{photo['height']})")

    print("\n✓ Pexels API Integration test complete!")