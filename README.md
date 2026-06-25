jam# 🤖 AI Voice Assistant - Jarvis & Simmi

An intelligent, context-aware AI voice assistant with multiple personalities (Jarvis and Simmi) that automatically understands who you're talking to without requiring explicit switch commands.

## ✨ Key Features

### 🧠 **Intelligent Context-Aware Switching**
- **No Keywords Required**: The AI automatically understands whether you're addressing Jarvis or Simmi based on context
- **Natural Conversation**: Just talk naturally - the system detects personality preferences from your tone and content
- **Language Detection**: Automatically switches to Hindi when you speak Hindi
- **Tone Analysis**: Professional/technical queries → Jarvis; Casual/emotional queries → Simmi

### 🎭 **Dual Personalities**

#### **Jarvis** (Male Voice)
- Professional, efficient, and direct
- Best for technical tasks, system operations, and formal interactions
- Available in English (`en_male`) and Hindi (`hi_male`)
- Voice: Clear, authoritative male voice

#### **Simmi** (Female Voice)  
- Warm, friendly, and cheerful
- Best for personal conversations, emotional support, and casual chat
- Available in English (`en_female`)
- Voice: Warm, empathetic female voice

### 🛠️ **Powerful Capabilities**
- **Document Creation**: Generate Word documents, PowerPoint presentations, and resumes
- **Creative Presentations**: Background-first design with Pexels images
- **System Control**: Open applications, get system info, manage clipboard
- **File Operations**: Create and manage text files
- **Tool Integration**: LLM-powered tool calling with Groq API for ultra-fast responses

### 🎨 **Pexels Integration for Presentations**
- **High-Quality Images**: Access millions of royalty-free photos from Pexels
- **Background-First Design**: Automatically downloads relevant background images
- **Smart Color Analysis**: Extracts color palettes for optimal text readability
- **Creative Layouts**: Multiple layout options (title_content, two_content, title_only)
- **Text Overlay**: Semi-transparent overlays for professional text presentation

## 🚀 Quick Start

### 1. Prerequisites
```bash
pip install groq sounddevice numpy pygame piper-tts python-docx python-pptx pyautogui pyperclip psutil ollama edge-tts pywin32 requests pillow python-dotenv
```

> **Note:** `requests` and `pillow` are required for Pexels API integration and image processing for creative presentations.

> **Note:** `pywin32` is required for live document creation (watching Word/PowerPoint create documents in real-time). If not installed, documents will be created silently in the background.

### 2. Set up API Keys (Required)

**⚠️ IMPORTANT: Never commit your API keys to GitHub**

Create a `.env` file in the project root with your API keys:

```bash
# .env — copy this template and fill in your keys
GROQ_API_KEY=gsk_your_groq_api_key_here
PEXELS_API_KEY=your_pexels_api_key_here
```

The `.env` file is already listed in `.gitignore` so it will never be pushed to GitHub.

- **Get a Groq API key:** https://console.groq.com/keys (free tier available)
- **Get a Pexels API key:** https://www.pexels.com/api/ (free tier available)

### 3. Running the Assistant
```bash
python jarvis.py
```

## 💡 How to Use

### **Natural Interaction Examples**

#### Talking to Jarvis:
```
You: Jarvis, what's my system status?
You: Hey Jarvis, open Chrome for me
You: Jarvis, I need to create a technical document
You: Can you analyze this data, Jarvis?
```

#### Talking to Simmi:
```
You: Simmi, I'm feeling a bit down today
You: Hey Simmi, tell me something cheerful
You: Simmi, I need some friendly advice
You: Can we chat for a bit, Simmi?
```

#### Language Switching:
```
You: [Speak in Hindi] मुझे एक दस्तावेज़ बनाना है
→ Automatically switches to Hindi Jarvis (hi_male)

You: [Speak in English] Create a presentation
→ Stays in English (Jarvis or Simmi based on context)
```

### **Context-Aware Behavior**

The system automatically detects:

1. **Name Usage**: Saying "Jarvis" or "Simmi" directly
2. **Tone Analysis**: 
   - Professional/technical → Jarvis
   - Casual/emotional → Simmi
3. **Task Type**:
   - System tasks, calculations, analysis → Jarvis
   - Personal conversations, support → Simmi
4. **Language**:
   - Hindi text → Hindi Jarvis
   - English text → English voice (Jarvis/Simmi based on context)

## 🔄 How Intelligent Switching Works

### **Two-Layer Detection System**

#### **Layer 1: Fast Keyword Detection** (Instant)
```python
detect_target_personality(user_input)
```
- Scores keywords associated with each personality
- Provides immediate voice switching before LLM processing
- Handles direct name addressing and contextual keywords

#### **Layer 2: LLM Context Analysis** (Deep Understanding)
- The current personality's LLM analyzes full context
- Considers conversation history and nuanced meaning
- Can override fast detection if deeper context suggests otherwise
- Provides explanations for voice choices

### **Switching Logic**

```python
# Fast detection (instant)
if "jarvis" in user_input:
    switch_to('en_male' or 'hi_male')
elif "simmi" in user_input:
    switch_to('en_female')
elif hindi_detected(user_input):
    switch_to('hi_male')

# LLM refinement (context-aware)
# LLM can override based on deeper understanding
```

## 🎯 Use Cases

### **When to Use Jarvis:**
- System administration tasks
- Technical documentation
- Data analysis and calculations
- Professional workflows
- Formal interactions

