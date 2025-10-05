import os
import re
import time
import random
import unicodedata

from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

BASE_DIR = os.path.dirname(__file__)
CHROMEDRIVER_PATH = os.path.join(BASE_DIR, "chromedriver", "chromedriver.exe")
PROXIES_FILE = os.path.join(BASE_DIR, "proxies.txt")

def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("ʼ", "'")
    return _clean(s).lower()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
]

def _pick_user_agent() -> str:
    ua = os.getenv("SCRAPER_UA", "").strip()
    return ua or random.choice(USER_AGENTS)

def _load_proxies_from_file() -> List[str]:
    if not os.path.isfile(PROXIES_FILE):
        return []
    out = []
    with open(PROXIES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and not url.startswith("#"):
                out.append(url)
    return out

def _pick_proxy() -> Optional[str]:
    env_proxy = (
        os.getenv("SCRAPER_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("HTTPS_PROXY")
        or ""
    ).strip()
    if env_proxy:
        return env_proxy
    pool = _load_proxies_from_file()
    return random.choice(pool) if pool else None

def _mask_proxy_for_log(proxy: str) -> str:
    return re.sub(r":([^:@/]+)@", r":***@", proxy)

def _make_options_with_masking(proxy: Optional[str]) -> Options:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,900")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--disable-blink-features=AutomationControlled")

    ua = _pick_user_agent()
    opts.add_argument(f"--user-agent={ua}")

    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
        print(f"[SCRAPER] proxy: {_mask_proxy_for_log(proxy)}")
    else:
        print("[SCRAPER] proxy: OFF")
    print(f"[SCRAPER] UA: {ua}")
    return opts

def _build_driver(proxy: Optional[str]) -> webdriver.Chrome:
    opts = _make_options_with_masking(proxy)
    if os.path.isfile(CHROMEDRIVER_PATH):
        return webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=opts)
    return webdriver.Chrome(options=opts)

def _get_html(url: str, proxy: Optional[str], attempts: int = 3) -> str:
    last_err: Optional[Exception] = None
    for _ in range(attempts):
        driver = None
        try:
            driver = _build_driver(proxy)
            driver.get(url)
            time.sleep(1.2 + random.random() * 0.9)
            html = driver.page_source
            driver.quit()
            return html
        except Exception as e:
            last_err = e
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            pool = _load_proxies_from_file()
            if pool:
                proxy = random.choice(pool)
            time.sleep(1.2)
    if last_err:
        raise last_err
    return ""

_REMOTE_TOK = re.compile(r"\b(remote|віддалено|дистанційно)\b", re.I | re.U)

def _strip_remote_token(q: str) -> Tuple[str, bool]:
    is_remote = bool(_REMOTE_TOK.search(q))
    cleaned = _REMOTE_TOK.sub(" ", q)
    return _clean(cleaned), is_remote

def _pretty_search_url(query: str, remote: bool) -> str:
    slug = re.sub(r"\s+", "+", query.strip())
    base = f"https://www.work.ua/jobs{'-remote' if remote else ''}-{slug}/"
    return f"{base}?notitle=1"

def search_workua(query: str, limit: int = 5) -> List[str]:
    """Простий пошук (тільки URLів)."""
    q = (query or "").strip()
    if not q:
        return []
    q_clean, is_remote = _strip_remote_token(q)
    urls_to_try = [
        _pretty_search_url(q_clean, is_remote),
        "https://www.work.ua/jobs/?" + urlencode({"search": q_clean, "ss": "1", "notitle": "1"}),
    ]
    found: List[str] = []
    proxy = _pick_proxy()
    for search_url in urls_to_try:
        try:
            soup = BeautifulSoup(_get_html(search_url, proxy), "html.parser")
            for a in soup.find_all("a", href=True):
                h = a["href"]
                if re.fullmatch(r"/jobs/\d+/?", h):
                    full = urljoin("https://www.work.ua", h)
                    if full not in found:
                        found.append(full)
                if len(found) >= limit:
                    return found
        except Exception:
            continue
    return found

def search_workua_detailed(query: str, limit: int = 10) -> List[Dict]:

    q = (query or "").strip()
    if not q:
        return []
    q_clean, is_remote = _strip_remote_token(q)
    urls_to_try = [
        _pretty_search_url(q_clean, is_remote),
        "https://www.work.ua/jobs/?" + urlencode({"search": q_clean, "ss": "1", "notitle": "1"}),
    ]

    out: List[Dict] = []
    proxy = _pick_proxy()

    for search_url in urls_to_try:
        try:
            html = _get_html(search_url, proxy)
            soup = BeautifulSoup(html, "html.parser")

            cards = []
            for div in soup.find_all("div"):
                cls = " ".join(div.get("class", []))
                if "card" in cls and "/jobs/" in div.decode().lower():
                    cards.append(div)

            for card in cards:
                a_job = card.find("a", href=re.compile(r"^/jobs/\d+/?$"))
                if not a_job:
                    continue
                url = urljoin("https://www.work.ua", a_job["href"])
                title = _clean(a_job.get_text(" "))

                a_co = card.find("a", href=re.compile(r"/company/"))
                company = _clean(a_co.get_text(" ")) if a_co else "—"

                raw = _clean(card.get_text(" "))
                m = re.search(r"(\d[\d\s]+\s*(?:–|-)\s*\d[\d\s]+\s*грн|\d[\d\s]+\s*грн|₴\s*\d[\d\s]+)", raw, re.I)
                salary = _clean(m.group(1)) if m else "—"

                found_emp = []
                for kw in EMPLOYMENT_KEYWORDS:
                    if kw in raw and kw not in found_emp:
                        found_emp.append(kw)
                employment = ", ".join(found_emp) if found_emp else "—"

                out.append({
                    "url": url, "title": title, "company": company,
                    "salary": salary, "employment": employment
                })
                if len(out) >= limit:
                    return out
        except Exception:
            continue

    return out

