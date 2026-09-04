import requests
from bs4 import BeautifulSoup

def strip_thinking_tokens(text: str) -> str:
    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>") + len("</think>")
        text = text[:start] + text[end:]
    return text


def clean_search_query(text: str) -> str:
    text = strip_thinking_tokens(text)
    for line in text.splitlines():
        line = line.strip().lstrip("0123456789.、- ").strip()
        if line:
            return line
    return text.strip()



def is_valid_search_query(query: str) -> bool:
    if not query:
        return False
    if any(ch in query for ch in '？?。，,！!；;：:'):
        return False
    cjk_count = sum(1 for ch in query if "\u4e00" <= ch <= "\u9fff")
    if cjk_count > 15:
        return False
    return True