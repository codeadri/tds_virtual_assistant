# tds_scraper.py (Modified with FTS5 integration)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import sqlite3
import time
import re
from datetime import datetime

# ========== CONFIG ==========
TDS_MAIN_URL = "https://tds.s-anand.net/#/2025-01/"
DISCOURSE_URL = "https://discourse.onlinedegree.iitm.ac.in/c/courses/tds-kb/34"
DISCOURSE_DATE_RANGE = ("2025-01-01", "2025-04-14")  # inclusive
DB_PATH = "tds_virtual_ta.db"

# ========== SETUP SELENIUM ==========
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
driver = webdriver.Chrome(options=options)

# ========== INIT DB ==========
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Create main content table
c.execute('''CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    description TEXT
)''')

# Create FTS virtual table
c.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(description, url UNINDEXED)''')
conn.commit()

# Create other scraper tables
c.execute('''CREATE TABLE IF NOT EXISTS course_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    title TEXT,
    description TEXT,
    content TEXT,
    source_url TEXT,
    scraped_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS discourse_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    author TEXT,
    date TEXT,
    content TEXT,
    permalink TEXT UNIQUE,
    scraped_at TEXT
)''')
conn.commit()

# ========== SCRAPE COURSE CONTENT ==========
def scrape_course_links(main_url):
    driver.get(main_url)
    time.sleep(3)
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    links = soup.find_all('a', href=True)
    records = []
    for link in links:
        url = link['href']
        if not url.startswith("http"):
            continue
        title = link.get_text(strip=True)
        description = link.find_parent('p').get_text(strip=True) if link.find_parent('p') else ""
        records.append((url, title, description))
    return records

def scrape_and_store_course_pages():
    records = scrape_course_links(TDS_MAIN_URL)
    for url, title, description in records:
        try:
            driver.get(url)
            time.sleep(2)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            content = soup.get_text("\n", strip=True)
            c.execute('''INSERT OR REPLACE INTO course_content (url, title, description, content, source_url, scraped_at)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (url, title, description, content, TDS_MAIN_URL, datetime.now().isoformat()))
            # Also store in content and FTS
            c.execute('''INSERT OR REPLACE INTO content (url, description) VALUES (?, ?)''', (url, content))
            c.execute('''INSERT OR REPLACE INTO content_fts (rowid, description, url) 
                         VALUES ((SELECT id FROM content WHERE url = ?), ?, ?)''', (url, content, url))
        except Exception as e:
            print(f"Error scraping {url}: {e}")
    conn.commit()

# ========== SCRAPE DISCOURSE POSTS ==========
def parse_discourse_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d")

def scrape_discourse():
    driver.get(DISCOURSE_URL)
    time.sleep(5)
    SCROLL_PAUSE_TIME = 2
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_TIME)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    topics = soup.select('a.title')
    for topic in topics:
        href = topic.get('href')
        full_url = "https://discourse.onlinedegree.iitm.ac.in" + href
        try:
            driver.get(full_url)
            time.sleep(3)
            page_soup = BeautifulSoup(driver.page_source, 'html.parser')
            title = page_soup.find('title').get_text(strip=True)
            posts = page_soup.select('.topic-post')
            for post in posts:
                author = post.select_one('.creator a span').text if post.select_one('.creator a span') else ""
                date_elem = post.select_one('time')
                date = date_elem.get('datetime', '')[:10] if date_elem else ""
                if not date or not (DISCOURSE_DATE_RANGE[0] <= date <= DISCOURSE_DATE_RANGE[1]):
                    continue
                content = post.select_one('.cooked')
                text = content.get_text("\n", strip=True) if content else ""
                c.execute('''INSERT OR IGNORE INTO discourse_posts (title, author, date, content, permalink, scraped_at)
                             VALUES (?, ?, ?, ?, ?, ?)''',
                          (title, author, date, text, full_url, datetime.now().isoformat()))
                # Also add to content and FTS
                c.execute('''INSERT OR REPLACE INTO content (url, description) VALUES (?, ?)''', (full_url, text))
                c.execute('''INSERT OR REPLACE INTO content_fts (rowid, description, url)
                             VALUES ((SELECT id FROM content WHERE url = ?), ?, ?)''', (full_url, text, full_url))
        except Exception as e:
            print(f"Error scraping Discourse post {full_url}: {e}")
    conn.commit()

# ========== RUN SCRAPERS ==========
if __name__ == "__main__":
    print("Scraping course content...")
    scrape_and_store_course_pages()
    print("Scraping Discourse posts...")
    scrape_discourse()
    print("Done.")
    driver.quit()
    conn.close()
import subprocess
subprocess.run(["python", "sync_to_fts.py"])