EMPLOYMENT_KEYWORDS = [
    "Повна зайнятість", "Неповна зайнятість", "Позмінна робота",
    "Готові взяти студента", "Без досвіду", "Дистанційна робота", "Офіс"
]

SECTION_TITLES = {
    "expect": [
        # UA
        "що ми очікуємо", "очікуємо", "вимоги", "обов’язкові вимоги",
        "потрібні навички", "необхідні навички", "необхідний досвід",
        "вимоги до кандидата", "кваліфікація", "кваліфікації",
        "стек", "технічний стек", "технологічний стек",
        "бажано", "буде плюсом", "буде перевагою", "додатково",
        "перевага", "переваги (буде плюсом)",
        # EN
        "we expect", "what we expect", "what we expect from you",
        "requirements", "requirement", "required", "required skills",
        "required experience", "must have", "must-have",
        "skills", "skills & experience", "skills and experience",
        "qualifications", "qualification", "candidate profile",
        "we are looking for", "looking for", "needed skills",
        "experience with", "proficiency in",
        "nice to have", "nice-to-have", "preferred", "preferred qualifications",
        "good to have", "optional",
        "tech stack", "technology stack", "stack",
        # RU (інколи трапляється)
        "требования", "обязательные требования",
        "необходимые навыки", "необходимый опыт",
        "квалификация", "стек", "технический стек",
        "будет плюсом", "желательно", "преимуществом будет",
    ],
    "tasks": [
        # UA
        "твої задачі", "ваші задачі", "завдання", "основні завдання",
        "обов'язки", "обов’язки", "опис обов’язків",
        "що будете робити", "що потрібно зробити",
        "що входить у твої обов’язки", "що входить у твої обов'язки",
        "обов'язки та завдання", "функціональні обов’язки",
        "чим ти будеш займатися", "чим ви будете займатись",
        # EN
        "responsibilities", "key responsibilities", "main responsibilities",
        "primary responsibilities", "role responsibilities",
        "duties", "key duties", "main duties",
        "tasks", "tasks & responsibilities", "tasks and responsibilities",
        "what you will do", "what you'll do", "what you will be doing",
        "you will", "you will be responsible for",
        "job responsibilities", "job duties", "day-to-day",
        "scope of work", "your responsibilities", "your tasks",
        # RU
        "обязанности", "основные обязанности",
        "что будете делать", "чем будете заниматься",
        "функциональные обязанности",
        "requirements", "requirement", "требования"
    ],
}

ALL_SECTION_TITLES = [*SECTION_TITLES["expect"], *SECTION_TITLES["tasks"]]

def _is_section_heading(tag) -> bool:
    if not tag:
        return False
    n = tag.name or ""
    if n in ("h2", "h3", "strong", "b"):
        return True
    if n == "p":
        b = tag.find(["b", "strong"], recursive=False)
        return bool(b and _norm(b.get_text(" ")))
    return False

def _heading_text(tag) -> str:
    if not tag:
        return ""
    if tag.name in ("h2", "h3", "strong", "b"):
        return _norm(tag.get_text(" "))
    if tag.name == "p":
        b = tag.find(["b", "strong"], recursive=False)
        if b:
            return _norm(b.get_text(" "))
    return ""

