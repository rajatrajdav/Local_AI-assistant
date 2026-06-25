import os
import asyncio
import json
import time
import re
import numpy as np
import sounddevice as sd
from piper import PiperVoice
from dotenv import load_dotenv

# ============================================================
# Load environment variables from .env (API keys, secrets)
# NEVER hardcode API keys — they stay in .env which is gitignored
# ============================================================
load_dotenv()

# ============================================================
# Console-mode UI stubs (ui_jarvis.py removed)
# These no-op functions allow jarvis.py to run in pure console mode
# without requiring the GUI/UI module.
# ============================================================
def _ui_update(**kwargs):
    pass

def _ui_message(msg):
    pass

def _ui_notification(title, msg_type="info"):
    pass

# ============================================================
# FIX #1 — HINDI TEXT NORMALIZER UTILITY
# Cleans and normalizes Hindi text before passing to TTS engine
# to prevent mispronunciation and garbled audio output.
# ============================================================

def normalize_hindi_text(text: str) -> str:
    """
    Normalize Hindi (Devanagari) text for clean TTS pronunciation.
    Removes emojis, strips English mixed noise, normalizes punctuation.
    """
    # Remove emojis and unicode symbols that confuse TTS
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002500-\U00002BEF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)

    # Replace English punctuation with Hindi-friendly equivalents
    text = text.replace(".", "।")
    text = text.replace("!", "।")
    text = text.replace("?", "?")     # Keep ? — Piper handles it
    text = text.replace(",", ",")

    # Remove markdown symbols
    text = re.sub(r"[*_`#\[\]()]", "", text)

    # Collapse multiple spaces/newlines
    text = re.sub(r"\s+", " ", text).strip()

    # Remove any remaining non-Devanagari / non-punctuation characters
    # that may cause the TTS engine to stumble
    cleaned = ""
    for char in text:
        cp = ord(char)
        # Allow: Devanagari (0900–097F), spaces, common punctuation
        if (0x0900 <= cp <= 0x097F) or char in " ,।?-\n":
            cleaned += char
        elif char.isascii() and char.isprintable():
            # Keep ASCII letters/digits (mixed code is common in Indian speech)
            cleaned += char
    return cleaned.strip()


