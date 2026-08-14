#!/usr/bin/env python3
"""Baut aus der grossen Provider-Playlist eine schlanke Live-Senderliste.

- nur Live-Streams (VOD /movie/ + /series/ fliegen raus)
- nur EN(UK) / USA / FR / IT / DE-Sprachraum (DE, AT, CH) + Adult
- Sport/FIFA/PPV bekommen eigene group-title Tags
- Qualitaets-Dubletten (SD/HD/FHD/HEVC/4K) werden auf die beste Variante reduziert
- tvg-id wird gegen die EPG-Quelle gemappt
"""
import argparse
import html
import os
import re
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--src", required=True, help="Roh-Playlist des Providers (.m3u)")
parser.add_argument("--epg-xml", required=True, help="lokal geladene XMLTV-Datei")
parser.add_argument("--epg-url", default="https://epg.best/24129-yquxim.xml",
                    help="EPG-URL, die in den #EXTM3U-Header geschrieben wird")
parser.add_argument("--out", default=os.path.join(REPO_ROOT, "control-plane", "iptv.m3u"))
args = parser.parse_args()

SRC = args.src
EPG_XML = args.epg_xml
EPG_URL = args.epg_url
OUT = args.out

# ---------------------------------------------------------------- Regionen
PREFIX_REGION = {
    "DE": "DE", "FIFA-DE": "DE", "OL-DE": "DE", "GERMANY HD": "DE", "GERMANY FHD": "DE",
    "AT": "AT", "FIFA-AT": "AT", "OL-AT": "AT",
    "SH": "CH", "FIFA-SH": "CH",
    "US": "US", "USA": "US", "USA-L": "US", "FIFA-US": "US", "OL-US": "US",
    "FIFA-UK": "UK", "OL-UK": "UK", "OL-IE": "UK",
    "FIFA-FR": "FR",
    "FIFA-IT": "IT",
    "XXX": "ADULT",
    # generische Sport-/Event-Prefixe -> Sprache wird ueber den Namen entschieden
    "PPV": "PPV", "VIP": "VIP",
    "SPORTS HD": "DE", "SPORTS FHD": "DE", "MUSIK HD": "DE", "MUSIK FHD": "DE",
    "KINDER HD": "DE", "KINDER FHD": "DE", "FILMS HD": "DE", "FILM FHD": "DE",
    "CHRISTMAS": "DROP", "XMAS": "DROP",
}

# PPV/VIP-Familien, die sprachlich nicht passen
PPV_DROP = re.compile(
    r"\[BG\]|SHAHID|ARABIC|MASRAHIYAT|F-INTERNATIONAL ES|QURAN|AFLAM|"
    r"NETFLIX (ARABIC|MASRAHIYAT)", re.I)

# komplette Herkunftsgruppen, die rausfliegen (24/7-Dauerschleifen einzelner Serien)
DROP_GROUPS = {"AM | USA CINEMANIA", "VIP | VIP-PREMIUN AR CINEMA", "VIP | SHAHID",
               "AM | USA LATINO", "AM | USA VIX", "AM | USA TELEMUNDO",
               "AM | USA UNIVISION", "VIP | CHRISTMAS"}

# spanischsprachige US-Kanaele (nicht angefordert)
SPANISH = re.compile(
    r"\(LATIN\)|\bVIX\b|TELEMUNDO|UNIVISION|TUDN|UNIVERSO|LATINO|EN ESPA|"
    r"\(SP\)|DEPORTES|GALAVISION|ESTRELLA", re.I)

# US-Lokalsender: nur die grossen Maerkte behalten
AFFILIATE = re.compile(
    r"^(ABC|CBS|NBC|FOX|CW|MY|MYTV|PBS|METV|ION|IND|TELEMUNDO|UNIVISION)\s*\d*\s*\(", re.I)
TOP_MARKETS = re.compile(
    r"NEW YORK|LOS ANGELES|CHICAGO|PHILADELPHIA|DALLAS|SAN FRANCISCO|ATLANTA|"
    r"HOUSTON|WASHINGTON|BOSTON|MIAMI|SEATTLE", re.I)

# max. Anzahl je durchnummerierter Slot-Familie (FLO SPORTS 001..1000 usw.)
FAMILY_CAP = 12

# ------------------------------------------------------------------- Sport
SPORT_GROUPS = re.compile(
    r"NFL|NBA|NHL|MLB|MILB|MLS|NCAA|ESPN|WHL|OHL|SPORT|FLO|DIRTVISION|FANDUEL|"
    r"FANATIZ|VICTORY|OLYMPIC|FIFA|UFC|F1 and MotoGP|UEFA|PPV", re.I)