def _extract_section_items(soup: BeautifulSoup, titles: List[str]) -> List[str]:
    host = soup.select_one("#job-description") or soup
    want = tuple(_norm(t) for t in titles)
    stop_set = tuple(_norm(t) for t in ALL_SECTION_TITLES)

    start = None
    for tag in host.find_all(["h2", "h3", "p", "strong", "b"]):
        if not _is_section_heading(tag):
            continue
        head = _heading_text(tag)
        if head.startswith(want):
            start = tag
            break

    items: List[str] = []
    if not start:
        for li in host.select("ul li"):
            txt = _clean(li.get_text(" "))
            if txt and txt not in items:
                items.append(txt)
            if len(items) >= 12:
                break
        return items

    def add_lines_from_p(p):
        raw = p.get_text("\n")
        for line in [x.strip() for x in raw.split("\n")]:
            if not line:
                continue
            ln = re.sub(r"^[•\-\–—·]+\s*", "", line)
            if _norm(ln).startswith(stop_set):
                continue
            if ln and ln not in items:
                items.append(ln)

    for sib in start.next_siblings:
        name = getattr(sib, "name", None)
        if not name:
            continue
        if _is_section_heading(sib) and _heading_text(sib).startswith(stop_set):
            break
        if name in ("ul", "ol"):
            for li in sib.find_all("li"):
                txt = _clean(li.get_text(" "))
                if txt and txt not in items:
                    items.append(txt)
            continue
        if name == "p":
            if _is_section_heading(sib) and _heading_text(sib).startswith(stop_set):
                break
            add_lines_from_p(sib)

    if not items and start.name == "p":
        add_lines_from_p(start)

    if not items:
        for li in host.select("ul li"):
            txt = _clean(li.get_text(" "))
            if txt and txt not in items:
                items.append(txt)

    return [i for i in items if len(i) > 1][:12]

def _extract_company(soup: BeautifulSoup, page_text: str) -> str:
    a = soup.select_one("a[href*='/company/']")
    if a:
        return _clean(a.get_text(" "))
    og = soup.select_one('meta[property="og:description"]')
    if og and og.get("content"):
        m = re.search(r"компанія\s+(.+?)(?:[,—-]|робота|дистанційно)", og["content"], re.I)
        if m:
            return _clean(m.group(1))
    m2 = re.search(r"компанія\s+([^\n]+)", page_text, re.I)
    if m2:
        return _clean(m2.group(1).split("робота")[0].split("дистанційно")[0])
    return "—"

def _extract_salary(soup: BeautifulSoup, page_text: str) -> str:
    pattern = r"((?:від|до)?\s*\d[\d\s]*\s*(?:–|-)\s*\d[\d\s]*\s*грн|від\s*\d[\д\s]*\s*грн|до\s*\d[\д\s]*\s*грн|\d[\д\s]*\s*грн|₴\s*\d[\д\s]*)"
    og = soup.select_one('meta[property="og:description"]')
    if og and og.get("content"):
        m = re.search(pattern, og["content"], re.I)
        if m:
            return _clean(m.group(1))
    m2 = re.search(pattern, page_text, re.I)
    return _clean(m2.group(1)) if m2 else "—"

def _extract_posted(soup: BeautifulSoup, page_text: str) -> str:
    t = soup.select_one("time[datetime]")
    if t and t.get("datetime"):
        dt = t["datetime"].strip()
        return dt.replace("T", " ").split(" ")[0]
    m = re.search(r"Вакансія від\s+([^\n]+?)(?:\.|$)", page_text, re.I)
    return _clean(m.group(1)) if m else "—"

def _extract_employment(soup: BeautifulSoup, page_text: str) -> str:
    pills = set()
    h1 = soup.find("h1")
    if h1:
        for sib in h1.find_all_next(limit=60):
            txt = _clean(getattr(sib, "get_text", lambda *_: "")(" "))
            for kw in EMPLOYMENT_KEYWORDS:
                if kw in txt:
                    pills.add(kw)
    for kw in EMPLOYMENT_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", page_text):
            pills.add(kw)
    if not pills:
        return "—"
    order = {k: i for i, k in enumerate(EMPLOYMENT_KEYWORDS)}
    return ", ".join(sorted(pills, key=lambda x: order.get(x, 999)))

def scrape_workua_job(url: str) -> Dict:
    proxy = _pick_proxy()
    html = _get_html(url, proxy)
    soup = BeautifulSoup(html, "html.parser")
    page_text = _clean(soup.get_text(" "))
    h1 = soup.find("h1")
    title = _clean(h1.get_text(" ")) if h1 else "—"
    company = _extract_company(soup, page_text)
    salary = _extract_salary(soup, page_text)
    posted = _extract_posted(soup, page_text)
    employment = _extract_employment(soup, page_text)
    tasks = _extract_section_items(soup, SECTION_TITLES["tasks"])
    expectations = _extract_section_items(soup, SECTION_TITLES["expect"])
    description: List[str] = []
    desc = soup.select_one("#job-description") or soup.select_one("div.card.wordwrap")
    if desc:
        for p in desc.find_all("p"):
            txt = _clean(p.get_text(" "))
            if txt:
                description.append(txt)
            if len(description) >= 3:
                break
    return {
        "url": url,
        "title": title or "—",
        "company": company or "—",
        "salary": salary or "—",
        "posted": posted or "—",
        "employment": employment or "—",
        "tasks": tasks[:12],
        "expectations": expectations[:12],
        "description": description[:3],
    }

if __name__ == "__main__":
    q = "remote python django"
    from pprint import pprint
    rows = search_workua_detailed(q, limit=5)
    print("FOUND:", len(rows))
    for r in rows:
        print("-", r["title"], "—", r["company"], "—", r["salary"], "—", r["employment"])
    if rows:
        pprint(scrape_workua_job(rows[0]["url"]))