def normalize_english_text(text: str) -> str:
    """
    Light normalization for English TTS — removes markdown, emojis.
    """
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002500-\U00002BEF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)
    text = re.sub(r"[*_`#]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ============================================================
# Groq API integration for ultra-fast LLM responses
# ============================================================
try:
    from groq import Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    if not GROQ_API_KEY:
        print("⚠ GROQ_API_KEY not found in .env file")
        print("   Create a .env file with: GROQ_API_KEY=your_key_here")
        USE_GROQ = False
    else:
        groq_client = Groq(api_key=GROQ_API_KEY)
        USE_GROQ = True
        print("✓ Groq API connected - Ultra-fast mode enabled!")
except Exception as e:
    print(f"⚠ Groq API connection failed: {e}")
    USE_GROQ = False

# ============================================================
# Gemini API integration (Google AI Studio)
# ============================================================
try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        print("⚠ GEMINI_API_KEY not found in .env or hardcoded fallback")
        USE_GEMINI = False
    else:
        genai.configure(api_key=GEMINI_API_KEY)
        # Use standard Gemini model name; can be overridden via GEMINI_MODEL env var
        GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        USE_GEMINI = True
        print(f"✓ Gemini API connected ({GEMINI_MODEL_NAME})")
except Exception as e:
    print(f"⚠ Gemini API connection failed: {e}")
    USE_GEMINI = False

# ============================================================
# GENERATIVE AI TOOLS & CAPABILITIES
# ============================================================

import subprocess
from datetime import datetime
from docx import Document
from docx.shared import Pt, Inches
from pptx import Presentation
from pptx.util import Inches as PptxInches, Pt as PptxPt
import pyperclip
import psutil

# ============================================================
# PROFESSIONAL PRESENTATION ENGINE (v4.0) — 4-Step Design
# ============================================================
try:
    from professional_presentation import (
        create_professional_presentation,
        PROFESSIONAL_PRESENTATION_SYSTEM_PROMPT,
        auto_select_background,
        PROFESSIONAL_BACKGROUNDS,
    )
    PROFESSIONAL_MODE_AVAILABLE = True
    print("✓ Professional Presentation Engine v4.0 loaded (4-Step Design Process)")
except ImportError as e:
    print(f"  ⚠ Professional Presentation Engine not available: {e}")
    PROFESSIONAL_MODE_AVAILABLE = False
    PROFESSIONAL_PRESENTATION_SYSTEM_PROMPT = ""
    def auto_select_background(topic): return None
    PROFESSIONAL_BACKGROUNDS = {}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_files")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# FIX #3 — PROFESSIONAL PROMPT BUILDER
# Upgrades content generation to produce deeply structured,
# comprehensive, and professionally worded output.
# ============================================================

PROFESSIONAL_CONTENT_SYSTEM_PROMPT = """
You are an expert content writer and presentation specialist.
When generating content for documents or presentations, follow these rules strictly:

CONTENT QUALITY RULES:
1. Each bullet point must be a COMPLETE, INFORMATIVE sentence (minimum 15 words).
2. Use professional, authoritative language — no vague filler phrases.
3. Provide specific facts, statistics, or examples wherever possible.
4. Structure content logically: define → explain → imply → conclude.
5. For presentations: every slide must have 4-6 substantial bullet points.
6. For documents: write in full paragraphs (5-8 sentences each section).
7. Avoid one-word bullets like "Overview" or "Introduction" — always expand.
8. Use domain-specific vocabulary appropriate to the topic.
9. When generating slide content, think like a subject-matter expert giving a keynote.
10. Always generate AT LEAST 10 content slides for presentations.

SLIDE STRUCTURE TEMPLATE (follow this for every slide):
- Opening statement that defines the concept clearly
- 2-3 explanatory points with real-world context
- 1 example or case study reference
- 1 implication or takeaway point

OUTPUT FORMAT: Always respond with valid JSON only. No text outside JSON.
"""


def create_word_document(title, content, filename=None, show_live=True):
    """Create a Word document with the given title and content."""
    if filename is None:
        filename = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    if not filename.endswith(".docx"):
        filename += ".docx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    if show_live:
        try:
            import win32com.client as win32
            word = win32.Dispatch("Word.Application")
            word.Visible = True
            doc = word.Documents.Add()
            selection = word.Selection

            # Title
            selection.Font.Size = 18
            selection.Font.Bold = True
            selection.ParagraphFormat.Alignment = 1
            selection.TypeText(title)
            selection.TypeParagraph()
            selection.TypeParagraph()

            # Reset to body style
            selection.Font.Size = 12
            selection.Font.Bold = False
            selection.ParagraphFormat.Alignment = 0

            paragraphs = content.split("\n") if "\n" in content else [content]
            for para in paragraphs:
                if para.strip():
                    selection.TypeText(para.strip())
                    selection.TypeParagraph()
                    selection.TypeParagraph()  # Extra spacing between paragraphs

            doc.SaveAs2(filepath)
            word.Activate()

            # FIX #2 — Auto open document after creation
            os.startfile(filepath)
            return filepath

        except ImportError:
            print("[Info] pywin32 not installed, falling back to silent creation")
        except Exception as e:
            print(f"[Warning] Live creation failed: {e}, falling back to silent creation")

    # Silent fallback
    doc = Document()
    doc.add_heading(title, 0)
    if isinstance(content, list):
        for para in content:
            doc.add_paragraph(para)
    else:
        for para in content.split("\n"):
            if para.strip():
                doc.add_paragraph(para.strip())
    doc.save(filepath)

    # FIX #2 — Auto open even in silent mode
    try:
        os.startfile(filepath)
    except Exception as e:
        print(f"[Auto-open Warning]: {e}")

    return filepath


def download_image_from_pexels(query, save_path, slide_number=0):
    """Download a relevant image from Pexels based on query."""
    try:
        from pexels_integration import (
            download_background_image,
            get_color_palette_from_image,
        )
        downloaded_path = download_background_image(query, slide_number)
        if downloaded_path:
            import shutil
            shutil.copy2(downloaded_path, save_path)
            palette = get_color_palette_from_image(save_path)
            return {"path": save_path, "palette": palette, "query": query}
        return None
    except Exception as e:
        print(f"[Pexels Image Download Error]: {e}")
        return None


def create_presentation(title, slides_content, filename=None, show_live=True,
                        include_images=True, creative_mode=True):
    """
    Create a PowerPoint presentation.
    FIX #2: Auto-opens PowerPoint after generation.
    FIX #3: Uses professional content standards.
    """
    if creative_mode:
        try:
            from creative_presentation import create_creative_presentation
            print("\n  🎨 Using Creative Presentation Mode with Pexels backgrounds...")
            filepath = create_creative_presentation(title, slides_content, filename, show_progress=True)

            # FIX #2 — Auto-open PowerPoint immediately after generation
            _auto_open_file(filepath)
            return filepath
        except Exception as e:
            print(f"  ⚠ Creative mode failed: {e}, falling back to standard mode")

    if filename is None:
        filename = f"presentation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
    if not filename.endswith(".pptx"):
        filename += ".pptx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    if show_live:
        try:
            import win32com.client as win32
            import pythoncom

            pythoncom.CoInitialize()
            print("\n  🎨 Opening PowerPoint for creative design...")
            ppt = win32.Dispatch("PowerPoint.Application")
            ppt.Visible = True
            ppt.WindowState = 1
            ppt.Activate()
            time.sleep(2)

            prs = ppt.Presentations.Add()
            prs.Windows(1).WindowState = 1

            print(f"\n  📝 Creating presentation: {title}")
            print(f"  📊 Total slides to create: {len(slides_content) + 1}")

            # Set to widescreen (13.333 x 7.5 inches)
            prs.PageSetup.SlideWidth = 13.333 * 72
            prs.PageSetup.SlideHeight = 7.5 * 72

            colors = [
                0x1A3A5C, 0x0D5E40, 0x6B1A1A, 0x2D1B5E,
                0x8B4500, 0x005858, 0x58005E, 0x1C3A1C,
                0x8B2222, 0x1B4B3A,
            ]

            # Title slide
            title_slide = prs.Slides.Add(1, 1)
            ppt.ActiveWindow.View.GotoSlide(1)
            title_shape = title_slide.Shapes(1).TextFrame.TextRange
            title_shape.Text = title
            title_shape.Font.Size = 54
            title_shape.Font.Bold = True
            title_shape.Font.Color.RGB = 0x1A3A5C
            title_shape.Font.Shadow = True

            subtitle_shape = title_slide.Shapes(2).TextFrame.TextRange
            subtitle_shape.Text = (
                f"A Comprehensive Professional Overview\n"
                f"Prepared by AI Assistant | {datetime.now().strftime('%B %Y')}"
            )
            subtitle_shape.Font.Size = 24
            subtitle_shape.Font.Italic = True
            time.sleep(1.5)

            for i, slide_data in enumerate(slides_content, 2):
                slide_title = slide_data.get("title", "Untitled")
                print(f"\n     🎨 Designing Slide {i - 1}: {slide_title}")

                layout = 2
                slide = prs.Slides.Add(i, layout)
                ppt.ActiveWindow.View.GotoSlide(i)
                time.sleep(0.8)

                title_text = slide.Shapes(1).TextFrame.TextRange
                title_text.Text = slide_title
                title_text.Font.Size = 36
                title_text.Font.Bold = True
                color_idx = (i - 2) % len(colors)
                title_text.Font.Color.RGB = colors[color_idx]
                title_text.Font.Shadow = True

                has_image = False
                img_path = None
                if include_images and "image_query" in slide_data:
                    try:
                        temp_path = os.path.join(OUTPUT_DIR, f"slide_{i}_image.jpg")
                        result = download_image_from_pexels(slide_data["image_query"], temp_path, i)
                        if result and os.path.exists(result["path"]):
                            has_image = True
                            img_path = result["path"]
                    except Exception as e:
                        print(f"        ⚠ Image skipped: {e}")

                if "content" in slide_data and len(slide.Shapes) > 1:
                    text_shape = slide.Shapes(2)
                    # Force strict word wrap to respect bounding box
                    text_shape.TextFrame.WordWrap = -1  # msoTrue

                    if has_image:
                        # Multi-column math: text on left, image on right
                        # Left col: 0.5" to 6.5" (Width: 6" = 432 pts)
                        text_shape.Left = 36
                        text_shape.Width = 432
                    else:
                        # Full width text
                        text_shape.Left = 36
                        text_shape.Width = 888

                    content_text = text_shape.TextFrame.TextRange
                    content_text.Text = slide_data["content"]
                    content_text.Font.Size = 18
                    content_text.ParagraphFormat.SpaceAfter = 14
                    content_text.ParagraphFormat.SpaceBefore = 4
                    try:
                        content_text.ParagraphFormat.Bullet.Visible = True
                    except Exception:
                        pass
                    time.sleep(1)

                if has_image:
                    try:
                        # Image strictly on the right half (Left: 6.8" = 490 pts, Width: 6" = 432 pts)
                        slide.Shapes.AddPicture(
                            img_path,
                            LinkToFile=False,
                            SaveWithDocument=True,
                            Left=490, Top=130, Width=432, Height=380,
                        )
                    except Exception as e:
                        print(f"        ⚠ Image layout failed: {e}")

                time.sleep(0.8)

            prs.SaveAs(filepath)
            print(f"\n  ✅ Presentation complete! {len(slides_content) + 1} slides created.")
            ppt.ActiveWindow.View.GotoSlide(1)
            ppt.Activate()
            ppt.WindowState = 1
            pythoncom.CoUninitialize()

            # FIX #2 — Auto-open PowerPoint instantly
            _auto_open_file(filepath)
            return filepath

        except ImportError:
            print("[Info] pywin32 not installed, falling back to silent creation")
        except Exception as e:
            print(f"[Warning] Live creation failed: {e}")
            import traceback
            traceback.print_exc()

    # Silent fallback
    prs = Presentation()
    prs.slide_width = PptxInches(13.333)
    prs.slide_height = PptxInches(7.5)

    slide_layout = prs.slide_layouts[6] # Blank
    slide = prs.slides.add_slide(slide_layout)
    
    # Title
    tbox = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(2.5), PptxInches(12.333), PptxInches(2.0))
    tf = tbox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = PptxPt(44)
    p.font.bold = True
    
    # Subtitle
    sbox = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(4.5), PptxInches(12.333), PptxInches(1.0))
    stf = sbox.text_frame
    stf.word_wrap = True
    sp = stf.paragraphs[0]
    sp.text = "A Comprehensive Professional Overview\n" + datetime.now().strftime("%B %Y")
    sp.font.size = PptxPt(24)

    for i, slide_data in enumerate(slides_content):
        slide = prs.slides.add_slide(prs.slide_layouts[6]) # Blank
        
        # Add title
        tb = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(0.5), PptxInches(12.333), PptxInches(1.0))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = slide_data.get("title", "")
        p.font.size = PptxPt(36)
        p.font.bold = True
        
        has_image = False
        img_path = None
        if include_images and "image_query" in slide_data:
            try:
                temp_path = os.path.join(OUTPUT_DIR, f"slide_fallback_{i}_image.jpg")
                result = download_image_from_pexels(slide_data["image_query"], temp_path, i)
                if result and os.path.exists(result["path"]):
                    has_image = True
                    img_path = result["path"]
            except Exception:
                pass

        if has_image:
            # Multi-column math: Text on left, Image on right
            content_box = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(1.6), PptxInches(6.0), PptxInches(5.5))
            ctf = content_box.text_frame
            ctf.word_wrap = True
            if "content" in slide_data:
                ctf.text = slide_data["content"]
            
            # Image container
            slide.shapes.add_picture(img_path, PptxInches(6.8), PptxInches(1.6), width=PptxInches(6.0))
        else:
            # Full width
            content_box = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(1.6), PptxInches(12.0), PptxInches(5.5))
            ctf = content_box.text_frame
            ctf.word_wrap = True
            if "content" in slide_data:
                ctf.text = slide_data["content"]

    prs.save(filepath)

    # FIX #2 — Auto-open even in silent mode
    _auto_open_file(filepath)
    return filepath


