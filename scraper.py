import requests
import json
import hashlib
import re
import time
import os
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ─────────────────────────────────────────────────────────────────────────────
# TIMEZONE
# ─────────────────────────────────────────────────────────────────────────────

VN_TZ       = timezone(timedelta(hours=7))
LIVE_BEFORE = timedelta(minutes=15)


def now_vn() -> datetime:
    return datetime.now(tz=VN_TZ)


def parse_kickoff(start_time: str) -> datetime | None:
    """Parse ISO startTime từ API (VD: 2026-05-17T21:00:00) về datetime VN."""
    if not start_time:
        return None
    try:
        # API trả về giờ UTC, cộng thêm 7h cho VN
        dt = datetime.fromisoformat(start_time.replace("Z", ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(VN_TZ)
    except Exception:
        return None


def calc_is_live(is_live_flag: bool, start_time: str) -> bool:
    if is_live_flag:
        return True
    kickoff = parse_kickoff(start_time)
    if kickoff is None:
        return False
    return now_vn() >= (kickoff - LIVE_BEFORE)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://sv1.bugio9.live/",
}

BASE_URL   = "https://sv1.bugio9.live"
API_LIST   = "https://sv.bugiotv.xyz/internal/api/matches"

THUMBS_DIR    = "thumbs"
REPO_RAW      = os.environ.get("REPO_RAW", "")
THUMB_VERSION = "v1"

# Phân loại theo tournamentName
VOLLEYBALL_KEYWORDS = ["bóng chuyền", "volleyball", "vtv", "binh dien", "bình điền"]
BASKETBALL_KEYWORDS = ["bóng rổ", "basketball", "nba", "euroleague"]
TENNIS_KEYWORDS     = ["tennis", "atp", "wta", "grand slam"]
BADMINTON_KEYWORDS  = ["cầu lông", "badminton", "bwf"]
ESPORT_KEYWORDS     = ["esport", "e-sport", "lol", "dota", "cs:go", "valorant"]
COMBAT_KEYWORDS     = ["võ thuật", "boxing", "ufc", "mma", "kickboxing"]
BASEBALL_KEYWORDS   = ["bóng chày", "baseball", "mlb"]

CATE_MAP = {
    "football":   "⚽ Bóng Đá",
    "basketball": "🏀 Bóng Rổ",
    "tennis":     "🎾 Tennis",
    "bongchuyen": "🏐 Bóng Chuyền",
    "esport":     "🎮 Esport",
    "caulong":    "🏸 Cầu Lông",
    "vothuat":    "🥊 Võ Thuật",
    "bongchay":   "⚾ Bóng Chày",
}

CATE_ORDER = ["football", "basketball", "tennis", "bongchuyen",
              "esport", "caulong", "vothuat", "bongchay"]

EXCLUDE_LEAGUES_AMERICA = [
    "mls", "major league soccer",
    "liga mx", "liga de expansion",
    "brasileirao", "brasileirão", "serie a brasil", "campeonato brasileiro", "brazilian",
    "copa do brasil",
    "argentine", "argentina", "liga profesional", "copa de la liga",
    "colombian", "colombia", "liga betplay",
    "chile", "ecuador", "peru", "venezuela", "paraguay", "uruguay", "bolivia",
    "inter miami", "new england", "la galaxy", "nycfc",
    "concacaf", "conmebol",
    "copa america", "copa sudamericana", "copa libertadores",
]


def is_america_league(league_name: str) -> bool:
    lower = league_name.lower()
    return any(kw in lower for kw in EXCLUDE_LEAGUES_AMERICA)


def detect_cate(tournament_name: str) -> str:
    lower = tournament_name.lower()
    if any(kw in lower for kw in VOLLEYBALL_KEYWORDS):
        return "bongchuyen"
    if any(kw in lower for kw in BASKETBALL_KEYWORDS):
        return "basketball"
    if any(kw in lower for kw in TENNIS_KEYWORDS):
        return "tennis"
    if any(kw in lower for kw in BADMINTON_KEYWORDS):
        return "caulong"
    if any(kw in lower for kw in ESPORT_KEYWORDS):
        return "esport"
    if any(kw in lower for kw in COMBAT_KEYWORDS):
        return "vothuat"
    if any(kw in lower for kw in BASEBALL_KEYWORDS):
        return "bongchay"
    return "football"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"


def fetch_image(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except Exception:
        return None


def parse_time_sort(start_time: str) -> int:
    kickoff = parse_kickoff(start_time)
    if kickoff:
        return kickoff.month * 10_000_000 + kickoff.day * 10_000 + kickoff.hour * 100 + kickoff.minute
    return 999_999_999


def is_within_24h(start_time: str, cate_type: str = "football") -> bool:
    if cate_type != "football":
        return True
    kickoff = parse_kickoff(start_time)
    if kickoff is None:
        return True
    now   = now_vn()
    lower = now - timedelta(hours=6)
    upper = now + timedelta(hours=24)
    return lower <= kickoff <= upper


def format_kickoff_display(start_time: str) -> tuple[str, str]:
    """Trả về (HH:MM, DD/MM) từ startTime ISO."""
    kickoff = parse_kickoff(start_time)
    if kickoff is None:
        return "", ""
    return kickoff.strftime("%H:%M"), kickoff.strftime("%d/%m")


# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, channel_id):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    cache_key = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    date_str  = now_vn().strftime("%Y%m%d")
    out_path  = f"{THUMBS_DIR}/{channel_id}_{logo_hash}_{date_str}.png"

    if os.path.exists(out_path):
        return out_path

    W, H = 1600, 1200
    HEADER_H = 180
    FOOTER_H = 160

    bg   = Image.new("RGB", (W, H), (245, 245, 248))
    draw = ImageDraw.Draw(bg)

    for y in range(HEADER_H, H - FOOTER_H):
        ratio = (y - HEADER_H) / (H - FOOTER_H - HEADER_H)
        gray  = int(248 - ratio * 18)
        draw.line([(0, y), (W, y)], fill=(gray, gray, gray + 4))

    draw.rectangle([(0, 0),            (W, HEADER_H)],  fill=(13, 20, 40))
    draw.rectangle([(0, H - FOOTER_H), (W, H)],         fill=(13, 20, 40))

    ACCENT = (220, 30, 40)
    draw.rectangle([(0, HEADER_H),         (W, HEADER_H + 5)],    fill=ACCENT)
    draw.rectangle([(0, H - FOOTER_H - 5), (W, H - FOOTER_H)],    fill=ACCENT)

    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs   = ImageFont.truetype(FONT_BOLD, 160)
        font_time = ImageFont.truetype(FONT_BOLD, 100)
        font_team = ImageFont.truetype(FONT_BOLD, 58)
    except Exception:
        font_vs = font_time = font_team = ImageFont.load_default()

    content_top = HEADER_H + 5
    content_bot = H - FOOTER_H - 5
    content_h   = content_bot - content_top

    logo_size     = 360
    name_h        = 120
    time_h        = 110
    gap_logo_name = 40
    gap_name_time = 60

    total_block_h = logo_size + gap_logo_name + name_h + gap_name_time + time_h
    block_top     = content_top + (content_h - total_block_h) // 2

    logo_y       = block_top
    name_block_y = logo_y + logo_size + gap_logo_name
    name_center  = name_block_y + name_h // 2
    time_y       = name_block_y + name_h + gap_name_time + time_h // 2

    if match.get("logo_a"):
        img = fetch_image(match["logo_a"])
        if img:
            img = img.resize((logo_size, logo_size), Image.LANCZOS)
            x   = W // 4 - logo_size // 2
            bg.paste(img, (x, logo_y), img)

    if match.get("logo_b"):
        img = fetch_image(match["logo_b"])
        if img:
            img = img.resize((logo_size, logo_size), Image.LANCZOS)
            x   = W * 3 // 4 - logo_size // 2
            bg.paste(img, (x, logo_y), img)

    draw.text((W // 2, logo_y + logo_size // 2), "VS",
              fill=ACCENT, font=font_vs, anchor="mm")

    def draw_team_name(text, cx):
        max_width = W // 2 - 60
        font_size = 58
        f = font_team
        while font_size >= 28:
            try:
                f = ImageFont.truetype(FONT_BOLD, font_size)
            except Exception:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= max_width:
                break
            font_size -= 3
        draw.text((cx, name_center), text, fill=(20, 20, 20), font=f, anchor="mm")

    if match.get("team_a"):
        draw_team_name(match["team_a"], W // 4)
    if match.get("team_b"):
        draw_team_name(match["team_b"], W * 3 // 4)

    time_fmt, date_fmt = format_kickoff_display(match.get("start_time", ""))
    time_display = f"{time_fmt} {date_fmt}".strip() if time_fmt else ""

    if time_display:
        font_size = 100
        f_time = font_time
        while font_size >= 40:
            try:
                f_time = ImageFont.truetype(FONT_BOLD, font_size)
            except Exception:
                f_time = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), time_display, font=f_time)
            if (bbox[2] - bbox[0]) <= W - 100:
                break
            font_size -= 4

        draw.text((W // 2 + 4, time_y + 4), time_display,
                  fill=ACCENT, font=f_time, anchor="mm")
        draw.text((W // 2, time_y), time_display,
                  fill=(15, 15, 15), font=f_time, anchor="mm")

    if match.get("league"):
        league_text = match["league"].upper()
        font_size   = 62
        f           = None
        while font_size >= 28:
            try:
                f = ImageFont.truetype(FONT_BOLD, font_size)
            except Exception:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), league_text, font=f)
            if (bbox[2] - bbox[0]) <= W - 60:
                break
            font_size -= 3
        draw.text((W // 2, HEADER_H // 2), league_text,
                  fill=(255, 255, 255), font=f, anchor="mm")

    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(180, 180, 180), width=3)
    bg.save(out_path, "PNG", optimize=True)
    return out_path


def cleanup_old_thumbs(days: int = 3):
    if not os.path.exists(THUMBS_DIR):
        return
    cutoff  = now_vn() - timedelta(days=days)
    removed = 0
    for fname in os.listdir(THUMBS_DIR):
        if not fname.endswith(".png"):
            continue
        m = re.search(r'_(\d{8})\.png$', fname)
        if not m:
            fpath = os.path.join(THUMBS_DIR, fname)
            try:
                os.remove(fpath)
                removed += 1
            except Exception:
                pass
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=VN_TZ)
        except ValueError:
            continue
        if file_date < cutoff:
            fpath = os.path.join(THUMBS_DIR, fname)
            try:
                os.remove(fpath)
                removed += 1
            except Exception:
                pass
    if removed:
        print(f"Da xoa {removed} thumbnail cu (>{days} ngay)")


# ─────────────────────────────────────────────────────────────────────────────
# FETCH API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_matches() -> list:
    """Lấy toàn bộ fixtures từ API (không lọc isPlaying)."""
    results = []
    page    = 1
    limit   = 50

    while True:
        try:
            url = f"{API_LIST}?limit={limit}&page={page}"
            res = requests.get(url, headers=HEADERS, timeout=15)
            data = res.json()

            items = []
            if isinstance(data, dict):
                items = data.get("data", []) or []
                # Nếu data là object đơn thay vì list
                if isinstance(items, dict):
                    items = [items]
            elif isinstance(data, list):
                items = data

            if not items:
                break

            results.extend(items)

            # Kiểm tra pagination — nếu ít hơn limit thì hết trang
            if len(items) < limit:
                break
            page += 1

        except Exception as e:
            print(f"  Loi fetch trang {page}: {e}")
            break

    return results


# ─────────────────────────────────────────────────────────────────────────────
# PARSE MATCHES
# ─────────────────────────────────────────────────────────────────────────────

def get_matches() -> list:
    raw_items = fetch_all_matches()
    matches   = []

    for item in raw_items:
        match_id   = str(item.get("id", ""))
        start_time = item.get("startTime", "")
        tournament = item.get("tournamentName", "")
        is_live_f  = item.get("isLive", False)

        home_club  = item.get("homeClub") or {}
        away_club  = item.get("awayClub") or {}
        team_a     = home_club.get("name", "") or item.get("homeClubName", "")
        team_b     = away_club.get("name", "") or item.get("awayClubName", "")
        logo_a     = home_club.get("logoUrl", "") or item.get("homeClubLogoUrl", "")
        logo_b     = away_club.get("logoUrl", "") or item.get("awayClubLogoUrl", "")

        commentator = item.get("commentator") or {}
        blv_name    = commentator.get("nickname", "")
        # Ưu tiên FHD, fallback HD
        stream_url  = (commentator.get("streamSourceFhd") or
                       commentator.get("streamSourceHd") or "")

        if not match_id:
            continue

        # Bỏ qua nếu không có BLV (chưa assign)
        if not blv_name and not stream_url:
            continue

        cate_type = detect_cate(tournament)

        if cate_type == "football" and is_america_league(tournament):
            continue

        if not is_within_24h(start_time, cate_type):
            continue

        is_live   = calc_is_live(is_live_f, start_time)
        time_sort = parse_time_sort(start_time)
        name      = item.get("title", "") or f"{team_a} vs {team_b}"

        matches.append({
            "match_id":   match_id,
            "cate_type":  cate_type,
            "name":       name,
            "start_time": start_time,
            "time_sort":  time_sort,
            "team_a":     team_a,
            "team_b":     team_b,
            "logo_a":     logo_a,
            "logo_b":     logo_b,
            "league":     tournament,
            "blv":        blv_name,
            "stream_url": stream_url,
            "is_live":    is_live,
            "is_hot":     item.get("isHot", False),
            "is_pinned":  item.get("isPinned", False),
        })

    matches.sort(key=lambda m: (0 if m["is_live"] else 1, m["time_sort"]))
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# BUILD CHANNEL JSON
# ─────────────────────────────────────────────────────────────────────────────

def build_channel(match: dict, thumb_url: str = "") -> dict:
    uid    = make_id(match["match_id"], "bg")
    src_id = make_id(match["match_id"], "src")
    ct_id  = make_id(match["match_id"], "ct")
    st_id  = make_id(match["match_id"], "st")

    stream_links = []
    if match["stream_url"]:
        lnk_id = make_id(match["stream_url"], "lnk")
        stream_links.append({
            "id":      lnk_id,
            "name":    "Link FHD",
            "type":    "hls",
            "default": True,
            "url":     match["stream_url"],
            "request_headers": [
                {"key": "Referer",    "value": "https://sv1.bugio9.live/"},
                {"key": "User-Agent", "value": "Mozilla/5.0"},
            ],
        })

    label_text  = "● LIVE" if match["is_live"] else "🕐 Sắp"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"

    time_fmt, date_fmt = format_kickoff_display(match["start_time"])
    display_name = match["name"]
    if time_fmt and date_fmt:
        display_name = f"{match['name']} | {time_fmt} {date_fmt}"
    elif time_fmt:
        display_name = f"{match['name']} | {time_fmt}"

    channel = {
        "id":            uid,
        "name":          display_name,
        "type":          "single",
        "display":       "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": label_text, "position": "top-left",
                    "color": "#00000080", "text_color": label_color}],
        "sources": [{
            "id":   src_id,
            "name": "BugioTV",
            "contents": [{
                "id":   ct_id,
                "name": match["name"],
                "streams": [{"id": st_id, "name": "BG", "stream_links": stream_links}],
            }],
        }],
        "org_metadata": {
            "league":    match.get("league",     ""),
            "team_a":    match.get("team_a",     ""),
            "team_b":    match.get("team_b",     ""),
            "logo_a":    match.get("logo_a",     ""),
            "logo_b":    match.get("logo_b",     ""),
            "start_time": match.get("start_time", ""),
            "blv":       match.get("blv",        ""),
            "is_live":   match["is_live"],
            "cate_type": match.get("cate_type",  ""),
        },
    }

    if thumb_url:
        channel["image"] = {
            "padding":          1,
            "background_color": "#ffffff",
            "display":          "contain",
            "url":              thumb_url,
            "width":            1600,
            "height":           1200,
        }

    return channel


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(THUMBS_DIR, exist_ok=True)
    cleanup_old_thumbs(days=3)
    print(f"Gio VN hien tai : {now_vn().strftime('%H:%M %d/%m/%Y')}")
    print("Lay danh sach tran tu BugioTV API...")

    matches = get_matches()

    live_count = sum(1 for m in matches if m["is_live"])
    print(f"Tong: {len(matches)} | LIVE: {live_count} | Sap: {len(matches) - live_count}\n")

    cate_channels = {cate: [] for cate in CATE_ORDER}

    for i, match in enumerate(matches):
        cate_type = match["cate_type"]
        status    = "LIVE" if match["is_live"] else "SAP"
        time_fmt, date_fmt = format_kickoff_display(match["start_time"])
        print(f"[{status} {i+1}/{len(matches)}] {match['name']} ({time_fmt} {date_fmt}) | BLV: {match['blv']}")

        if match["stream_url"]:
            print(f"    stream: DA CO ({match['stream_url'][:60]}...)")
        else:
            print(f"    stream: Chua co link")

        uid       = make_id(match["match_id"], "bg")
        cache_key = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
        logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]

        thumb_path = make_thumbnail(match, uid)
        thumb_url  = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else ""

        channel = build_channel(match, thumb_url)

        if cate_type not in cate_channels:
            cate_channels[cate_type] = []
        cate_channels[cate_type].append(channel)

        time.sleep(0.1)

    groups = []
    for cate_type in CATE_ORDER:
        channels = cate_channels.get(cate_type, [])
        if not channels:
            continue

        cate_label = CATE_MAP.get(cate_type, "🏅 Thể Thao")
        live_cnt   = sum(1 for ch in channels
                         if ch.get("org_metadata", {}).get("is_live", False))
        cate_name  = f"{cate_label} ({live_cnt} LIVE)" if live_cnt > 0 else cate_label

        groups.append({
            "id":            f"cate_{cate_type}",
            "name":          cate_name,
            "display":       "vertical",
            "grid_number":   2,
            "enable_detail": False,
            "channels":      channels,
        })

    for cate_type, channels in cate_channels.items():
        if cate_type not in CATE_ORDER and channels:
            live_cnt  = sum(1 for ch in channels
                            if ch.get("org_metadata", {}).get("is_live", False))
            cate_name = f"🏅 Thể Thao ({live_cnt} LIVE)" if live_cnt > 0 else "🏅 Thể Thao"
            groups.append({
                "id":            f"cate_{cate_type}",
                "name":          cate_name,
                "display":       "vertical",
                "grid_number":   2,
                "enable_detail": False,
                "channels":      channels,
            })

    output = {
        "id":          "bugio",
        "url":         "https://sv1.bugio9.live",
        "name":        "BugioTV",
        "color":       "#e53935",
        "grid_number": 3,
        "image":       {"type": "cover", "url": "https://sv1.bugio9.live/favicon.ico"},
        "groups":      groups,
    }

    staging = "output_staging.json"
    with open(staging, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(g["channels"]) for g in groups)

    def normalize(path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return json.dumps(d, sort_keys=True, ensure_ascii=False)
        except Exception:
            return ""

    old_norm = normalize("output.json")
    new_norm = normalize(staging)

    if old_norm != new_norm:
        os.replace(staging, "output.json")
        print(f"\nXong! {total} kenh, {len(groups)} mon the thao -> output.json (DA CAP NHAT)")
    else:
        os.remove(staging)
        print(f"\nXong! {total} kenh, {len(groups)} mon the thao -> Khong co thay doi, giu nguyen output.json")


if __name__ == "__main__":
    main()
