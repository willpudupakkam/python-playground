import re
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# Catalog root (SPA). We navigate here, use the in-page combobox search, then open the course page.
CAL_ROOT = "https://uwaterloo.ca/academic-calendar/undergraduate-studies/catalog"

def extract_course_codes(prereq_lines):
    codes = []
    pattern = re.compile(r"\b([A-Z]{2,5})\s*-?\s*(\d{2,3}[A-Z]?)\b")

    for line in prereq_lines:
        match = pattern.search(line)
        if match:
            subject, number = match.groups()
            codes.append(f"{subject} {number}")

    return codes

def _split_to_codes(text: str):
    if not text:
        return []
    return extract_course_codes(text.split('\n'))

async def _get_adjacent_block_text(page, heading_text: str) -> str:
    from playwright.async_api import TimeoutError as PWTimeout
    try:
        h = page.get_by_role("heading", level=3, name=heading_text)
        await h.wait_for(timeout=4000)
    except PWTimeout:
        try:
            h = page.get_by_role("heading", name=heading_text)
            await h.wait_for(timeout=4000)
        except PWTimeout:
            return ""
    try:
        div = h.locator("xpath=following-sibling::*[1]").first
        await div.wait_for(timeout=3000)
        return (await div.inner_text()).strip()
    except PWTimeout:
        return ""

async def get_reqs(course_code: str, headless: bool = True, debug: bool = False) -> dict:
    """
    1) Open the Undergraduate Studies catalog SPA
    2) Use the "Search Calendar" combobox to find the exact course (e.g., "AMATH 333")
    3) Open the course page
    4) Find the H3 heading with exact text "Prerequisites" and return the text of the
       immediately following sibling <div> (the list of courses)
    """
    m = re.match(r"\s*([A-Za-z]+)\s*-?\s*(\d+[A-Za-z]?)\s*$", course_code)
    if not m:
        raise ValueError(f"Invalid course code: {course_code}")
    subject, number = m.group(1).upper(), m.group(2).upper()
    exact_code = f"{subject} {number}"
    print(f'Finding requisite info for {exact_code}...')
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        # 1) Go to catalog root
        await page.goto(CAL_ROOT, wait_until="domcontentloaded")
        # give the SPA a brief moment to bootstrap (reduces flakiness on some networks)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass

        # 2) Use the correct combobox input with placeholder "Search Calendar"
        search = page.locator('input[role="combobox"][placeholder="Search Calendar"]').first
        await search.wait_for(timeout=15000)
        await search.fill(exact_code)

        # 3) Prefer selecting the autocomplete option for the exact code; otherwise go to results and click the link
        try:
            listbox = page.locator('[role="listbox"]').first
            await listbox.wait_for(timeout=6000)
            # Pick the option whose accessible name starts with the exact course code
            option = page.get_by_role("option", name=re.compile(rf"^{subject}\s*{re.escape(number)}\b", re.I)).first
            await option.wait_for(timeout=6000)
            await option.click()
        except PWTimeout:
            # Fallback: press Enter to go to results, then click the course link
            await search.press("Enter")
            hit = page.get_by_role("link", name=re.compile(rf"^{subject}\s*{re.escape(number)}\b", re.I)).first
            await hit.wait_for(timeout=15000)
            await hit.click()

        # 4) Confirm we are on the course page by locating a heading containing the course code
        course_heading = page.get_by_role("heading", name=re.compile(rf"{subject}\s*{re.escape(number)}\b", re.I))
        await course_heading.wait_for(timeout=15000)

        # 5) Pull the Prerequisites and Corequisites blocks (if present)
        prereq_text = await _get_adjacent_block_text(page, "Prerequisites")
        coreq_text = await _get_adjacent_block_text(page, "Corequisites")

        if debug:
            try:
                await page.screenshot(path="course_debug.png", full_page=True)
                html = await page.content()
                with open("course_debug.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

        await browser.close()

    prerequisites = _split_to_codes(prereq_text)
    corequisites = _split_to_codes(coreq_text)
    return {"course": exact_code, "prerequisites": prerequisites, "corequisites": corequisites}