import os
from dotenv import load_dotenv

load_dotenv()

# Which LLM provider to use for extraction/vision/taxonomy calls: "anthropic" or "gemini"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "serper")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Tunables
MAX_SOURCES_TO_FETCH = 5
MAX_PDF_PAGES = 15
REQUEST_TIMEOUT_SECONDS = 20