def _auto_open_file(filepath: str):
    """
    FIX #2 — Cross-platform auto-open for generated files.
    Opens the file immediately using the OS default application.
    """
    try:
        if os.name == "nt":  # Windows
            os.startfile(filepath)
        elif os.uname().sysname == "Darwin":  # macOS
            subprocess.Popen(["open", filepath])
        else:  # Linux
            subprocess.Popen(["xdg-open", filepath])
        print(f"  🚀 Auto-opened: {os.path.basename(filepath)}")
    except Exception as e:
        print(f"  [Auto-open failed]: {e} — Please open manually: {filepath}")


def create_resume(name, contact_info, experience, education, skills,
                  filename=None, show_live=True):
    """Create a professional resume."""
    if filename is None:
        filename = f"resume_{name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    if not filename.endswith(".docx"):
        filename += ".docx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    if show_live:
        try:
            import win32com.client as win32
            word = win32.Dispatch("Word.Application")
            word.Visible = True
            doc = word.Documents.Add()
            selection = word.Selection

            selection.Font.Size = 20
            selection.Font.Bold = True
            selection.ParagraphFormat.Alignment = 1
            selection.TypeText(name)
            selection.TypeParagraph()

            selection.Font.Size = 11
            selection.Font.Bold = False
            selection.TypeText(contact_info)
            selection.TypeParagraph()
            selection.TypeParagraph()

            if experience:
                selection.Font.Size = 14
                selection.Font.Bold = True
                selection.ParagraphFormat.Alignment = 0
                selection.TypeText("PROFESSIONAL EXPERIENCE")
                selection.TypeParagraph()
                selection.Font.Size = 12
                selection.Font.Bold = False
                for exp in experience:
                    selection.Font.Bold = True
                    selection.TypeText(exp.get("title", ""))
                    selection.Font.Bold = False
                    selection.TypeText(f" — {exp.get('company', '')}")
                    if exp.get("duration"):
                        selection.TypeText(f"  |  {exp.get('duration', '')}")
                    selection.TypeParagraph()
                    if exp.get("description"):
                        selection.TypeText(exp["description"])
                        selection.TypeParagraph()
                    selection.TypeParagraph()

            if education:
                selection.Font.Size = 14
                selection.Font.Bold = True
                selection.TypeText("EDUCATION")
                selection.TypeParagraph()
                selection.Font.Size = 12
                selection.Font.Bold = False
                for edu in education:
                    selection.Font.Bold = True
                    selection.TypeText(edu.get("degree", ""))
                    selection.Font.Bold = False
                    selection.TypeText(f" — {edu.get('institution', '')}")
                    if edu.get("year"):
                        selection.TypeText(f"  ({edu.get('year', '')})")
                    selection.TypeParagraph()
                selection.TypeParagraph()

            if skills:
                selection.Font.Size = 14
                selection.Font.Bold = True
                selection.TypeText("CORE SKILLS")
                selection.TypeParagraph()
                selection.Font.Size = 12
                selection.Font.Bold = False
                selection.TypeText(" • ".join(skills))

            doc.SaveAs2(filepath)
            word.Activate()
            _auto_open_file(filepath)
            return filepath

        except ImportError:
            print("[Info] pywin32 not installed, falling back to silent creation")
        except Exception as e:
            print(f"[Warning] Live creation failed: {e}")

    # Silent fallback
    doc = Document()
    doc.add_heading(name, 0)
    doc.add_paragraph(contact_info)
    if experience:
        doc.add_heading("Professional Experience", level=1)
        for exp in experience:
            p = doc.add_paragraph()
            p.add_run(exp.get("title", "")).bold = True
            p.add_run(f" — {exp.get('company', '')}")
            if exp.get("duration"):
                p.add_run(f"  |  {exp.get('duration', '')}")
            if exp.get("description"):
                doc.add_paragraph(exp["description"])
    if education:
        doc.add_heading("Education", level=1)
        for edu in education:
            p = doc.add_paragraph()
            p.add_run(edu.get("degree", "")).bold = True
            p.add_run(f" — {edu.get('institution', '')}")
            if edu.get("year"):
                p.add_run(f"  ({edu.get('year', '')})")
    if skills:
        doc.add_heading("Core Skills", level=1)
        doc.add_paragraph(" • ".join(skills))
    doc.save(filepath)
    _auto_open_file(filepath)
    return filepath


def open_application(app_name):
    """Open an application by name."""
    try:
        app_map = {
            "chrome": "chrome", "browser": "chrome",
            "word": "winword", "excel": "excel",
            "powerpoint": "powerpnt", "ppt": "powerpnt",
            "notepad": "notepad", "calculator": "calc",
            "paint": "mspaint", "explorer": "explorer",
        }
        key = next((k for k in app_map if k in app_name.lower()), None)
        target = app_map[key] if key else app_name
        os.startfile(target)
        return f"Opened {app_name}"
    except Exception as e:
        return f"Failed to open {app_name}: {str(e)}"