SPORT_NAME = re.compile(
    r"\bSPORT|DAZN|SKY SPORT|EUROSPORT|BEIN|MOTOGP|FORMULA|\bF1\b|UFC|BOXING|"
    r"\bNFL\b|\bNBA\b|\bNHL\b|\bMLB\b|\bMLS\b|NCAA|ESPN|UEFA|FIFA|TENNIS|GOLF|"
    r"RUGBY|SETANTA|OLYMPI|WWE|RACING|SPIELE|BUNDESLIGA|SPORT1|SPORTDIGITAL", re.I)

QUALITY = [("4K", 5), ("UHD", 5), ("FHD", 4), ("HEVC", 2), ("HD", 3), ("SD", 1)]
QUAL_RE = re.compile(r"\b(4K|UHD|FHD|HEVC|H265|HD|SD)\b", re.I)

EXTINF_RE = re.compile(r'^#EXTINF:(?P<dur>-?\d+)\s+(?P<attrs>.*?),(?P<title>.*)$')
ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# --------------------------------------------------------------- EPG laden
def load_epg():
    chunks = []
    with open(EPG_XML, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "<programme" in line:
                break
            chunks.append(line)
    head = "".join(chunks)
    by_id, by_name = {}, {}
    for cid, body in re.findall(r'<channel id="([^"]+)">(.*?)</channel>', head, re.S):
        by_id[cid.lower()] = cid
        for dn in re.findall(r"<display-name[^>]*>(.*?)</display-name>", body, re.S):
            dn = html.unescape(dn).strip()
            by_name.setdefault(norm(dn), cid)
            # "13th Street DE" -> auch ohne Laendersuffix matchen
            base = re.sub(r"\s+(DE|AT|CH)$", "", dn, flags=re.I)
            by_name.setdefault(norm(base), cid)
    return by_id, by_name


EPG_BY_ID, EPG_BY_NAME = load_epg()


# ----------------------------------------------------------- Klassifikation
def split_prefix(name: str):
    """'DE| ARTE FHD' -> ('DE', 'ARTE FHD')"""
    if "|" not in name:
        return None, name.strip()
    head, rest = name.split("|", 1)
    head = head.strip().upper()
    if len(head) > 12 or not re.fullmatch(r"[A-Z0-9 -]+", head):
        return None, name.strip()
    return head, rest.strip()


def region_of(prefix, base, group):
    if prefix in PREFIX_REGION:
        reg = PREFIX_REGION[prefix]
    elif prefix is None:
        reg = "PPV" if "FIFA" in base.upper() else "DROP"
    else:
        return "DROP"

    if reg in ("PPV", "VIP"):
        if PPV_DROP.search(base):
            return "DROP"
        up = base.upper()
        if up.startswith("IT-"):
            return "IT"
        if up.startswith("DE-") or "NETFLIX DE" in up:
            return "DE"
        return "PPV"
    return reg


def quality_rank(base):
    best = 0
    for tok, rank in QUALITY:
        if re.search(rf"\b{tok}\b", base, re.I):
            best = max(best, rank)
    if re.search(r"\[BK\]", base, re.I):      # Backup-Feed abwerten
        best -= 10
    return best


def dedup_key(base):
    k = QUAL_RE.sub("", base)
    k = re.sub(r"\[(BK|LIVE-EVENT)\]|\(Tod\)", "", k, flags=re.I)
    return norm(k)


def group_for(region, base, orig_group):
    up = base.upper()
    og = orig_group.upper()
    is_sport = bool(SPORT_GROUPS.search(og) or SPORT_NAME.search(up))

    if region == "ADULT":
        return "XXX | ADULT +18"

    if is_sport:
        if "FIFA" in up or "FIFA" in og:
            return "SPORT | FIFA WC26"
        if "OLYMPI" in up or "OLYMPIC" in og:
            return "SPORT | OLYMPICS"
        if re.search(r"MOTOGP|FORMULA|\bF1\b|TT RACES", up):
            return "SPORT | F1 & MOTOGP"
        if re.search(r"UFC|BOXING|WWE", up):
            return "SPORT | UFC & BOXING"
        if "DAZN" in up:
            return "SPORT | DAZN (DE)"
        if region in ("DE", "AT", "CH"):
            return "SPORT | DE/AT/CH"
        if region == "US":
            return "SPORT | USA"
        if region == "UK":
            return "SPORT | UK"
        if region == "FR":
            return "SPORT | FR"
        if region == "IT":
            return "SPORT | IT"
        return "SPORT | PPV EVENTS"

    return {
        "DE": "DE | TV",
        "AT": "AT | TV",
        "CH": "CH | TV",
        "US": "US | TV",
        "UK": "UK | TV",
        "FR": "FR | TV",
        "IT": "IT | TV",
        "PPV": "SPORT | PPV EVENTS",
    }[region]


def epg_id_for(old_id, base, region):
    if old_id and old_id.lower() in EPG_BY_ID:
        return EPG_BY_ID[old_id.lower()]
    key = QUAL_RE.sub("", base).strip()
    for cand in (key, re.sub(r"\[.*?\]|\(.*?\)", "", key).strip()):
        hit = EPG_BY_NAME.get(norm(cand))
        if hit:
            return hit
    return old_id or ""


# ------------------------------------------------------------------- Build
def main():
    kept = {}          # dedup_key -> record
    stats = defaultdict(int)

    with open(SRC, encoding="utf-8", errors="replace") as fh:
        pending = None
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("#EXTINF"):
                pending = line
                continue
            if not line.startswith("http") or pending is None:
                continue
            extinf, url, pending = pending, line, None
            stats["total"] += 1

            if "/series/" in url or "/movie/" in url:
                stats["vod"] += 1
                continue
            stats["live"] += 1

            m = EXTINF_RE.match(extinf)
            if not m:
                stats["unparsed"] += 1
                continue
            attrs = dict(ATTR_RE.findall(m.group("attrs")))
            name = attrs.get("tvg-name") or m.group("title")

            if "✦" in name or "●" in name:
                stats["separator"] += 1
                continue

            src_group = attrs.get("group-title", "").strip()
            if src_group in DROP_GROUPS:
                stats["dauerschleifen/spanisch"] += 1
                continue

            prefix, base = split_prefix(name)
            region = region_of(prefix, base, src_group)
            if region == "DROP":
                stats["fremdsprachig"] += 1
                continue

            if region == "US" and SPANISH.search(base):
                stats["dauerschleifen/spanisch"] += 1
                continue

            if region == "US" and AFFILIATE.match(base) and not TOP_MARKETS.search(base):
                stats["us_lokalsender"] += 1
                continue

            group = group_for(region, base, src_group)
            key = (group, dedup_key(base)) if region != "PPV" else (group, norm(base))
            rank = quality_rank(base)

            rec = {
                "id": epg_id_for(attrs.get("tvg-id", ""), base, region),
                "name": base,
                "logo": attrs.get("tvg-logo", ""),
                "group": group,
                "region": region,
                "url": url,
                "rank": rank,
            }
            prev = kept.get(key)
            if prev is None or rank > prev["rank"]:
                if prev is not None:
                    stats["dubletten"] += 1
                kept[key] = rec
            else:
                stats["dubletten"] += 1

    # durchnummerierte Slot-Familien kappen (FLO SPORTS 001..1000, BOX OFFICE 1..100, ...)
    families = defaultdict(list)
    for rec in kept.values():
        families[(rec["group"], re.sub(r"\d+", "#", rec["name"]))].append(rec)

    survivors = []
    for (_, fam), members in families.items():
        if "#" in fam and len(members) > FAMILY_CAP:
            members.sort(key=lambda r: [int(n) for n in re.findall(r"\d+", r["name"])])
            stats["slot_kappung"] += len(members) - FAMILY_CAP
            members = members[:FAMILY_CAP]
        survivors.extend(members)

    # sortieren: Gruppen alphabetisch, darin Sendername
    order = sorted(survivors, key=lambda r: (r["group"], r["name"].upper()))

    with open(OUT, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U x-tvg-url="{EPG_URL}" url-tvg="{EPG_URL}"\n')
        for r in order:
            disp = f'{r["region"]} | {r["name"]}' if r["region"] != "PPV" else r["name"]
            out.write(
                f'#EXTINF:-1 tvg-id="{r["id"]}" tvg-name="{r["name"]}" '
                f'tvg-logo="{r["logo"]}" group-title="{r["group"]}",{disp}\n'
            )
            out.write(r["url"] + "\n")

    with_epg = sum(1 for r in order if r["id"] and r["id"].lower() in EPG_BY_ID)
    print(f"Quelle gesamt      : {stats['total']:>7}")
    print(f"  VOD entfernt     : {stats['vod']:>7}")
    print(f"  Live-Kanaele     : {stats['live']:>7}")
    print(f"  Trenner entfernt : {stats['separator']:>7}")
    print(f"  fremdsprachig    : {stats['fremdsprachig']:>7}")
    print(f"  Qualitaets-Dubl. : {stats['dubletten']:>7}")
    print(f"  Dauerschl./ES    : {stats['dauerschleifen/spanisch']:>7}")
    print(f"  US-Lokalsender   : {stats['us_lokalsender']:>7}")
    print(f"  Slot-Kappung     : {stats['slot_kappung']:>7}")
    print(f"ERGEBNIS           : {len(order):>7}")
    print(f"  davon mit EPG-ID : {with_epg:>7}")
    print()
    per = defaultdict(int)
    for r in order:
        per[r["group"]] += 1
    for g, c in sorted(per.items(), key=lambda kv: -kv[1]):
        print(f"{c:>5}  {g}")


if __name__ == "__main__":
    sys.exit(main())
