"""
fill_new_boards.py — one-shot fill for 6 new Java Burn coffee boards
Publishes all 10 pins + 1 idea pin per board directly via Pinterest API
"""
import os, sys, json, time, traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTENT_FILE = os.path.join(BASE_DIR, "pin_content.json")
IMAGES_DIR = os.path.join(BASE_DIR, "pin_images")
REPO_RAW = "https://raw.githubusercontent.com/dali-aoun/pinterest-scheduler/refs/heads/master/pin_images"
PINTEREST_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")

NEW_BOARDS = [
    "Coffee & Weight Loss for Women",
    "Morning Coffee Ritual for Women 40+",
    "Java Burn Reviews & Results",
    "Coffee Metabolism Hacks",
    "Cortisol & Belly Fat Solutions",
    "Women\'s Hormonal Health & Coffee",
]

LINK = "https://coffee.thehappy-healthy-life.com/?utm_source=pinterest&utm_medium=pin&utm_campaign=organic"

def log(msg):
    print(msg, flush=True)

def get_image_urls():
    import os
    local_pins = sorted(f for f in os.listdir(IMAGES_DIR) if f.endswith(".png")) if os.path.isdir(IMAGES_DIR) else []
    return [f"{REPO_RAW}/{f}" for f in local_pins]

def get_board_ids(headers):
    import requests
    board_map = {}
    r = requests.get("https://api.pinterest.com/v5/boards", headers=headers, params={"page_size": 100}, timeout=30)
    if r.status_code == 200:
        for b in r.json().get("items", []):
            board_map[b["name"]] = b["id"]
    return board_map

def publish_pin(title, desc, board_id, image_url, headers):
    import requests
    payload = {
        "title": title[:100],
        "description": desc[:500],
        "board_id": board_id,
        "media_source": {"source_type": "image_url", "url": image_url},
        "link": LINK,
    }
    r = requests.post("https://api.pinterest.com/v5/pins", json=payload, headers=headers, timeout=30)
    return r.status_code, r.json()

def publish_idea_pin(title, pages, board_id, image_urls, headers):
    import requests
    items = [{"url": u} for u in image_urls[:4]]
    if len(items) < 2:
        return 0, {"error": "not enough images"}
    payload = {
        "title": title[:100],
        "description": " | ".join(pages)[:500],
        "board_id": board_id,
        "media_source": {"source_type": "multiple_image_urls", "items": items},
    }
    r = requests.post("https://api.pinterest.com/v5/pins", json=payload, headers=headers, timeout=30)
    return r.status_code, r.json()

def main():
    if not PINTEREST_TOKEN:
        log("ERROR: PINTEREST_ACCESS_TOKEN not set")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {PINTEREST_TOKEN}", "Content-Type": "application/json"}
    content = json.load(open(CONTENT_FILE, encoding="utf-8"))
    boards_content = content["boards"]
    idea_sets = {s["title"]: s for s in content["idea_pin_sets"]}
    image_urls = get_image_urls()

    if not image_urls:
        log("ERROR: no images in pin_images/")
        sys.exit(1)

    log("Fetching board IDs from Pinterest...")
    board_map = get_board_ids(headers)
    log(f"Found {len(board_map)} boards on Pinterest")

    total_published = 0
    total_errors = 0
    img_idx = 0

    for board_name in NEW_BOARDS:
        board_id = board_map.get(board_name)
        if not board_id:
            log(f"\n[SKIP] Board not found on Pinterest: {board_name}")
            total_errors += 1
            continue

        log(f"\n=== {board_name} (ID: {board_id}) ===")
        pins = boards_content.get(board_name, [])

        for i, pin in enumerate(pins):
            img_url = image_urls[img_idx % len(image_urls)]
            img_idx += 1
            status, resp = publish_pin(pin["title"], pin["desc"], board_id, img_url, headers)
            if status in (200, 201):
                log(f"  [{i+1}/10] OK: {pin['title'][:55]}")
                total_published += 1
            else:
                log(f"  [{i+1}/10] ERROR {status}: {resp.get('message',resp)[:80]}")
                total_errors += 1
            time.sleep(2)

        # Idea pin for this board
        idea = None
        for s in content["idea_pin_sets"]:
            # Match by board thematic
            if board_name.split()[0].lower() in s["title"].lower() or any(w in s["title"] for w in board_name.split()[:2]):
                idea = s
                break
        if not idea:
            idea = content["idea_pin_sets"][NEW_BOARDS.index(board_name) % len(content["idea_pin_sets"])]

        idea_imgs = [image_urls[(img_idx + j) % len(image_urls)] for j in range(4)]
        img_idx += 4
        status, resp = publish_idea_pin(idea["title"], idea["pages"], board_id, idea_imgs, headers)
        if status in (200, 201):
            log(f"  [IDEA] OK: {idea['title'][:55]}")
            total_published += 1
        else:
            log(f"  [IDEA] ERROR {status}: {resp.get('message',resp)[:80]}")
            total_errors += 1
        time.sleep(3)

    log(f"\n=== FILL COMPLETE: {total_published} published | {total_errors} errors ===")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(f"EXCEPTION:\n{traceback.format_exc()}")
        sys.exit(1)