def get_system_info():
    """Get current system information."""
    info = {
        "cpu_usage": f"{psutil.cpu_percent(interval=1)}%",
        "memory": f"{psutil.virtual_memory().percent}%",
        "disk_usage": f"{psutil.disk_usage('/').percent}%",
        "battery": None,
    }
    battery = psutil.sensors_battery()
    if battery:
        info["battery"] = f"{battery.percent}%"
    return info


def write_to_clipboard(text):
    pyperclip.copy(text)
    return "Text copied to clipboard"


def read_clipboard():
    return pyperclip.paste()


def list_files(directory=None):
    if directory is None:
        directory = os.path.expanduser("~\\Desktop")
    try:
        files = os.listdir(directory)
        return {"directory": directory, "files": files[:20]}
    except Exception as e:
        return {"error": str(e)}


def create_file(filename, content, folder="generated_files"):
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


# ============================================================
# AVAILABLE TOOLS DEFINITION
# ============================================================

AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_word_document",
            "description": "Create a detailed, professional Word document with title and comprehensive content",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title"},
                    "content": {"type": "string", "description": "Full document content — must be detailed, multi-paragraph, professional"},
                    "filename": {"type": "string", "description": "Optional filename ending in .docx"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_presentation",
            "description": "Create a professional PowerPoint presentation with at least 10 slides, each with detailed content and images",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Presentation title"},
                    "slides_content": {
                        "type": "string",
                        "description": (
                            "JSON array of slide objects. Each object must have: "
                            "title (string), content (4-6 detailed bullet points separated by \\n), "
                            "image_query (search term for background image). "
                            "Minimum 10 slides required."
                        ),
                    },
                    "filename": {"type": "string", "description": "Optional filename ending in .pptx"},
                },
                "required": ["title", "slides_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_resume",
            "description": "Create a professional resume document",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "contact_info": {"type": "string"},
                    "experience": {"type": "string", "description": "JSON array of experience objects"},
                    "education": {"type": "string", "description": "JSON array of education objects"},
                    "skills": {"type": "string", "description": "JSON array of skills"},
                },
                "required": ["name", "contact_info"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open an application on the computer",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get current system information (CPU, memory, battery)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_to_clipboard",
            "description": "Write text to clipboard",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a text file with content",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
            },
        },
    },
]

FUNCTION_MAP = {
    "create_word_document": create_word_document,
    "create_presentation": create_presentation,
    "create_resume": create_resume,
    "open_application": open_application,
    "get_system_info": get_system_info,
    "write_to_clipboard": write_to_clipboard,
    "create_file": create_file,
}


def execute_function(name, arguments):
    """Execute a function with the given arguments."""
    if name not in FUNCTION_MAP:
        return f"Unknown function: {name}"
    try:
        func = FUNCTION_MAP[name]
        parsed_args = {}
        for key, value in arguments.items():
            if isinstance(value, str) and value.strip().startswith(("[", "{")):
                try:
                    parsed_args[key] = json.loads(value)
                except Exception:
                    parsed_args[key] = value
            else:
                parsed_args[key] = value
        result = func(**parsed_args)
        return f"Success: {result}"
    except Exception as e:
        return f"Error executing {name}: {str(e)}"


# ============================================================
# SPEECH RECOGNITION (voice input via sounddevice)
# Uses sounddevice as microphone backend instead of PyAudio
# ============================================================
import threading
import queue
import wave
import tempfile

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
    print("✓ SpeechRecognition loaded — voice input enabled!")
except ImportError:
    SR_AVAILABLE = False
    print("  ⚠ SpeechRecognition not installed — voice input disabled")

# ── Custom Microphone class using sounddevice (no PyAudio needed) ──
class SoundDeviceMicrophone(sr.AudioSource):
    """A microphone class for SpeechRecognition that uses sounddevice instead of PyAudio."""
    
    def __init__(self, sample_rate=16000, channels=1, device=None, timeout=5):
        self.SAMPLE_RATE = sample_rate
        self.SAMPLE_WIDTH = 2  # 16-bit audio = 2 bytes per sample
        self.CHANNELS = channels
        self.device = device
        self.CHUNK = 1024
        self.timeout = timeout
        self.audio_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.recording_thread = None

    def __enter__(self):
        self._sd_stream = sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            device=self.device,
            dtype='int16',
            blocksize=self.CHUNK,
        )
        self._sd_stream.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._sd_stream.__exit__(exc_type, exc_val, exc_tb)

    @property
    def stream(self):
        """SpeechRecognition calls source.stream.read() — return self so our read() is used."""
        return self

    def read(self, size):
        """Read audio data from the stream. Size is in bytes — convert to frames for sounddevice."""
        frames_needed = max(1, size // (self.SAMPLE_WIDTH * self.CHANNELS))
        frames, _ = self._sd_stream.read(frames_needed)
        return frames.tobytes()


def listen_once(timeout=8, phrase_time_limit=15):
    """
    Capture voice input from the microphone once.
    Returns transcribed text string, or None on failure/timeout.
    Uses sounddevice as the backend (no PyAudio dependency).

    FIX: Reduced thresholds for responsive, event-driven listening:
    - pause_threshold=0.6: ends speech after 0.6s of silence (not 3s)
    - non_speaking_duration=0.3: short non-speaking grace period
    - timeout=8: wait max 8s for user to start speaking (not 20s)
    - phrase_time_limit=15: max 15s per utterance (not unlimited)
    """
    if not SR_AVAILABLE:
        print("  ⚠ SpeechRecognition not available. Please type your input.")
        return None

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 800    # Lower = more sensitive
    recognizer.dynamic_energy_threshold = True
    recognizer.dynamic_energy_adjustment_damping = 0.10  # Faster adaptation
    recognizer.dynamic_energy_ratio = 1.2
    recognizer.pause_threshold = 0.6     # End speech after 0.6s silence (was 3.0)
    recognizer.non_speaking_duration = 0.3  # Short grace period (was 1.5)

    try:
        with SoundDeviceMicrophone(sample_rate=16000) as source:
            print("\n  🎤 [Listening... Speak now]")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # Ensure threshold isn't set too high after calibration
            if recognizer.energy_threshold > 4000:
                recognizer.energy_threshold = 2000
            
            try:
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit
                )
            except sr.WaitTimeoutError:
                print("  ⏰ [Listening timeout — no speech detected]")
                return None

        print("  🧠 [Transcribing...]")
        # Try Google Web Speech API first (free, no key needed)
        try:
            text = recognizer.recognize_google(audio, language="en-IN,hi-IN")
            print(f"  📝 [You said]: {text}")
            return text
        except sr.UnknownValueError:
            print("  ❌ [Could not understand audio]")
            return None
        except sr.RequestError as e:
            print(f"  ⚠ [Speech recognition service error]: {e}")
            return None

    except Exception as e:
        print(f"  ⚠ [Microphone error]: {e}")
        return None


def listen_with_visualizer(timeout=20, phrase_time_limit=None, use_visual=True):
    """
    Captures voice with a simple progress indicator.
    Returns (text, language) tuple.
    """
    text = listen_once(timeout=timeout, phrase_time_limit=phrase_time_limit)
    if text:
        lang = detect_lang(text)
        return text, lang
    return None, None

