"""
Cultural & Historical Image Search Module
===========================================
Specialized image search for cultural, religious, historical, and mythological topics.
Uses DuckDuckGo image search and Wikipedia API to find relevant, authentic images
instead of generic stock photos from Pexels.

Features:
- Detects cultural/religious/historical/mythological topics
- Searches DuckDuckGo images for real, relevant photos
- Fetches Wikipedia article images for authoritative visuals
- Provides enhanced image queries for better Pexels fallback
- Downloads and caches images locally
"""

import os
import re
import json
import time
import requests
import hashlib
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from urllib.parse import quote, urlparse

# ── Configuration ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CULTURAL_MEDIA_DIR = os.path.join(BASE_DIR, "generated_files", "cultural_media")
os.makedirs(CULTURAL_MEDIA_DIR, exist_ok=True)

# Local culture folder with user-provided images
LOCAL_CULTURE_DIR = os.path.join(BASE_DIR, "culture")
os.makedirs(LOCAL_CULTURE_DIR, exist_ok=True)

CACHE_FILE = os.path.join(CULTURAL_MEDIA_DIR, "image_cache.json")

# Load cache if exists
_image_cache = {}
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            _image_cache = json.load(f)
    except Exception:
        _image_cache = {}

# ── Cultural Topic Database ────────────────────────────────────
# Topics that need culturally relevant images instead of stock photos
CULTURAL_KEYWORDS = {
    # Indian Mythology & Epics
    "mahabharat": ["Mahabharata", "Mahabharat 2013", "Mahabharat TV series", "Mahabharata characters"],
    "mahabharata": ["Mahabharata", "Mahabharat 2013", "Mahabharat TV series", "Mahabharata characters"],
    "ramayan": ["Ramayana", "Ramayan TV series", "Ramayana epic", "Lord Rama"],
    "ramayana": ["Ramayana", "Ramayan TV series", "Ramayana epic", "Lord Rama"],
    "sri krishna": ["Lord Krishna", "Krishna Bhagavad Gita", "Krishna painting", "Sri Krishna artwork"],
    "krishna": ["Lord Krishna", "Krishna Bhagavad Gita", "Krishna painting", "Sri Krishna artwork"],
    "lord krishna": ["Lord Krishna", "Krishna Bhagavad Gita", "Krishna painting", "Sri Krishna artwork"],
    "shiva": ["Lord Shiva", "Shiva meditation", "Shiva painting", "Shiva artwork"],
    "lord shiva": ["Lord Shiva", "Shiva meditation", "Shiva wallpaper", "Shiva artwork"],
    "vishnu": ["Lord Vishnu", "Vishnu painting", "Vishnu artwork", "Vishnu avatar"],
    "brahma": ["Lord Brahma", "Brahma painting", "Brahma creator god"],
    "goddess durga": ["Maa Durga", "Goddess Durga", "Durga painting", "Durga artwork"],
    "durga": ["Maa Durga", "Goddess Durga", "Durga portrait", "Durga Maa"],
    "saraswati": ["Goddess Saraswati", "Maa Saraswati", "Saraswati painting"],
    "lakshmi": ["Goddess Lakshmi", "Maa Lakshmi", "Lakshmi painting"],
    "ganesh": ["Lord Ganesha", "Ganesh Chaturthi", "Ganesha painting", "Ganesha artwork"],
    "hanuman": ["Lord Hanuman", "Hanuman painting", "Hanuman artwork", "Hanuman statue"],
    "arjuna": ["Arjuna Mahabharata", "Arjuna archer", "Arjuna character"],
    "bheem": ["Bheem Mahabharata", "Bheema character"],
    "duryodhana": ["Duryodhana Mahabharata", "Duryodhana character"],
    "karna": ["Karna Mahabharata", "Karna character"],
    "draupadi": ["Draupadi Mahabharata", "Draupadi character"],
    "bhishma": ["Bhishma Mahabharata", "Bhishma Pitamah"],
    
    # Indian Religious Figures
    "guru nanak": ["Guru Nanak Dev Ji", "Guru Nanak painting", "Sikh Guru Nanak"],
    "guru gobind singh": ["Guru Gobind Singh Ji", "Guru Gobind Singh painting"],
    "sai baba": ["Sai Baba of Shirdi", "Sai Baba photo", "Sai Baba painting"],
    "swami vivekananda": ["Swami Vivekananda photo", "Swami Vivekananda portrait"],
    "tagore": ["Rabindranath Tagore photo", "Rabindranath Tagore portrait"],
    
    # Hindu Gods & Goddesses (general)
    "hindu god": ["Hindu god wallpaper", "Hindu deities artwork", "Hindu god image"],
    "hindu mythology": ["Hindu mythology painting", "Hindu gods and goddesses"],
    
    # Other Mythologies
    "greek mythology": ["Greek mythology painting", "Greek gods artwork", "Ancient Greek art"],
    "zeus": ["Zeus Greek god statue", "Zeus painting", "Zeus mythology"],
    "poseidon": ["Poseidon Greek god", "Poseidon statue"],
    "roman mythology": ["Roman mythology art", "Roman gods painting"],
    "egyptian mythology": ["Egyptian mythology art", "Egyptian gods painting", "Ancient Egypt art"],
    
    # World Religious Figures
    "jesus": ["Jesus Christ painting", "Jesus religious art", "Jesus icon"],
    "jesus christ": ["Jesus Christ painting", "Jesus religious art", "Jesus icon"],
    "buddha": ["Buddha statue", "Gautam Buddha painting", "Buddha meditation art"],
    "gautam buddha": ["Gautam Buddha statue", "Gautam Buddha painting", "Buddha art"],
    "mahavira": ["Mahavira Jain", "Lord Mahavira statue", "Mahavira painting"],
    "prophet muhammad": ["Islamic calligraphy", "Mosque architecture"],
    
    # Specific Topics
    "bhagavad gita": ["Bhagavad Gita book", "Bhagavad Gita painting", "Krishna Arjuna Gita"],
    "bhagavad-gita": ["Bhagavad Gita book", "Bhagavad Gita painting", "Krishna Arjuna Gita"],
    "gita": ["Bhagavad Gita book", "Bhagavad Gita painting"],
    "vedas": ["Vedas ancient text", "Vedic scriptures", "Vedic manuscripts"],
    "upanishads": ["Upanishads text", "Ancient Indian scriptures"],
    "mahabharat war": ["Mahabharata war painting", "Kurukshetra war", "Mahabharata battle"],
    "kurukshetra": ["Kurukshetra war painting", "Mahabharata battlefield"],
}

