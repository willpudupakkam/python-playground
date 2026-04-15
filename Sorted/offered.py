import re
import requests
from bs4 import BeautifulSoup
from functools import lru_cache

URL_AMATH = "https://uwaterloo.ca/applied-mathematics/current-undergraduates/undergraduate-course-list"
URL_PHYS = "https://uwaterloo.ca/physics-astronomy/undergraduate-students/undergraduate-phys-course-offerings"
URL_CS_BASE = "https://cs.uwaterloo.ca//current/courses/course_descriptions/index"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

@lru_cache(maxsize=8)
def _fetch_soup_for(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

@lru_cache(maxsize=1)
def _fetch_soup() -> BeautifulSoup:
    """Fetch and parse the AMATH course list page. Cached to avoid repeat downloads."""
    return _fetch_soup_for(URL_AMATH)

@lru_cache(maxsize=1)
def _fetch_soup_phys() -> BeautifulSoup:
    """Fetch and parse the PHYS course offerings page. Cached to avoid repeat downloads."""
    return _fetch_soup_for(URL_PHYS)

_DEF_ORDER = "FWS"  # canonical order

def _extract_terms(text: str, *, require_full_words: bool = False) -> str:
    """
    Normalize a term cell (e.g., "F, W, S" or "Fall, Winter") to a compact
    string using canonical order (FWS). Any missing letter means not offered.

    If require_full_words is True, only count whole-word matches for
    "Fall", "Winter", and "Spring" (or "Summer" as an alias for the May–Aug term).
    This avoids accidental matches where a lone 'S' appears inside other words.
    """
    t = (text or "").upper()
    if require_full_words:
        # Whole-word matches only
        has_f = re.search(r"\bFALL\b", t) is not None
        has_w = re.search(r"\bWINTER\b", t) is not None
        # UW sometimes writes Spring for the May–Aug term (sometimes Summer)
        has_s = (re.search(r"\bSPRING\b", t) is not None) or (re.search(r"\bSUMMER\b", t) is not None)
    else:
        has_f = ("F" in t) or ("FALL" in t)
        has_w = ("W" in t) or ("WINTER" in t)
        # UW sometimes writes Spring for the May–Aug term (sometimes Summer)
        has_s = ("S" in t) or ("SPRING" in t) or ("SUMMER" in t)
    flags = [has_f, has_w, has_s]
    return "".join(c for c, keep in zip(_DEF_ORDER, flags) if keep)

def get_amath_terms(course: str) -> str:
    """
    Given a course like 'AMATH 231', return a compact term string like 'F', 'FW', or 'FWS'.
    Assumes exact course code format (SUBJECT + space + CATALOG), as per the page's link text.
    Raises KeyError if the course is not found.
    """
    course_key = (course or "").strip().upper()
    if not re.match(r"^[A-Z]{2,}\s\d{3}[A-Z]?$", course_key):
        raise ValueError("Expected course in the form 'AMATH 333'.")

    soup = _fetch_soup()

    # Find the <a> whose visible text matches the exact course code
    link = soup.find("a", string=lambda s: isinstance(s, str) and s.strip().upper() == course_key)
    if not link:
        raise KeyError(f"Course '{course}' not found on the Applied Math course list page.")

    # Climb to its table row, then read the second <td> which is the Term column
    tr = link.find_parent("tr")
    if not tr:
        raise RuntimeError("Unexpected HTML: course link is not inside a <tr>.")

    tds = tr.find_all("td")
    if len(tds) < 2:
        raise RuntimeError("Unexpected HTML: could not locate the Term column (second <td>).")

    term_cell_text = tds[1].get_text(" ", strip=True)
    return _extract_terms(term_cell_text)


def get_phys_terms(course: str) -> str:
    """
    Given a course like 'PHYS 111', return a compact term string like 'F', 'FW', or 'FWS'.
    Assumes exact course code text in the first column of the table.
    """
    course_key = (course or "").strip().upper()
    if not re.match(r"^PHYS\s\d{3}[A-Z]?$", course_key):
        raise ValueError("Expected course in the form 'PHYS 121'.")

    soup = _fetch_soup_phys()

    # Find the row whose first td is exactly the course code
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        first = tds[0].get_text(strip=True).upper()
        if first == course_key:
            term_text = tds[1].get_text(" ", strip=True)
            return _extract_terms(term_text)

    raise KeyError(f"Course '{course}' not found on the PHYS course offerings page.")


def get_cs_terms(course: str) -> str:
    """
    Given a course like 'CS 230', fetch the CS course page with the TermsOfOffering anchor
    and parse the "Next offerings are: ..." text to return a compact term string like 'F', 'FW', or 'FWS'.
    The request URL format is: `${URL_CS_BASE}?course=CS230#TermsOfOffering` (space removed).
    """
    course_key = (course or "").strip().upper()
    if not re.match(r"^CS\s\d{3}[A-Z]?$", course_key):
        raise ValueError("Expected course in the form 'CS 230'.")

    subject, number = course_key.split()
    query_code = f"{subject}{number}"  # e.g., CS230
    url = f"{URL_CS_BASE}?course={query_code}#TermsOfOffering"

    soup = _fetch_soup_for(url)
    soup_str = str(soup)
    ind1 = soup_str.find(r"<i>")
    ind2 = soup_str.find(r"</i>")
    offerings_text = soup_str[ind1+3:ind2]

    return _extract_terms(offerings_text, require_full_words=True)


def get_terms_offered(course: str) -> str:
    """Master router: returns the terms string for AMATH, PHYS, or CS courses."""
    if not course or " " not in course:
        raise ValueError("Expected course like 'AMATH 333' or 'PHYS 121'.")
    subject = course.split()[0].upper()
    if subject == "AMATH":
        return get_amath_terms(course)
    if subject == "PHYS":
        return get_phys_terms(course)
    if subject == "CS":
        return get_cs_terms(course)
    raise ValueError(f"Unsupported subject '{subject}'. Only AMATH, PHYS, and CS are implemented.")