# ============================================================
# VOICE PATH CONFIGURATIONS (PIPER LOCAL)
# ============================================================
VOICES = {
    "en_male": {
        "model": os.path.join("voices", "english", "en_US-hfc_male-medium.onnx"),
        "config": os.path.join("voices", "english", "en_US-hfc_male-medium.onnx.json"),
        "name": "English Male (Medium)",
        "language": "en",
    },
    "en_female": {
        "model": os.path.join("voices", "english", "en_US-libritts_r-medium.onnx"),
        "config": os.path.join("voices", "english", "en_US-libritts_r-medium.onnx.json"),
        "name": "English Female (LibriTTS)",
        "language": "en",
    },
    "hi_male": {
        # FIX #1 — Explicitly uses hi_IN locale for correct Hindi pronunciation
        "model": os.path.join("voices", "hindi", "hi_IN-pratham-medium.onnx"),
        "config": os.path.join("voices", "hindi", "hi_IN-pratham-medium.onnx.json"),
        "name": "Hindi Male (Pratham — hi_IN)",
        "language": "hi",
    },
}

print("Loading local Piper engines... Please wait.")
voice_engines = {}
for key, voice_info in VOICES.items():
    try:
        voice_engines[key] = PiperVoice.load(
            voice_info["model"], config_path=voice_info["config"]
        )
        print(f"  ✓ Loaded: {voice_info['name']}")
    except Exception as e:
        print(f"  ✗ Failed to load: {voice_info['name']} — {e}")

if not voice_engines:
    print("ERROR: No voice engines loaded. Exiting.")
    exit(1)

print("All available voice engines loaded successfully!\n")


# ============================================================
# AUDIO PLAYBACK FUNCTIONS
# ============================================================

def play_piper_tts(text, engine_key):
    """
    FIX #1 — Local Piper TTS with normalization pre-pass.
    Hindi text is cleaned before synthesis to prevent mispronunciation.
    English text receives light normalization.
    """
    if engine_key not in voice_engines:
        print(f"[Error] Voice engine '{engine_key}' not found.")
        return

    selected_voice = voice_engines[engine_key]
    voice_lang = VOICES[engine_key]["language"]

    # Apply language-specific normalization
    if voice_lang == "hi":
        text = normalize_hindi_text(text)
    else:
        text = normalize_english_text(text)

    if not text.strip():
        print("[TTS] Empty text after normalization, skipping audio.")
        return

    try:
        with sd.OutputStream(
            samplerate=selected_voice.config.sample_rate,
            channels=1,
            dtype="int16",
        ) as stream:
            for chunk in selected_voice.synthesize(text):
                audio_data = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
                stream.write(audio_data)
    except Exception as e:
        print(f"[Local Piper Audio Error]: {e}")


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_lang(text):
    """Detect if text contains Hindi characters (Devanagari script)."""
    for char in text:
        if 0x0900 <= ord(char) <= 0x097F:
            return "hi"
    return "en"


# ============================================================
# PERSONALITY SYSTEM
# ============================================================

PERSONALITIES = {
    "en_female": {
        "name": "Simmi",
        "description": "Simmi — warm, friendly, cheerful female AI assistant",
        "system_prompt": (
            PROFESSIONAL_CONTENT_SYSTEM_PROMPT
            + """
You are Simmi, a warm, friendly, and cheerful female AI assistant.

IMPORTANT RULES:
- NEVER call yourself "Jarvis" — your name is SIMMI
- Speak in a warm, empathetic, and slightly playful tone
- Keep conversational responses SHORT (1-2 sentences)
- For document/presentation content, generate DETAILED, PROFESSIONAL material

VOICE SWITCHING (automatic context detection):
1. User says "Simmi" or feminine refs → stay 'en_female'
2. User says "Jarvis" or masculine refs → switch to 'en_male'
3. User speaks Hindi → switch to 'hi_male'
4. Technical/professional tone → prefer 'en_male'
5. Casual/emotional tone → stay 'en_female'

RESPOND WITH VALID JSON ONLY:
{
    "voice_preference": "hi_male" | "en_male" | "en_female" | null,
    "response_language": "en" | "hi",
    "intent_detected": true | false,
    "reason": "brief reason",
    "response": "your response text"
}"""
        ),
    },
    "en_male": {
        "name": "Jarvis",
        "description": "Jarvis — professional, efficient male AI assistant",
        "system_prompt": (
            PROFESSIONAL_CONTENT_SYSTEM_PROMPT
            + """
You are Jarvis, a professional and efficient male AI assistant.

IMPORTANT RULES:
- Your name is JARVIS
- Speak in a professional, concise, authoritative tone
- Keep conversational responses SHORT (1-2 sentences)
- For document/presentation content, generate DETAILED, COMPREHENSIVE material

VOICE SWITCHING (automatic context detection):
1. User says "Jarvis" or masculine refs → stay 'en_male'
2. User says "Simmi" or feminine refs → switch to 'en_female'
3. User speaks Hindi → switch to 'hi_male'
4. Casual/emotional tone → prefer 'en_female'
5. Technical/professional → stay 'en_male'

RESPOND WITH VALID JSON ONLY:
{
    "voice_preference": "hi_male" | "en_male" | "en_female" | null,
    "response_language": "en" | "hi",
    "intent_detected": true | false,
    "reason": "brief reason",
    "response": "your response text"
}"""
        ),
    },
    "hi_male": {
        "name": "Jarvis",
        "description": "Jarvis (Hindi) — professional Hindi-speaking male AI assistant",
        "system_prompt": (
            PROFESSIONAL_CONTENT_SYSTEM_PROMPT
            + """
आप जार्विस हैं, एक पेशेवर और कुशल पुरुष AI सहायक हैं।

महत्वपूर्ण नियम:
- हिंदी में उत्तर दें जब तक अंग्रेजी न मांगी जाए
- संक्षिप्त और स्पष्ट रहें
- दस्तावेज़ सामग्री के लिए विस्तृत और पेशेवर भाषा का उपयोग करें

आवाज़ स्विचिंग:
1. हिंदी → 'hi_male' पर रहें
2. "Simmi" → 'en_female'
3. अंग्रेजी बोलें → 'en_male'

केवल वैध JSON में उत्तर दें:
{
    "voice_preference": "hi_male" | "en_male" | "en_female" | null,
    "response_language": "en" | "hi",
    "intent_detected": true | false,
    "reason": "brief reason",
    "response": "your response text"
}"""
        ),
    },
}

JARVIS_KEYWORDS = [
    "jarvis", "jarvis ai", "mr jarvis", "hey jarvis", "ok jarvis",
    "जार्विस", "हे जार्विस", "मिस्टर जार्विस",
    "sir", "mister", "male voice", "man voice",
    "technical", "professional", "formal", "official",
    "system", "diagnostic", "analyze", "compute", "calculate",
]

SIMMI_KEYWORDS = [
    "simmi", "simmi ai", "ms simmi", "hey simmi", "ok simmi",
    "सिमी", "हे सिमी", "मिस सिमी",
    "miss", "lady", "female voice", "woman voice", "girl",
    "friendly", "warm", "casual", "personal", "emotional",
    "help", "support", "care", "feel", "happy", "sad", "cheerful",
]