# Enhanced queries for better Pexels results on cultural topics
CULTURAL_PEXELS_QUERIES = {
    "mahabharat": "Indian epic art",
    "ramayan": "Indian mythology art",
    "krishna": "Indian deity art",
    "shiva": "Indian god art",
    "hindu": "Indian culture temple",
    "buddha": "Buddha meditation statue",
}


def is_cultural_topic(topic: str) -> Tuple[bool, List[str]]:
    """
    Detect if a topic is cultural/religious/historical/mythological.
    Returns (is_cultural, list_of_search_queries).
    """
    topic_lower = topic.lower().strip()
    
    # Check exact or partial matches against our database
    for keyword, queries in CULTURAL_KEYWORDS.items():
        if keyword in topic_lower or topic_lower in keyword:
            return True, queries
    
    # Broader detection: check for cultural/religious indicators
    cultural_indicators = [
        "god", "goddess", "lord", "deity", "mythology", "mythological",
        "epic", "scripture", "temple", "shrine", "pilgrimage",
        "ancient", "medieval", "meditation", "spiritual", "divine",
        "hindu", "hinduism", "buddhist", "buddhism", "jain", "jainism",
        "sikh", "sikhism", "islam", "muslim", "christian", "christianity",
        "religion", "religious", "faith", "worship", "prayer",
        "indian culture", "indian tradition", "indian heritage",
        "vedic", "puranic", "itihasa", "sanatan", "dharma",
        "sage", "rishi", "guru", "swami", "saint",
        "avatar", "incarnation", "reincarnation", "karma", "dharma",
        # Indian epics
        "mahabharat", "mahabharata", "ramayan", "ramayana", "bhagavad",
        "gita", "veda", "purana", "upanishad", "ramcharitmanas",
        # Indian festivals
        "diwali", "holi", "dussehra", "navratri", "janmashtami",
        "shivratri", "rakshabandhan", "ganesh chaturthi", "durga puja",
        "eid", "ramadan", "christmas", "easter",
    ]
    
    for indicator in cultural_indicators:
        if indicator in topic_lower:
            # Generate relevant queries
            enhanced_queries = [f"{topic} artwork", f"{topic} painting", topic]
            return True, enhanced_queries
    
    return False, []


