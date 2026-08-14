# iptv.m3u — schlanke Live-Senderliste

`control-plane/iptv.m3u` ist die Master-Playlist. Sie wird **nicht von Hand gepflegt**,
sondern aus der Roh-Playlist des Providers erzeugt:

```bash
curl -sSL -o /tmp/epg.xml "https://epg.best/24129-yquxim.xml"
python3 control-plane/tools/build_iptv.py \
  --src ~/Downloads/tv_channels_6563139079_plus.m3u \
  --epg-xml /tmp/epg.xml
```

## Was gefiltert wird

| Schritt | Regel | entfernt |
|---|---|---|
| VOD | alle URLs mit `/movie/` oder `/series/` | 475.258 |
| Trenner | Deko-Einträge `✦●✦ … ✦●✦` | 142 |
| Sprache | alles außer DE/AT/CH, US, UK, FR, IT (AR, TR, ES, PT, BG, EXYU, SE, NL, PL, …) | 388 |
| Dauerschleifen / Spanisch | `USA CINEMANIA` (24/7-Loops einzelner Serien), `USA LATINO/VIX/TELEMUNDO/UNIVISION`, `VIP SHAHID` | 1.274 |
| US-Lokalsender | ABC/CBS/NBC/FOX/CW/PBS-Affiliates außerhalb der 12 größten Märkte | 839 |
| Qualitäts-Dubletten | pro Sender bleibt die beste Variante (4K > FHD > HD > HEVC > SD, Backup-Feeds `[BK]` abgewertet) | 333 |
| Slot-Kappung | durchnummerierte Event-Platzhalter (`FLO SPORTS 001…1000`, `BOX OFFICE 1…100`, `DAZN 1…20`) auf 12 pro Familie | 1.863 |

**482.820 → 2.723 Einträge.**

## Gruppen (`group-title`)

Sport ist vollständig aus den Länder-Gruppen herausgelöst:

```
DE | TV            AT | TV            CH | TV            US | TV
SPORT | FIFA WC26          SPORT | DAZN (DE)       SPORT | DE/AT/CH
SPORT | USA                SPORT | F1 & MOTOGP     SPORT | UFC & BOXING
SPORT | OLYMPICS           SPORT | PPV EVENTS
XXX | ADULT +18
```

## EPG

Der Header trägt `x-tvg-url` **und** `url-tvg` (je nach Player wird das eine oder
andere Attribut gelesen):

```
#EXTM3U x-tvg-url="https://epg.best/24129-yquxim.xml" url-tvg="https://epg.best/24129-yquxim.xml"
```

Die `tvg-id` wird gegen die 478 Kanäle der EPG-Quelle gemappt — erst exakt über die
ID, danach über den normalisierten `display-name`. Diese EPG deckt **nur den
DACH-Raum ab** (331 `.de`, 119 `.ch`, 28 `.at`); für US/UK/FR/IT liefert sie nichts.
Die originalen `tvg-id`s (`*.us`, `*.fr`, `*.it`) bleiben erhalten, damit später eine
zweite EPG-Quelle ergänzt werden kann.

## Firewall

Der Portal-Host antwortet mit `302` auf eine **rotierende Edge-Farm** — nur den
Portal-Host freizugeben reicht nicht.

| Ziel | Port | Zweck |
|---|---|---|
| `cjtwpzun.sqhsm.com` (CNAME `edge.noderoute.net`) | TCP 88 | Portal / Stream-Request |
| `5710425.*.cc` — Muster `c##s.cc`, `w##s.cc`, `s##s.cc`, `j##m.cc`, `t##m.cc`, `m##vn.cc` | TCP 80 | Video-Edges (Redirect-Ziel) |
| `epg.best` | TCP 443 | EPG-XML |
| `lo1.in` | TCP 443 | Sender-Logos |

Die Edge-IPs liegen in unzusammenhängenden Netzen mehrerer Provider
(45.155.227.0/24, 45.155.90.0/24, 154.6.144.0/24, 154.6.18.0/23, 149.57.136.0/24 …)
und rotieren — eine IP-Allowlist ist nicht haltbar. Entweder FQDN-/Wildcard-Regeln
verwenden oder die Regel am Client festmachen (IPTV-Box/VLAN darf TCP 80+88 raus).
