"""
publish_period.py — Pinterest auto-publisher (100% autonomous)
10 pins/jour: 2 slots x 5 pins (4 standard + 1 idea pin)
No CSV dependency — content from pin_content.json + Canva images
"""

import os, sys, json, time, random, traceback
from datetime import date, datetime, timezone, timedelta

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DONE_FILE = os.path.join(BASE_DIR, "published_done.json")
LOG_FILE  = os.path.join(BASE_DIR, "publish_log.txt")
STATE_FILE = os.path.join(BASE_DIR, "pin_auto_state.json")
CONTENT_FILE = os.path.join(BASE_DIR, "pin_content.json")
IMAGES_DIR = os.path.join(BASE_DIR, "pin_images")

PINTEREST_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
FUNNEL_URL = "https://smoothie.thehappy-healthy-life.com"
REPO_RAW = "https://raw.githubusercontent.com/dali-aoun/pinterest-scheduler/refs/heads/master/pin_images"


def log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] {msg}\n")
    except Exception:
        pass


def load_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_board_id(board_name, headers, board_cache):
    if board_name in board_cache:
        return board_cache[board_name]
    import requests
    for attempt in range(3):
        try:
            r = requests.get(
                "https://api.pinterest.com/v5/boards",
                headers=headers, params={"page_size": 100}, timeout=30
            )
            if r.status_code == 200:
                for board in r.json().get("items", []):
                    board_cache[board["name"]] = board["id"]
                return board_cache.get(board_name)
        except Exception as e:
            log(f"  get_board_id error attempt {attempt+1}: {e}")
        time.sleep(5)
    return None


def publish_standard_pin(title, description, board_id, image_url, link, headers):
    import requests
    payload = {
        "title": title[:100],
        "description": description[:500],
        "board_id": board_id,
        "media_source": {"source_type": "image_url", "url": image_url},
        "link": link,
    }
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.pinterest.com/v5/pins",
                json=payload, headers=headers, timeout=30
            )
            return r.status_code, r.json()
        except Exception as e:
            log(f"  publish error attempt {attempt+1}: {e}")
            time.sleep(5)
    return 0, {"error": "failed after 3 attempts"}


def publish_idea_pin(title, pages_text, board_id, image_urls, headers):
    import requests
    items = []
    for i, img_url in enumerate(image_urls):
        items.append({"url": img_url})

    payload = {
        "title": title[:100],
        "description": " | ".join(pages_text)[:500],
        "board_id": board_id,
        "media_source": {
            "source_type": "multiple_images",
            "items": items
        },
    }
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.pinterest.com/v5/pins",
                json=payload, headers=headers, timeout=30
            )
            return r.status_code, r.json()
        except Exception as e:
            log(f"  idea pin error attempt {attempt+1}: {e}")
            time.sleep(5)
    return 0, {"error": "failed after 3 attempts"}


def get_image_url(state):
    local_pins = sorted(f for f in os.listdir(IMAGES_DIR) if f.endswith(".png")) if os.path.isdir(IMAGES_DIR) else []
    if not local_pins:
        return None
    idx = state.get("img_idx", 0) % len(local_pins)
    state["img_idx"] = idx + 1
    return f"{REPO_RAW}/{local_pins[idx]}"