def get_local_culture_images(topic: str) -> List[str]:
    """
    Check the local 'culture/' folder for relevant images.
    First tries to match by filename containing topic keywords.
    If no keyword match found, returns ALL images from the folder
    (since user may have placed relevant images with generic names).
    Returns list of image file paths.
    """
    topic_lower = topic.lower().strip()
    
    # Extract meaningful keywords from topic
    keywords = re.findall(r'\b[a-zA-Z]{3,}\b', topic_lower)
    
    matches = []
    all_images = []
    
    if os.path.exists(LOCAL_CULTURE_DIR):
        for f in sorted(os.listdir(LOCAL_CULTURE_DIR)):
            if f.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                fpath = os.path.join(LOCAL_CULTURE_DIR, f)
                all_images.append(fpath)
                f_lower = f.lower()
                # Check if filename contains any keyword
                for kw in keywords:
                    if kw in f_lower:
                        matches.append(fpath)
                        break  # Only add once per file
    
    # If keyword matches found, return those (prioritize named images)
    if matches:
        return matches
    
    # Otherwise return ALL images from culture folder
    # (user may have placed relevant images with generic names like "Screenshot...")
    return all_images


def copy_local_image_to_media(image_path: str, query: str) -> Optional[str]:
    """
    Copy a local culture image to the media directory with a proper name.
    """
    try:
        ext = os.path.splitext(image_path)[1] or '.jpg'
        safe_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')[:30]
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"local_{safe_query}_{timestamp}{ext}"
        save_path = os.path.join(CULTURAL_MEDIA_DIR, filename)
        
        import shutil
        shutil.copy2(image_path, save_path)
        print(f"  ✓ Using local culture image: {os.path.basename(image_path)} → {filename}")
        return save_path
    except Exception as e:
        print(f"  [Copy Error]: {e}")
        return None


