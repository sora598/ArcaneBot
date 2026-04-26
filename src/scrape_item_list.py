"""Scrape item names from the Sailor Piece value list page using Selenium.

This script extracts text from:
<h3 class="w-full truncate ... font-semibold ..."><span>Item Name</span></h3>

It scrolls the page in headless mode until no new items are loaded.

Output format:
{
  "items": ["Madoka Set", ...]
}
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://sailor-piece.vaultedvaluesx.com/value-list"
OUTPUT_PATH = Path(__file__).resolve().parent / "data" / "item_list.json"
TARGET_SELECTOR = "h3.w-full.truncate.px-1.text-center.font-semibold > span"


def build_driver() -> webdriver.Remote:
    """Create a headless browser driver, preferring Chrome and falling back to Edge."""
    try:
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        return webdriver.Chrome(options=chrome_options)
    except WebDriverException:
        edge_options = EdgeOptions()
        edge_options.add_argument("--headless=new")
        edge_options.add_argument("--disable-gpu")
        edge_options.add_argument("--window-size=1920,1080")
        return webdriver.Edge(options=edge_options)


def extract_item_names(url: str) -> List[str]:
    """Load page, auto-scroll until stable, then extract all matching item names."""
    driver = build_driver()
    try:
        driver.get(url)

        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, TARGET_SELECTOR)))

        # Keep scrolling until item count does not change for a few rounds.
        stable_rounds = 0
        last_count = 0
        max_rounds = 40
        for _ in range(max_rounds):
            elements = driver.find_elements(By.CSS_SELECTOR, TARGET_SELECTOR)
            current_count = len(elements)
            if current_count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = current_count

            if stable_rounds >= 3:
                break

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.0)

        raw_items = [el.text.strip() for el in driver.find_elements(By.CSS_SELECTOR, TARGET_SELECTOR)]
    except TimeoutException as exc:
        raise SystemExit("Timed out waiting for item cards to load.") from exc
    finally:
        driver.quit()

    # Preserve order while removing duplicates and empties.
    seen = set()
    unique_items: List[str] = []
    for name in raw_items:
        if name and name not in seen:
            seen.add(name)
            unique_items.append(name)

    return unique_items


def save_items(items: List[str], output_path: Path) -> None:
    """Save item names as JSON under key 'items'."""
    payload = {"items": items}
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    items = extract_item_names(URL)
    save_items(items, OUTPUT_PATH)
    print(f"Extracted {len(items)} items.")
    print(f"Saved JSON to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
