"""
Phase 3 - deep file page probe: find where the PDF URL is hidden.
"""
import sys, re
sys.path.insert(0, ".")
from bs4 import BeautifulSoup
from core.session_manager import SessionManager

sm = SessionManager()
FILE_URL = "https://files.jntufastupdates.com/download/i-year-b-tech-ac-2025-26/"
r = sm.get(FILE_URL, delay=False)
soup = BeautifulSoup(r.text, "lxml")

with open("exports/file_page_raw.html", "w", encoding="utf-8") as f:
    f.write(r.text)

print("=== ALL ANCHORS ===")
for a in soup.find_all("a", href=True):
    print(f"  [{a.get('class','')}] TEXT={a.get_text(strip=True)[:60]} | HREF={a['href']}")

print("\n=== ALL BUTTONS ===")
for b in soup.find_all("button"):
    print(f"  [{b.get('class','')}] TEXT={b.get_text(strip=True)[:60]} | onclick={b.get('onclick','')}")

print("\n=== DATA ATTRIBUTES on links ===")
for tag in soup.find_all(True):
    attrs = {k:v for k,v in tag.attrs.items() if k.startswith("data-")}
    if attrs:
        print(f"  <{tag.name}> {attrs}")

print("\n=== SCRIPT TAGS (PDF references) ===")
for s in soup.find_all("script"):
    txt = s.string or ""
    if txt and any(k in txt.lower() for k in ["pdf","download","file","href","url","link"]):
        # Print lines containing those keywords
        for line in txt.split("\n"):
            if any(k in line.lower() for k in ["pdf","download url","fileurl","file_url","href"]):
                print(f"  JS: {line.strip()[:200]}")

print("\n=== FORMS ===")
for f in soup.find_all("form"):
    print(f"  form action={f.get('action','')} method={f.get('method','')}")
    for inp in f.find_all(["input","hidden"]):
        print(f"    input name={inp.get('name','')} value={inp.get('value','')[:100]}")

print("\n=== META REFRESH / REDIRECT ===")
for m in soup.find_all("meta"):
    if m.get("http-equiv","").lower() == "refresh":
        print(f"  META REFRESH: {m.get('content','')}")

sm.close()
print("Done. Also saved file_page_raw.html")