### **When to Use Simmi:**
- Personal conversations
- Emotional support
- Casual chatting
- Creative discussions
- Friendly assistance

### **When to Use Hindi:**
- Hindi language conversations
- Indian language content creation
- Regional communication needs

## ⚙️ Technical Architecture

### **Components:**

1. **Voice Engines** (Piper TTS)
   - Local `.onnx` models for offline synthesis
   - English Male, English Female, Hindi Male
   - Real-time audio streaming

2. **LLM Backend** (Groq API)
   - Ultra-fast responses (Llama 3.1 8B)
   - Tool calling support
   - JSON-structured outputs

3. **Personality System**
   - Distinct system prompts for each personality
   - Context-aware switching logic
   - Conversation history management

4. **Tool Integration**
   - Document creation (Word, PowerPoint, Resume)
   - System control (apps, clipboard, files)
   - Function execution framework

## 🔧 Configuration

### **Voice Settings**
Located in `jarvis.py`:

```python
VOICES = {
    'en_male': {  # Jarvis English
        'model': 'voices/english/en_US-hfc_male-medium.onnx',
        'config': 'voices/english/en_US-hfc_male-medium.onnx.json',
        'name': 'English Male (Medium)',
        'language': 'en'
    },
    'en_female': {  # Simmi English
        'model': 'voices/english/en_US-libritts_r-medium.onnx',
        'config': 'voices/english/en_US-libritts_r-medium.onnx.json',
        'name': 'English Female (LibriTTS)',
        'language': 'en'
    },
    'hi_male': {  # Jarvis Hindi
        'model': 'voices/hindi/hi_IN-pratham-medium.onnx',
        'config': 'voices/hindi/hi_IN-pratham-medium.onnx.json',
        'name': 'Hindi Male (Pratham)',
        'language': 'hi'
    }
}
```

### **Personality Prompts**
Each personality has customized system prompts that define:
- Name and identity
- Speaking style and tone
- Voice switching rules
- Response format requirements

## 📊 Performance

- **Response Time**: ~0.5-2 seconds (Groq API)
- **Voice Switching**: Instant (keyword detection) + ~1 second (LLM refinement)
- **Audio Generation**: Real-time streaming
- **Memory Usage**: ~500MB (voice models loaded)

## 🛡️ Error Handling

The system includes robust error handling:
- Fallback to local Ollama if Groq API fails
- JSON parsing recovery
- Voice engine error handling
- Graceful degradation

## 📝 Examples

### **Example 1: Technical Task with Jarvis**
```
You: Jarvis, create a Word document about AI
[Auto-switches to Jarvis]
Jarvis: I'll create that document for you right away!
[Document created successfully]
```

### **Example 2: Emotional Support with Simmi**
```
You: Simmi, I had a rough day
[Auto-switches to Simmi]
Simmi: I'm here for you. Want to talk about it? 💙
```

### **Example 3: Hindi Conversation**
```
You: मुझे एक प्रेजेंटेशन बनाना है
[Auto-switches to Hindi Jarvis]
जार्विस: मैं अभी प्रेजेंटेशन बनाता हूँ!
```

## 🎨 Creative Presentation System

The AI assistant now includes a powerful creative presentation system that uses the **Pexels API** to create stunning presentations with a **background-first design approach**.

### **How It Works:**

1. **Background Selection**: For each slide, the system searches Pexels for relevant high-quality images
2. **Color Analysis**: Extracts the dominant colors from the background image
3. **Text Color Optimization**: Automatically chooses white or dark text for maximum readability
4. **Semi-Transparent Overlays**: Adds overlays to ensure text is always readable
5. **Creative Layouts**: Supports multiple layout types for visual variety

### **Layout Options:**

- **`title_content`**: Title at top, content box on side (default)
- **`two_content`**: Two content boxes side by side
- **`title_only`**: Full-screen background with centered title

### **Example Slide Structure:**
```python
{
    "title": "Introduction to AI",
    "content": "• What is AI?\n• History of AI\n• Current applications",
    "image_query": "artificial intelligence technology",
    "layout": "title_content",
    "text_position": "right"
}
```

### **Pexels API Features:**
- **Free High-Quality Images**: Millions of royalty-free photos
- **Smart Search**: Enhanced queries for presentation-optimized backgrounds
- **Video Support**: Can also search and download videos
- **Automatic Downloads**: Images cached locally for reuse

## 🔄 Updates & Improvements

### **Latest Changes:**
✅ **Pexels Integration for Presentations**
- Background-first design approach
- Automatic color palette extraction
- Smart text overlay with readability optimization
- Support for multiple creative layouts

✅ **Intelligent Context-Aware Switching**
- Automatic personality detection without keywords
- Tone and context analysis
- Seamless voice transitions

✅ **Enhanced Personality System**
- Distinct Jarvis and Simmi personalities
- Improved system prompts
- Better context understanding

✅ **Optimized Performance**
- Two-layer detection (fast + deep)
- Single LLM call per interaction
- Efficient voice switching

## 🤝 Contributing

Contributions welcome! Areas for improvement:
- Additional voice options
- More personality types
- Enhanced context detection
- Better language support

## 📄 License

MIT License - Feel free to use and modify

## 🙏 Acknowledgments

- **Groq** for ultra-fast LLM inference
- **Piper TTS** for high-quality voice synthesis
- **Piper Voice Models** for English and Hindi voices

---

**Enjoy your intelligent AI assistant that truly understands who you're talking to! 🎉**