"""
publish_period.py — Pinterest pin publisher
Publie les pins du slot horaire courant depuis les CSVs
Concu pour GitHub Actions (token via env var)
"""

import os, sys, csv, json, time, traceback
from datetime import date, datetime, timezone, timedelta

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DONE_FILE = os.path.join(BASE_DIR, "published_done.json")
LOG_FILE  = os.path.join(BASE_DIR, "publish_log.txt")

PINTEREST_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")


def log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] {msg}\n")
    except Exception:
        pass


def load_done():
    if not os.path.exists(DONE_FILE):
        return {}
    try:
        with open(DONE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_done(done):
    with open(DONE_FILE, "w", encoding="utf-8") as f:
        json.dump(done, f, indent=2)


def get_board_id(board_name, headers, board_cache):
    if board_name in board_cache:
        return board_cache[board_name]
    import requests
    for attempt in range(3):
        try:
            r = requests.get(
                "https://api.pinterest.com/v5/boards",
                headers=headers,
                params={"page_size": 100},
                timeout=30
            )
            if r.status_code == 200:
                for board in r.json().get("items", []):
                    board_cache[board["name"]] = board["id"]
                return board_cache.get(board_name)
        except Exception as e:
            log(f"  get_board_id erreur tentative {attempt+1}: {e}")
        time.sleep(5)
    return None


def publish_pin(title, description, board_id, image_url, link, headers):
    import requests
    payload = {
        "title":        title[:100],
        "description":  description[:500],
        "board_id":     board_id,
        "media_source": {"source_type": "image_url", "url": image_url},
        "link":         link,
    }
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.pinterest.com/v5/pins",
                json=payload, headers=headers, timeout=30
            )
            return r.status_code, r.json()
        except Exception as e:
            log(f"  publish_pin erreur tentative {attempt+1}: {e}")
            time.sleep(5)
    return 0, {"error": "echec apres 3 tentatives"}


def main():
    if not PINTEREST_TOKEN:
        log("ERREUR: PINTEREST_ACCESS_TOKEN non defini")
        sys.exit(1)

    # Heure Tunisia = UTC+1
    tz_tunis  = timezone(timedelta(hours=1))
    now_utc   = datetime.now(timezone.utc)
    now_tunis = now_utc.astimezone(tz_tunis)

    # Déterminer le slot horaire
    if len(sys.argv) >= 3:
        target_date = sys.argv[1]
        period      = sys.argv[2]
    else:
        target_date = now_tunis.strftime("%Y-%m-%d")
        done = load_done()
        slots = ["08h", "17h"]
        period = None
        for s in slots:
            key = f"{target_date}_{s}"
            if not done.get(key):
                period = s
                break
        if not period:
            log(f"Les 2 slots de {target_date} sont deja publies - skip")
            sys.exit(0)
        log(f"UTC {now_utc.hour}h{now_utc.minute:02d} -> prochain slot non publie: {period}")

    csv_file   = os.path.join(BASE_DIR, "csvs", f"period_{target_date}_{period}.csv")
    period_key = f"{target_date}_{period}"

    log(f"=== Pinterest Publisher {target_date} {period} ===")

    if not os.path.exists(csv_file):
        log(f"Pas de CSV pour {period_key} — rien a publier")
        sys.exit(0)

    done = load_done()
    if done.get(period_key):
        log(f"Deja publie: {period_key} — skip")
        sys.exit(0)

    headers = {
        "Authorization": f"Bearer {PINTEREST_TOKEN}",
        "Content-Type":  "application/json"
    }

    # Charger le cache boards
    board_cache_file = os.path.join(BASE_DIR, "boards.json")
    board_cache = {}
    if os.path.exists(board_cache_file):
        try:
            with open(board_cache_file, "r", encoding="utf-8") as f:
                board_cache = json.load(f)
        except Exception:
            pass

    # Lire les pins du CSV
    pins = []
    with open(csv_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pins.append(row)

    log(f"{len(pins)} pins a publier")

    published = 0
    errors    = 0

    pin_images_dir = os.path.join(BASE_DIR, "pin_images")
    local_pins = sorted(f for f in os.listdir(pin_images_dir) if f.endswith(".png")) if os.path.isdir(pin_images_dir) else []
    pin_img_idx_file = os.path.join(BASE_DIR, "pin_img_idx.json")
    try:
        with open(pin_img_idx_file, "r") as f:
            pin_img_state = json.load(f)
    except Exception:
        pin_img_state = {"idx": 0}

    for i, pin in enumerate(pins, 1):
        title      = pin.get("title", "")
        desc       = pin.get("description", "")
        board_name = pin.get("board", "")
        image_url  = pin.get("image", "")
        link       = pin.get("link", "https://smoothie.thehappy-healthy-life.com")

        if local_pins:
            idx = pin_img_state["idx"] % len(local_pins)
            image_url = f"https://raw.githubusercontent.com/dali-aoun/pinterest-scheduler/refs/heads/master/pin_images/{local_pins[idx]}"
            pin_img_state["idx"] = idx + 1

        board_id = get_board_id(board_name, headers, board_cache)
        if not board_id:
            log(f"  [{i}] ERREUR board introuvable: {board_name}")
            errors += 1
            continue

        status, resp = publish_pin(title, desc, board_id, image_url, link, headers)
        if status in (200, 201):
            log(f"  [{i}] OK: {title[:60]}")
            published += 1
        else:
            log(f"  [{i}] ERREUR {status}: {resp}")
            errors += 1

        if i < len(pins):
            time.sleep(3)

    # Sauvegarder le cache boards mis a jour
    try:
        with open(board_cache_file, "w", encoding="utf-8") as f:
            json.dump(board_cache, f, indent=2)
    except Exception:
        pass

    if local_pins:
        try:
            with open(pin_img_idx_file, "w") as f:
                json.dump(pin_img_state, f)
        except Exception:
            pass

    if published > 0:
        done[period_key] = {
            "published": published,
            "errors":    errors,
            "total":     len(pins),
            "at":        datetime.utcnow().isoformat()
        }
        save_done(done)
    else:
        log(f"ATTENTION: 0 pins publies, slot NON marque comme fait (sera reessaye)")
    log(f"=== Termine: {published} publies | {errors} erreurs ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(f"EXCEPTION:\n{traceback.format_exc()}")
        sys.exit(1)