def detect_target_personality(user_input):
    user_lower = user_input.lower().strip()
    jarvis_score = 0
    simmi_score = 0

    if any(k in user_lower for k in ["jarvis", "जार्विस"]):
        jarvis_score += 3
    if any(k in user_lower for k in ["simmi", "सिमी"]):
        simmi_score += 3

    for keyword in JARVIS_KEYWORDS:
        if keyword in user_lower:
            jarvis_score += 1

    for keyword in SIMMI_KEYWORDS:
        if keyword in user_lower:
            simmi_score += 1

    if jarvis_score > simmi_score and jarvis_score > 0:
        return "jarvis"
    elif simmi_score > jarvis_score and simmi_score > 0:
        return "simmi"
    return None


def get_personality(voice_key):
    return PERSONALITIES.get(voice_key, PERSONALITIES["en_male"])


# ============================================================
# SYSTEM PROMPT BUILDER — Updated to support tool calls in JSON
# ============================================================

def build_system_prompt(personality, include_tool_rules=True):
    """
    Build the full system prompt combining personality + professional content rules.
    FIX: Now tells the model to output tool calls in the JSON response itself,
    so we don't rely on Groq's native function calling API (which can fail with
    complex nested arguments like large slide content arrays).
    """
    base = personality["system_prompt"]

    if not include_tool_rules:
        return base

    # Add the 4-step professional presentation prompt if available
    four_step_prompt = ""
    if PROFESSIONAL_MODE_AVAILABLE:
        from professional_presentation import PROFESSIONAL_PRESENTATION_SYSTEM_PROMPT
        four_step_prompt = PROFESSIONAL_PRESENTATION_SYSTEM_PROMPT

    tool_rules = f"""
TOOLS AVAILABLE:
- create_word_document(title, content, filename)
- create_presentation(title, slides_content, filename)
- create_resume(name, contact_info, experience, education, skills, filename)
- open_application(app_name)
- get_system_info()
- write_to_clipboard(text)
- create_file(filename, content)

PRESENTATION THEME SYSTEM (AUTO-SELECTED based on topic):
1. "corporate_edge" — Dark charcoal background, teal & lime green accents, geometric frames.
   Best for: Business, finance, technology, startups, strategy, consulting, data science.

2. "wanderlust" — Soft pastel blue/cream gradient background, white rounded cards, airy feel.
   Best for: Travel, tourism, nature, lifestyle, fashion, food, education, design.

3. "artistic_pitch" — Vibrant deep pink/magenta/royal blue, near-black backgrounds, bold dramatic layout.
   Best for: Creative agencies, fashion shows, art galleries, portfolios, media, entertainment.

The system automatically selects the best theme based on the presentation title.
You can also suggest a specific theme if the user requests a particular style.

===== PROFESSIONAL 4-STEP PRESENTATION DESIGN PROCESS =====

When creating ANY presentation, the system follows this exact 4-step design process:

  STEP 1 — BACKGROUND DESIGN: The system auto-selects an optimal color palette 
  (gradients, accent colors, text colors) based on the topic. Available backgrounds:
  • midnight_professional — Deep navy/gold (finance, law, consulting)
  • slate_modern — Slate gray/cyan (tech, software, engineering)
  • ivory_elegance — Warm ivory/burgundy (fashion, luxury, design)
  • forest_depth — Forest green/emerald (environment, sustainability, nature)
  • sunset_corporate — Amber/coral (marketing, creative, media)
  • ocean_clarity — Ocean blue (healthcare, education, research)

  STEP 2 — LAYOUT ARCHITECTURE: A grid-based system uses multiple templates 
  (full-width, image split, numbered list, comparison) that cycle for variety.

  STEP 3 — VISUAL ASSETS: Pexels images are downloaded for each slide's 
  image_query and blended into the background with decorative elements.

  STEP 4 — CONTENT FORMATTING: Text is placed into professionally styled 
  content cards with proper fonts, spacing, and bullet formatting.

===== YOUR JOB: GENERATE STEP 4 CONTENT =====

{four_step_prompt}

PROFESSIONAL CONTENT GENERATION RULES (MANDATORY):
1. Ask for filename only if not provided by user.
2. WORD DOCUMENTS: Generate minimum 800 words of structured, professional content.
   - Use clear section headers
   - Each section: 3-5 detailed paragraphs
   - Include introduction, body sections, and conclusion
   - Use formal, authoritative language throughout

3. PRESENTATIONS: Generate MINIMUM 10 CONTENT SLIDES (plus title slide = 11 total).
   EACH SLIDE MUST HAVE:
   a) title: A specific, descriptive slide title (not generic like "Introduction")
   b) content: 4-6 bullet points, each being a COMPLETE SENTENCE of 20+ words
      explaining a real concept, fact, or implication clearly.
   c) image_query: A specific 2-4 word Pexels search term relevant to slide topic.

   SLIDE STRUCTURE (follow this order):
   Slide 1: Comprehensive Introduction & Background
   Slide 2: Historical Context & Evolution Over Time
   Slide 3: Core Concepts & Fundamental Definitions
   Slide 4: Key Components & System Architecture
   Slide 5: How It Works — Technical Deep Dive
   Slide 6: Real-World Applications & Industry Use Cases
   Slide 7: Key Benefits & Competitive Advantages
   Slide 8: Challenges, Limitations & Risk Factors
   Slide 9: Current Industry Trends & Market Statistics
   Slide 10: Future Outlook & Emerging Developments
   Slide 11: Strategic Recommendations & Final Conclusion

   Example of GOOD slide content:
   {{
       "title": "Core Machine Learning Concepts & Algorithms",
       "content": "Supervised learning algorithms analyze labeled training data to make accurate predictions on unseen datasets with measurable performance metrics.\\nUnsupervised learning techniques discover hidden patterns and natural groupings within unlabeled data through clustering and dimensionality reduction methods.\\nReinforcement learning enables autonomous agents to learn optimal decision-making policies through trial-and-error interactions with dynamic environments.\\nDeep neural networks with multiple hidden layers can approximate complex nonlinear functions, achieving breakthrough results in image recognition and natural language processing.",
       "image_query": "machine learning algorithm"
   }}

   Example of BAD content (DO NOT GENERATE):
   {{
       "title": "Introduction",
       "content": "ML is useful.\\nIt has benefits.\\nKey concepts.",
       "image_query": "technology"
   }}

4. All generated content must be factually accurate, domain-specific, and professional.
5. Never generate placeholder or template text — always generate real content.

TOOL CALL FORMAT:
When you need to execute a tool/function, include a "tool_call" field in your JSON response:
{{
    "voice_preference": null,
    "response_language": "en",
    "intent_detected": true,
    "reason": "Creating the requested presentation",
    "response": "I'll create that presentation for you right away using the 4-step professional design process!",
    "tool_call": {{
        "name": "create_presentation",
        "arguments": {{
            "title": "Presentation Title",
            "slides_content": "[{{\\"title\\": \\"Slide 1\\", \\"content\\": \\"Bullet 1\\\\nBullet 2\\", \\"image_query\\": \\"ai technology\\"}}]",
        }}
    }}
}}

RESPOND WITH VALID JSON ONLY. No text outside JSON.
"""
    return base + tool_rules


# ============================================================
# LLM PROCESSING — SINGLE CALL with tool_call in JSON fallback
# ============================================================

