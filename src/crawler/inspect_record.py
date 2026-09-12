import json
from pathlib import Path

from playwright.sync_api import sync_playwright


INPUT_FILE = Path("data/raw/metadata/record_urls.json")


def load_first_record():
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        records = json.load(file)

    if not records:
        raise ValueError("Nenhum registro encontrado em record_urls.json")

    return records[0]


def inspect_record():
    record_url = load_first_record()

    print("=" * 60)
    print("REGISTRO")
    print(record_url)
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        page.goto(
            record_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        print("\nTítulo da página:")
        print(page.title())

        print("\nURL:")
        print(page.url)

        print("\n" + "=" * 60)
        print("TEXTO DA PÁGINA")
        print("=" * 60)

        body_text = page.locator("body").inner_text()

        print(body_text[:10000])

        print("\n" + "=" * 60)
        print("LINKS ENCONTRADOS")
        print("=" * 60)

        links = page.locator("a[href]")

        for i in range(links.count()):
            link = links.nth(i)

            href = link.get_attribute("href")

            try:
                text = link.inner_text().strip()
            except Exception:
                text = ""

            if href:
                print(
                    f"\nTexto: {text[:100]}"
                    f"\nURL: {href}"
                )

        browser.close()


if __name__ == "__main__":
    inspect_record()