def get_wikipedia_image(topic: str, max_results: int = 3) -> List[Dict]:
    """
    Fetch images from Wikipedia for a given topic.
    Returns list of image info dicts with url, title, description.
    """
    try:
        # Step 1: Search Wikipedia for the topic
        search_url = "https://en.wikipedia.org/w/api.php"
        search_params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": topic,
            "srlimit": 3,
            "srprop": "snippet",
        }
        
        wiki_headers = {
            "User-Agent": "J.A.R.V.I.S-AI-Assistant/1.0 (https://github.com/rajatrajdav/Local_AI-assistant; contact@jarvis.local) Python-Requests/3.0",
            "Accept": "application/json",
        }
        
        resp = requests.get(search_url, params=search_params, headers=wiki_headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        pages = data.get("query", {}).get("search", [])
        if not pages:
            # Try Hindi Wikipedia
            search_params["srwhat"] = "text"
            resp = requests.get(search_url, params=search_params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("query", {}).get("search", [])
        
        images = []
        for page in pages[:1]:  # Take first result
            page_title = page.get("title", "")
            if not page_title:
                continue
            
            # Step 2: Get images from the page
            image_params = {
                "action": "query",
                "format": "json",
                "titles": page_title,
                "prop": "images",
                "imlimit": max_results,
            }
            
            img_resp = requests.get(search_url, params=image_params, headers=wiki_headers, timeout=10)
            img_resp.raise_for_status()
            img_data = img_resp.json()
            
            pages_dict = img_data.get("query", {}).get("pages", {})
            for page_id, page_info in pages_dict.items():
                if page_id == "-1":
                    continue
                
                image_list = page_info.get("images", [])
                for img in image_list[:max_results]:
                    img_title = img.get("title", "")
                    if not img_title:
                        continue
                    
                    # Step 3: Get the actual image URL
                    url_params = {
                        "action": "query",
                        "format": "json",
                        "titles": img_title,
                        "prop": "imageinfo",
                        "iiprop": "url|extmetadata",
                        "iilimit": 1,
                    }
                    
                    url_resp = requests.get(search_url, params=url_params, headers=wiki_headers, timeout=10)
                    url_resp.raise_for_status()
                    url_data = url_resp.json()
                    
                    url_pages = url_data.get("query", {}).get("pages", {})
                    for uid, uinfo in url_pages.items():
                        if uid == "-1":
                            continue
                        image_info = uinfo.get("imageinfo", [])
                        for ii in image_info:
                            img_url = ii.get("url", "")
                            description = ii.get("extmetadata", {})\
                                .get("ImageDescription", {})\
                                .get("value", "")
                            
                            if img_url and not img_url.endswith(".svg"):
                                images.append({
                                    "url": img_url,
                                    "title": img_title.replace("File:", "").replace("_", " "),
                                    "description": description[:200] if description else topic,
                                    "source": "wikipedia",
                                    "page_title": page_title,
                                    "width": ii.get("width", 0),
                                    "height": ii.get("height", 0),
                                })
                                
                                if len(images) >= max_results:
                                    break
                    if len(images) >= max_results:
                        break
            
            if images:
                break
        
        return images
    
    except Exception as e:
        print(f"  [Wikipedia Image Error]: {e}")
        return []


def search_duckduckgo_images(query: str, max_results: int = 5) -> List[Dict]:
    """
    Search DuckDuckGo for images related to the query.
    Uses HTML scraping (DuckDuckGo has no official image API).
    Returns list of image info dicts.
    """
    try:
        # Try DuckDuckGo instant answer API first (more reliable)
        ddg_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        resp = requests.get(ddg_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        images = []
        
        # Check for image from the instant answer
        image_url = data.get("Image", "")
        if image_url and not image_url.endswith(".svg"):
            images.append({
                "url": f"https://duckduckgo.com{image_url}" if image_url.startswith("/") else image_url,
                "title": data.get("Heading", query),
                "description": data.get("Abstract", query)[:200],
                "source": "duckduckgo",
            })
        
        # Check related topics
        related = data.get("RelatedTopics", [])
        for topic_data in related[:3]:
            if isinstance(topic_data, dict):
                topic_icon = topic_data.get("Icon", {})
                icon_url = topic_icon.get("URL", "")
                if icon_url:
                    images.append({
                        "url": f"https://duckduckgo.com{icon_url}" if icon_url.startswith("/") else icon_url,
                        "title": topic_data.get("Text", query)[:100],
                        "description": topic_data.get("Text", query)[:200],
                        "source": "duckduckgo",
                    })
        
        return images[:max_results]
    
    except Exception as e:
        print(f"  [DuckDuckGo Image Error]: {e}")
        return []


def download_cultural_image(image_url: str, query: str, index: int = 0) -> Optional[str]:
    """
    Download an image from URL and save locally.
    Returns file path or None on failure.
    """
    try:
        # Create a safe filename
        safe_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')[:30]
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%H%M%S")
        
        # Get extension from URL
        parsed = urlparse(image_url)
        _, ext = os.path.splitext(parsed.path)
        if not ext or ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
            ext = '.jpg'
        
        filename = f"{safe_query}_{url_hash}_{timestamp}{ext}"
        save_path = os.path.join(CULTURAL_MEDIA_DIR, filename)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        resp = requests.get(image_url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        
        # Check content type
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            # Try to fix extension
            pass
        
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Verify file is not empty
        if os.path.getsize(save_path) > 1024:  # At least 1KB
            print(f"  ✓ Downloaded cultural image: {query} → {filename}")
            return save_path
        
        os.remove(save_path)
        return None
    
    except Exception as e:
        print(f"  [Download Error]: {e}")
        return None


def search_cultural_image(query: str, slide_number: int = 0, count: int = 3) -> Optional[str]:
    """
    Main function to search for culturally relevant images.
    Strategy:
    1. Check cache first
    2. Try Wikipedia images (web sources FIRST)
    3. Try DuckDuckGo images
    4. Fall back to enhanced Pexels query
    5. ALSO use local culture/ folder images as supplements
    
    FIX: Uses slide_number to select a DIFFERENT image for each slide,
    ensuring visual variety throughout the presentation.
    
    Returns path to downloaded image or None.
    """
    is_cultural, cultural_queries = is_cultural_topic(query)
    
    if not is_cultural:
        return None
    
    print(f"  🏛️  Cultural topic detected: '{query}' — searching for authentic images...")
    
    # STEP 1: Check cache (include slide_number in cache key for variety)
    cache_key = f"{query.lower().strip()}_{count}_{slide_number}"
    if cache_key in _image_cache:
        cached_path = _image_cache[cache_key]
        if os.path.exists(cached_path):
            print(f"  ✓ Using cached image for '{query}' (slide {slide_number})")
            return cached_path
    
    # STEP 2: Try each cultural query on WEB SOURCES FIRST
    web_images_found = []
    for cq in cultural_queries:
        if cq:
            # 2a. Try Wikipedia (most authoritative for cultural topics)
            wiki_images = get_wikipedia_image(cq, max_results=2)
            for img in wiki_images:
                saved = download_cultural_image(img["url"], cq, slide_number)
                if saved:
                    web_images_found.append(saved)
            
            # 2b. Try DuckDuckGo
            ddg_images = search_duckduckgo_images(cq, max_results=3)
            for img in ddg_images:
                saved = download_cultural_image(img["url"], cq, slide_number)
                if saved:
                    web_images_found.append(saved)
            
            # Brief pause between attempts
            time.sleep(0.5)
    
    # 2c. Try original query on Wikipedia
    wiki_images = get_wikipedia_image(query, max_results=3)
    for img in wiki_images:
        saved = download_cultural_image(img["url"], query, slide_number)
        if saved:
            web_images_found.append(saved)
    
    # STEP 3: ALSO use local culture/ folder images alongside web images
    local_images = get_local_culture_images(query)
    for cq in cultural_queries:
        if cq:
            cq_images = get_local_culture_images(cq)
            local_images.extend(cq_images)
    
    # Copy local images as supplements
    local_copied = []
    for local_path in local_images:
        copied = copy_local_image_to_media(local_path, query)
        if copied and os.path.exists(copied):
            local_copied.append(copied)
    
    # STEP 4: Return a different image based on slide_number for variety
    all_images = web_images_found + local_copied
    
    if all_images:
        # Use slide_number to pick a different image for each slide
        # This ensures variety even when the same query is used
        image_index = slide_number % len(all_images)
        best = all_images[image_index]
        # Cache the result with slide_number in key
        if cache_key not in _image_cache:
            _image_cache[cache_key] = best
            try:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(_image_cache, f)
            except Exception:
                pass
        return best
    
    print(f"  ⚠ Could not find cultural image for '{query}' via alternative sources")
    return None


def get_enhanced_pexels_query(topic: str) -> Optional[str]:
    """
    Get an enhanced Pexels search query for cultural topics.
    This helps Pexels return more thematically relevant images.
    """
    topic_lower = topic.lower().strip()
    
    # Check exact matches
    for keyword, enhanced_query in CULTURAL_PEXELS_QUERIES.items():
        if keyword in topic_lower:
            return enhanced_query
    
    # If cultural but no specific enhancement, return general cultural query
    is_cultural, _ = is_cultural_topic(topic)
    if is_cultural:
        return f"Indian culture {topic[:20]}"
    
    return None


# ── Modified version of download_background_image that prefers cultural sources ──

def get_best_image_for_topic(topic: str, slide_number: int = 0) -> Optional[str]:
    """
    Get the best image for any topic - prefers cultural sources for
    cultural/religious/historical topics, falls back to Pexels for general topics.
    """
    # 1. First check if it's a cultural topic
    cultural_image = search_cultural_image(topic, slide_number)
    if cultural_image and os.path.exists(cultural_image):
        return cultural_image
    
    # 2. For cultural topics, also try the enhanced query on all available sources
    enhanced_query = get_enhanced_pexels_query(topic)
    if enhanced_query:
        # Search with enhanced query on DuckDuckGo
        ddg_images = search_duckduckgo_images(enhanced_query, max_results=3)
        for img in ddg_images:
            saved = download_cultural_image(img["url"], enhanced_query, slide_number)
            if saved:
                return saved
    
    return None


# ── Test / Debug ──────────────────────────────────────────────

def test_cultural_search():
    """Test the cultural image search with various topics."""
    test_topics = [
        "Mahabharat",
        "Lord Krishna", 
        "Ramayana",
        "Shiva",
        "Artificial Intelligence",
        "Buddha",
        "Bhagavad Gita",
    ]
    
    print("Testing Cultural Image Search\n")
    print("=" * 60)
    
    for topic in test_topics:
        print(f"\n📌 Topic: '{topic}'")
        is_cultural, queries = is_cultural_topic(topic)
        print(f"   Cultural: {is_cultural}")
        if is_cultural:
            print(f"   Queries: {queries[:3]}")
            
            # Try to find image
            result = search_cultural_image(topic)
            if result:
                print(f"   ✅ Image found: {os.path.basename(result)}")
            else:
                print(f"   ❌ No image found")
    
    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    test_cultural_search()