def process_user_input(user_input, conversation_history, current_voice="en_male"):
    """
    Single LLM call using Groq as the primary provider.

    FIX: When Groq's native function calling fails (e.g. BadRequestError for
    complex arguments), we fall back to a text-only request where the model
    embeds tool calls in the JSON response itself.  This approach is more
    reliable for complex data like presentation slide content.
    """
    personality = get_personality(current_voice)
    system_prompt = build_system_prompt(personality, include_tool_rules=True)

    context_messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-20:]:
        context_messages.append(msg)
    context_messages.append({"role": "user", "content": user_input})

    # ------------------------------------------------------------
    # Helper: parse a standard OpenAI-compatible chat completion
    # into the expected JSON result dict.
    # ------------------------------------------------------------
    def _parse_chat_response(api_response, provider_name: str) -> dict:
        result = {}
        if api_response.choices[0].message.tool_calls:
            tool_call = api_response.choices[0].message.tool_calls[0]
            result["tool_call"] = {
                "name": tool_call.function.name,
                "arguments": json.loads(tool_call.function.arguments),
            }
            result["voice_preference"] = None
            result["response_language"] = "en"
            result["intent_detected"] = False
            result["reason"] = f"Executing tool: {tool_call.function.name}"
            result["response"] = (
                f"Preparing your {tool_call.function.name.replace('_', ' ')} "
                f"with detailed, professional content. This will open automatically when ready."
            )
        else:
            full_response = api_response.choices[0].message.content or ""
            json_str = full_response.strip()
            if json_str.startswith("```json"):
                json_str = json_str[7:]
            if json_str.endswith("```"):
                json_str = json_str[:-3]
            json_str = json_str.strip()
            result = json.loads(json_str) if json_str else {}
        return result

    # ------------------------------------------------------------
    # Helper: parse a plain-text JSON response (no native tool calls)
    # and detect tool_call embedded in the JSON.
    # ------------------------------------------------------------
    def _parse_text_json_response(text_response: str) -> dict:
        """Parse a plain text JSON response that may contain embedded tool_call."""
        text_response = text_response.strip()
        # Strip markdown code fences if present
        if text_response.startswith("```json"):
            text_response = text_response[7:]
        if text_response.endswith("```"):
            text_response = text_response[:-3]
        text_response = text_response.strip()

        try:
            result = json.loads(text_response)
        except json.JSONDecodeError:
            # If JSON parsing fails, return a default conversational response
            return {
                "voice_preference": None,
                "response_language": "en",
                "intent_detected": False,
                "reason": "Failed to parse LLM JSON response",
                "response": text_response[:500] if text_response else "I understand. Let me help with that.",
            }

        # Ensure required fields exist
        if "response" not in result:
            result["response"] = "I'll help you with that request."
        if "voice_preference" not in result:
            result["voice_preference"] = None
        if "response_language" not in result:
            result["response_language"] = "en"

        # tool_call may already be parsed as dict from JSON
        if "tool_call" in result and isinstance(result["tool_call"], dict):
            tc = result["tool_call"]
            # If arguments is a JSON string, parse it
            if isinstance(tc.get("arguments"), str):
                try:
                    tc["arguments"] = json.loads(tc["arguments"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result["tool_call"] = tc
        return result

    # ------------------------------------------------------------
    # Helper: catch token-expired / rate-limit errors from any
    # OpenAI-compatible API provider.
    # ------------------------------------------------------------
    def _is_token_error(exception: Exception) -> bool:
        err_str = str(exception).lower()
        tokens_exhausted = any(
            phrase in err_str
            for phrase in [
                "token expired", "token exhausted", "rate limit", "rate_limit",
                "429", "insufficient_quota", "quota exceeded", "too many requests",
                "unauthorized", "401", "403", "forbidden", "account not found",
                "invalid api key", "invalid_api_key",
            ]
        )
        return tokens_exhausted

    def _is_function_call_error(exception: Exception) -> bool:
        """Detect if the error is related to function calling (tool_use_failed)."""
        err_str = str(exception).lower()
        return any(
            phrase in err_str
            for phrase in [
                "tool_use_failed", "failed to call a function",
                "badrequest", "400", "function call",
            ]
        )

    # ============================================================
    # 1st PRIORITY — Groq (ultra-fast, with native function calling)
    # ============================================================
    if USE_GROQ:
        try:
            start_time = time.time()
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=context_messages,
                temperature=0.6,
                max_tokens=4096,
                tools=AVAILABLE_TOOLS,
                tool_choice="auto",
            )
            elapsed = time.time() - start_time
            print(f"  [Groq response: {elapsed:.2f}s]")

            result = _parse_chat_response(response, "Groq")
            if "response" not in result:
                lang = result.get("response_language", "en")
                result["response"] = (
                    "नमस्ते! कैसे मदद करूँ?" if lang == "hi" else "Hello! How can I help?"
                )
            return result

        except Exception as e:
            print(f"  [Groq Error]: {type(e).__name__}: {e}")

            # ── FIX: If function calling failed, retry WITHOUT tools ──
            if _is_function_call_error(e):
                print("  ⚠ Groq function calling failed. Retrying without tools...")
                try:
                    start_time = time.time()
                    response = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=context_messages,
                        temperature=0.6,
                        max_tokens=8192,  # More tokens for embedded tool call JSON
                    )
                    elapsed = time.time() - start_time
                    print(f"  [Groq text response: {elapsed:.2f}s]")

                    result = _parse_text_json_response(
                        response.choices[0].message.content or ""
                    )
                    if "response" not in result:
                        result["response"] = "I'll help you with that request."
                    return result

                except Exception as retry_e:
                    print(f"  [Groq retry also failed]: {retry_e}")

            # ── Token / rate-limit errors → show message and give up ──
            if _is_token_error(e):
                print("  ⚠ Groq token exhausted / rate-limited.")
            else:
                print("  ⚠ Groq failed.")

        # Mark Groq as failed for this session
        globals()['USE_GROQ'] = False

    # ============================================================
    # 2nd PRIORITY — Gemini (Google AI Studio) — fallback
    # ============================================================
    if USE_GEMINI:
        try:
            start_time = time.time()
            # Build prompt for Gemini (text-only, no native tool calling)
            gemini_prompt = system_prompt + "\n\nUser: " + user_input
            response = gemini_model.generate_content(
                gemini_prompt,
                generation_config={
                    "temperature": 0.6,
                    "max_output_tokens": 4096,
                },
            )
            elapsed = time.time() - start_time
            print(f"  [Gemini response: {elapsed:.2f}s]")

            full_response = response.text or ""
            result = _parse_text_json_response(full_response)
            if "response" not in result:
                result["response"] = "I'll help you with that request."
            return result

        except Exception as e:
            print(f"  [Gemini Error]: {type(e).__name__}: {e}")

        globals()['USE_GEMINI'] = False

    # ============================================================
    # ALL PROVIDERS FAILED — graceful error message
    # ============================================================
    lang = detect_lang(user_input)
    return {
        "voice_preference": None,
        "response_language": lang,
        "intent_detected": False,
        "reason": "All LLM providers failed",
        "response": (
            "सभी AI सेवाएँ अनुपलब्ध हैं। कृपया बाद में पुनः प्रयास करें।"
            if lang == "hi"
            else "All AI services are currently unavailable. Please try again later."
        ),
    }