def main():
    if not PINTEREST_TOKEN:
        log("ERROR: PINTEREST_ACCESS_TOKEN not set")
        sys.exit(1)

    tz_tunis = timezone(timedelta(hours=1))
    now_utc = datetime.now(timezone.utc)
    now_tunis = now_utc.astimezone(tz_tunis)

    if len(sys.argv) >= 3:
        target_date = sys.argv[1]
        period = sys.argv[2]
    else:
        target_date = now_tunis.strftime("%Y-%m-%d")
        done = load_json(DONE_FILE)
        slots = ["08h", "17h"]
        period = None
        for s in slots:
            key = f"{target_date}_{s}"
            if not done.get(key):
                period = s
                break
        if not period:
            log(f"Both slots for {target_date} already published - skip")
            sys.exit(0)
        log(f"UTC {now_utc.hour}h{now_utc.minute:02d} -> next unpublished slot: {period}")

    period_key = f"{target_date}_{period}"
    log(f"=== Pinterest Auto-Publisher {target_date} {period} ===")

    done = load_json(DONE_FILE)
    if done.get(period_key, {}).get("published", 0) > 0:
        log(f"Already published: {period_key} - skip")
        sys.exit(0)

    content = load_json(CONTENT_FILE)
    boards_content = content.get("boards", {})
    idea_sets = content.get("idea_pin_sets", [])
    state = load_json(STATE_FILE, {"content_idx": 0, "img_idx": 0, "idea_idx": 0, "board_order_idx": 0})

    headers = {
        "Authorization": f"Bearer {PINTEREST_TOKEN}",
        "Content-Type": "application/json"
    }

    board_cache_file = os.path.join(BASE_DIR, "boards.json")
    board_cache = load_json(board_cache_file)

    board_names = list(boards_content.keys())
    if not board_names:
        log("ERROR: no board content found in pin_content.json")
        sys.exit(1)

    published = 0
    errors = 0

    # Publish 4 standard pins from different boards
    for i in range(4):
        board_idx = (state.get("board_order_idx", 0) + i) % len(board_names)
        board_name = board_names[board_idx]
        pins_pool = boards_content[board_name]

        content_idx = state.get("content_idx", 0) % len(pins_pool)
        pin_data = pins_pool[content_idx]
        state["content_idx"] = content_idx + 1

        image_url = get_image_url(state)
        if not image_url:
            log(f"  [{i+1}] ERROR: no images available")
            errors += 1
            continue

        board_id = get_board_id(board_name, headers, board_cache)
        if not board_id:
            log(f"  [{i+1}] ERROR: board not found: {board_name}")
            errors += 1
            continue

        status, resp = publish_standard_pin(
            pin_data["title"], pin_data["desc"],
            board_id, image_url, FUNNEL_URL, headers
        )
        if status in (200, 201):
            log(f"  [{i+1}] OK [{board_name}]: {pin_data['title'][:50]}")
            published += 1
        else:
            log(f"  [{i+1}] ERROR {status}: {resp}")
            errors += 1
        time.sleep(3)

    # Publish 1 idea pin (multi-image, no link — boosts algorithm)
    if idea_sets:
        idea_idx = state.get("idea_idx", 0) % len(idea_sets)
        idea = idea_sets[idea_idx]
        state["idea_idx"] = idea_idx + 1

        idea_images = []
        for _ in range(min(len(idea["pages"]), 4)):
            img = get_image_url(state)
            if img:
                idea_images.append(img)

        if len(idea_images) >= 2:
            idea_board_idx = (state.get("board_order_idx", 0) + 4) % len(board_names)
            idea_board = board_names[idea_board_idx]
            idea_board_id = get_board_id(idea_board, headers, board_cache)

            if idea_board_id:
                status, resp = publish_idea_pin(
                    idea["title"], idea["pages"],
                    idea_board_id, idea_images, headers
                )
                if status in (200, 201):
                    log(f"  [5] OK IDEA PIN [{idea_board}]: {idea['title'][:50]}")
                    published += 1
                else:
                    log(f"  [5] IDEA PIN ERROR {status}: {resp}")
                    # Fallback: publish as standard pin instead
                    fallback_board_idx = (state.get("board_order_idx", 0) + 4) % len(board_names)
                    fb_board = board_names[fallback_board_idx]
                    fb_pins = boards_content[fb_board]
                    fb_idx = state.get("content_idx", 0) % len(fb_pins)
                    fb_pin = fb_pins[fb_idx]
                    state["content_idx"] = fb_idx + 1
                    fb_img = get_image_url(state)
                    fb_board_id = get_board_id(fb_board, headers, board_cache)
                    if fb_img and fb_board_id:
                        st2, rp2 = publish_standard_pin(fb_pin["title"], fb_pin["desc"], fb_board_id, fb_img, FUNNEL_URL, headers)
                        if st2 in (200, 201):
                            log(f"  [5] OK FALLBACK [{fb_board}]: {fb_pin['title'][:50]}")
                            published += 1
                        else:
                            log(f"  [5] FALLBACK ERROR {st2}: {rp2}")
                            errors += 1
                    else:
                        errors += 1
            else:
                errors += 1
        else:
            errors += 1

    state["board_order_idx"] = (state.get("board_order_idx", 0) + 5) % len(board_names)

    save_json(board_cache_file, board_cache)
    save_json(STATE_FILE, state)

    if published > 0:
        done[period_key] = {
            "published": published,
            "errors": errors,
            "total": 5,
            "at": datetime.utcnow().isoformat()
        }
        save_json(DONE_FILE, done)
    else:
        log(f"WARNING: 0 pins published, slot NOT marked as done (will retry)")

    log(f"=== Done: {published} published | {errors} errors ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(f"EXCEPTION:\n{traceback.format_exc()}")
        sys.exit(1)