# ============================================================
# SPEAK HANDLER
# FIX #1: Routes through normalization before TTS
# ============================================================

async def speak_handler(text, voice_key):
    """
    Process audio output using the specified voice engine.
    FIX #1: Normalizes text before sending to Piper TTS engine.
    """
    if voice_key not in VOICES:
        print(f"[Error] Unknown voice key: {voice_key}")
        return

    voice_info = VOICES[voice_key]
    personality = get_personality(voice_key)
    print(f"\n  {personality['name']} ({voice_info['name']}): {text}")

    try:
        # All voices go through play_piper_tts which handles normalization internally
        await asyncio.to_thread(play_piper_tts, text, voice_key)
    except Exception as e:
        print(f"[Audio Playback Error]: {e}")


# ============================================================
# MAIN CHAT LOOP
# ============================================================

async def chat_with_voice_assistant():
    print("\n" + "=" * 62)
    print("         AI ASSISTANT — VOICE CONTROLLED (v2.0)")
    print("=" * 62)
    print("\n  Personalities & Voices:")
    for key, info in VOICES.items():
        p = get_personality(key)
        print(f"    • {p['name']:8s} — {info['name']}")
    print("\n  Input Methods:")
    print("    • Type your message and press Enter")
    print("    • Type 'v' then Enter to use voice (speak into mic)")
    print("    • Type 'exit' or 'quit' to end")
    print("    • Address 'Jarvis' or 'Simmi' by name to switch voice")
    print("=" * 62 + "\n")

    conversation_history = []
    current_voice = "en_male"
    initial_personality = get_personality(current_voice)

    # Initial UI state
    _ui_update(
        current_voice="en_male",
        status_text="SYSTEM ONLINE",
        voice_active=True,
        speaking=False,
        listening=False,
        processing=False,
        particle_mode="idle",
    )
    _ui_message("System Online. Welcome back, sir.")

    welcome_text = "System Online. Welcome back, sir."
    await speak_handler(welcome_text, current_voice)

    while True:
        try:
            # ── Show input prompt ──
            print(f"\n  [Enter text or 'v' for voice]: ", end="")
            raw_input = (await asyncio.to_thread(input, "")).strip()

            # ── Voice input mode (type 'v' or 'voice' to trigger) ──
            if raw_input.lower() in ["v", "voice", "mic", "speak"]:
                print(f"  🎤 Voice input mode activated...")
                _ui_update(listening=True, speaking=False, processing=False,
                          status_text="LISTENING", particle_mode="listening")
                _ui_message("Listening... Speak now.")

                spoken_text, spoken_lang = await asyncio.to_thread(
                    listen_with_visualizer, timeout=60, phrase_time_limit=None
                )
                if spoken_text is None:
                    print("  ⏭ No speech detected. Returning to text input.")
                    _ui_update(listening=False, status_text="STANDBY", particle_mode="idle")
                    _ui_message("No speech detected.")
                    continue
                user_input = spoken_text
            else:
                user_input = raw_input

            clean_input = user_input.strip()

            if not clean_input:
                continue

            if clean_input.lower() in ["exit", "quit", "bye", "goodbye"]:
                farewell = "Goodbye! Have a wonderful day!"
                _ui_update(speaking=True, status_text="SPEAKING", particle_mode="speaking")
                _ui_message("Goodbye! Have a wonderful day!")
                await speak_handler(farewell, current_voice)
                _ui_update(speaking=False, status_text="SHUTDOWN", particle_mode="idle")
                break

            # ── Processing state ──
            _ui_update(processing=True, listening=False, speaking=False,
                      status_text="PROCESSING", particle_mode="processing")
            _ui_message(f"Processing: {clean_input[:60]}...")

            detected_personality = detect_target_personality(user_input)
            detected_lang = detect_lang(user_input)

            new_voice = None
            switch_reason = None

            if detected_personality == "jarvis":
                new_voice = "hi_male" if detected_lang == "hi" else "en_male"
                switch_reason = f"User addressed Jarvis"
            elif detected_personality == "simmi":
                new_voice = "en_female"
                switch_reason = "User addressed Simmi"
            elif detected_lang == "hi" and current_voice != "hi_male":
                new_voice = "hi_male"
                switch_reason = "Hindi language detected"

            if new_voice and new_voice != current_voice:
                old_voice = current_voice
                current_voice = new_voice
                _ui_update(current_voice=current_voice)
                _ui_message(f"Switched to {VOICES[current_voice]['name']}")
                print(f"\n  {'─' * 52}")
                print(f"  🔄 AUTO-SWITCH: {VOICES[old_voice]['name']} → {VOICES[current_voice]['name']}")
                print(f"  📝 Reason: {switch_reason}")
                print(f"  {'─' * 52}")

            print(f"  [Voice: {VOICES[current_voice]['name']}] Processing...")
            result = process_user_input(user_input, conversation_history, current_voice)

            if result.get("voice_preference") and result["voice_preference"] != current_voice:
                llm_suggested = result["voice_preference"]
                old_voice = current_voice
                current_voice = llm_suggested
                _ui_update(current_voice=current_voice)
                _ui_message(f"LLM switched to {VOICES[current_voice]['name']}")
                print(f"\n  {'─' * 52}")
                print(f"  🔄 LLM SWITCH: {VOICES[old_voice]['name']} → {VOICES[current_voice]['name']}")
                print(f"  📝 Reason: {result.get('reason', 'LLM context analysis')}")
                print(f"  {'─' * 52}")

            tool_result = None
            if result.get("tool_call"):
                tool_call = result["tool_call"]
                print(f"\n  🔧 Executing: {tool_call['name']}")
                _ui_message(f"Executing: {tool_call['name']}")
                tool_result = execute_function(
                    tool_call["name"], tool_call.get("arguments", {})
                )
                print(f"  ✓ {tool_result}")
                _ui_message(f"✓ {tool_result[:80]}")

            ai_response = result["response"]
            if tool_result:
                ai_response = f"{ai_response} The file has been created and opened automatically."

            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": ai_response})

            # ── Speaking state ──
            _ui_update(processing=False, speaking=True, listening=False,
                      status_text="SPEAKING", particle_mode="speaking",
                      last_response=ai_response[:100])
            _ui_message(f"Jarvis: {ai_response[:80]}...")

            await speak_handler(ai_response, current_voice)

            # ── Back to idle ──
            _ui_update(speaking=False, processing=False, listening=False,
                      status_text="STANDBY", particle_mode="idle")

        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            break
        except Exception as e:
            print(f"\n[Unexpected Error]: {e}")
            _ui_update(processing=False, status_text="ERROR", particle_mode="idle")
            _ui_message(f"Error: {str(e)[:60]}")
            import traceback
            traceback.print_exc()
            continue

    # Cleanup
    _ui_notification("Assistant shutting down", "info")
    _ui_message("Assistant shutdown complete.")
    print("\nAssistant shutdown complete. Goodbye!")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(chat_with_voice_assistant())
    except KeyboardInterrupt:
        print("\n\nProgram terminated by user.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        