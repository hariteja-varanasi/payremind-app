"""Generate the PayRemind design diagrams from one description.

Each diagram is a list of shapes with fixed coordinates. From that one list this script writes:
  - <name>.svg      a standalone image (light colours) for GitHub, slides and documents
  - <name>.drawio   an editable file for draw.io / diagrams.net (Lucidchart can import it too)
  - optionally, an HTML file of inline SVG fragments for the published diagram page

Run from the repo root:  python docs/diagrams/build.py [fragments.html]
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).parent

# Light colours for the standalone files. The web page restyles the same classes per theme.
LIGHT = {
    "canvas": "#ffffff",
    "ink": "#1d2733",
    "muted": "#5b6878",
    "edge": "#4b5868",
    "core_fill": "#e3f3ef",
    "core": "#0f766e",
    "ext_fill": "#f2f4f7",
    "ext": "#64748b",
    "person_fill": "#fff5e0",
    "person": "#b7791f",
    "plan_fill": "#edf3ff",
    "plan": "#3b6fd8",
    "zone_fill": "#f7f9fb",
    "zone": "#9aa8b8",
    "money": "#15803d",
    "warn": "#c2410c",
}

FONT = "'IBM Plex Sans', 'Segoe UI', Helvetica, Arial, sans-serif"


@dataclass
class Node:
    x: float
    y: float
    w: float
    h: float
    title: str
    sub: list[str] = field(default_factory=list)
    kind: str = "core"  # core | ext | person | plan
    step: int | None = None
    mono: bool = False  # title is a code path


@dataclass
class Zone:
    x: float
    y: float
    w: float
    h: float
    label: str
    kind: str = "zone"  # zone | plan | warn


@dataclass
class Edge:
    points: list[tuple[float, float]]
    label: list[str] = field(default_factory=list)
    at: tuple[float, float] = (0, 0)
    anchor: str = "middle"
    kind: str = "edge"  # edge | money | warn | plan
    dashed: bool = False
    both: bool = False


@dataclass
class Text:
    x: float
    y: float
    lines: list[str]
    cls: str = "note"  # note | banner | band
    anchor: str = "start"


Shape = Node | Zone | Edge | Text


@dataclass
class Diagram:
    name: str
    title: str
    w: int
    h: int
    shapes: list[Shape]


# --------------------------------------------------------------------------------------------
# 1. System context
# --------------------------------------------------------------------------------------------


def context() -> Diagram:
    s: list[Shape] = [
        Node(30, 40, 220, 70, "Tally · Busy · Excel", ["accounting software"], "ext"),
        Node(30, 190, 220, 80, "Merchant (MSME)", ["owner or accountant"], "person"),
        Node(30, 420, 220, 80, "PayRemind operator", ["invites businesses"], "person"),
        Node(
            400,
            195,
            220,
            130,
            "PayRemind",
            ["dashboard · API · daily job", "stores invoices,", "never holds money"],
            "core",
        ),
        Node(400, 30, 220, 70, "Razorpay", ["collects our monthly fee"], "ext"),
        Node(400, 440, 220, 70, "Merchant's bank account", ["behind their own UPI ID"], "ext"),
        Node(800, 30, 210, 80, "WhatsApp Cloud API", ["Meta"], "ext"),
        Node(800, 220, 210, 80, "Customer (buyer)", ["owes the merchant"], "person"),
        Node(800, 400, 210, 70, "Customer's UPI app", ["GPay · PhonePe · Paytm"], "ext"),
        # edges
        Edge([(140, 110), (140, 190)], ["exports .xlsx / .csv"], (148, 154), "start"),
        Edge([(250, 222), (400, 222)], ["uploads, marks paid"], (325, 214)),
        Edge([(400, 252), (250, 252)], ["overdue list, ageing"], (325, 270)),
        Edge(
            [(250, 460), (330, 460), (330, 300), (400, 300)],
            ["invite (CLI)"],
            (338, 384),
            "start",
        ),
        Edge(
            [(510, 100), (510, 195)],
            ["subscription,", "payment webhooks"],
            (518, 140),
            "start",
            both=True,
        ),
        Edge([(620, 215), (700, 215), (700, 62), (800, 62)], ["send template"], (750, 54)),
        Edge(
            [(800, 90), (730, 90), (730, 235), (620, 235)],
            ["STOP replies"],
            (765, 108),
            dashed=True,
        ),
        Edge([(905, 110), (905, 220)], ["reminder or", "login code"], (913, 160), "start"),
        Edge([(800, 275), (620, 275)], ["opens pay page link"], (710, 293)),
        Edge([(905, 300), (905, 400)], ["taps Pay"], (913, 354), "start"),
        Edge(
            [(800, 435), (710, 435), (710, 475), (620, 475)],
            ["₹ paid direct"],
            (710, 427),
            kind="money",
        ),
    ]
    return Diagram("01-system-context", "System context", 1040, 540, s)


# --------------------------------------------------------------------------------------------
# 2. Components (inside the app)
# --------------------------------------------------------------------------------------------


def components() -> Diagram:
    s: list[Shape] = []
    left, right = 160, 1040
    width = right - left
    bands = [
        (20, 70, "Who calls in"),
        (124, 86, "Entry points"),
        (244, 86, "Use cases"),
        (364, 74, "Pure logic"),
        (472, 74, "Adapters"),
        (580, 66, "Outside services"),
    ]
    for y, h, label in bands:
        s.append(Zone(16, y - 8, right - 16 + 14, h + 16, "", "zone"))
        s.append(Text(30, y + h / 2 + 4, [label], "band"))

    def row(y: float, h: float, items: list[tuple[str, list[str], str, bool]]) -> list[Node]:
        n = len(items)
        gap = 12
        w = (width - gap * (n - 1)) / n
        out = []
        for i, (t, sub, kind, mono) in enumerate(items):
            out.append(Node(left + i * (w + gap), y, w, h, t, sub, kind, mono=mono))
        return out

    callers = row(
        20,
        70,
        [
            ("Merchant", ["browser"], "person", False),
            ("Script", ["curl / API client"], "person", False),
            ("Customer", ["phone browser"], "person", False),
            ("Meta", ["webhook"], "ext", False),
            ("Razorpay", ["webhook"], "ext", False),
            ("Scheduler", ["daily, 09:30 IST"], "ext", False),
            ("Operator", ["shell"], "person", False),
        ],
    )
    entries = row(
        124,
        86,
        [
            ("api/web.py", ["Dashboard /app/*", "cookie session + CSRF"], "core", True),
            ("api/app.py", ["REST API", "bearer token"], "core", True),
            ("pay page /p/{token}", ["public, read-only", "UPI button + QR"], "core", True),
            ("webhooks", ["/webhooks/whatsapp", "/webhooks/razorpay"], "core", True),
            ("cli.py", ["invite · add-user", "migrate · run-reminders"], "core", True),
        ],
    )
    cases = row(
        244,
        86,
        [
            (
                "services.py",
                ["invoices, promises, reminders", "every query tenant-scoped"],
                "core",
                True,
            ),
            ("auth.py", ["phone OTP sign-in", "web sessions"], "core", True),
            (
                "importers/excel.py",
                ["reads .xlsx / .csv", "header aliases, row errors"],
                "core",
                True,
            ),
            ("billing/service.py", ["plan status, trial gate", "GST invoices"], "core", True),
        ],
    )
    logic = row(
        364,
        74,
        [
            ("core/schedule.py", ["which reminder today"], "core", True),
            ("core/ageing.py", ["overdue buckets"], "core", True),
            ("core/upi.py", ["upi://pay link"], "core", True),
            ("core/phone.py", ["+91 normaliser"], "core", True),
            ("billing/gst.py", ["CGST/SGST/IGST split"], "core", True),
        ],
    )
    adapters = row(
        472,
        74,
        [
            ("messaging/whatsapp.py", ["Cloud API sender", "or fake sender in dev"], "core", True),
            ("billing/razorpay.py", ["subscriptions client"], "core", True),
            ("models.py + db.py", ["SQLAlchemy, Alembic", "migrations"], "core", True),
        ],
    )
    outside = row(
        580,
        66,
        [
            ("Meta Graph API", ["WhatsApp messages"], "ext", False),
            ("Razorpay API", ["our fee only"], "ext", False),
            ("PostgreSQL", ["SQLite in local dev"], "ext", False),
        ],
    )
    s += callers + entries + cases + logic + adapters + outside

    def bottom(n: Node) -> tuple[float, float]:
        return (n.x + n.w / 2, n.y + n.h)

    def top(n: Node) -> tuple[float, float]:
        return (n.x + n.w / 2, n.y)

    pairs = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 3), (5, 4), (6, 4)]
    for c, e in pairs:
        s.append(Edge([bottom(callers[c]), top(entries[e])]))
    for a, o in zip(adapters, outside, strict=True):
        s.append(
            Edge(
                [bottom(a), top(o)],
                ["HTTPS" if o.title != "PostgreSQL" else "SQL"],
                (a.x + a.w / 2 + 8, a.y + a.h + 21),
                "start",
            )
        )
    s.append(
        Text(
            left,
            680,
            [
                "Each layer calls only the layers below it. Pure logic has no database or network "
                "access, so it is fully unit-tested."
            ],
            "note",
        )
    )
    return Diagram("02-components", "Components", 1070, 696, s)


# --------------------------------------------------------------------------------------------
# 3. Data flow: upload -> reminder -> payment
# --------------------------------------------------------------------------------------------


def dataflow() -> Diagram:
    lanes = ["Merchant", "PayRemind", "Database", "WhatsApp", "Customer", "Bank / UPI"]
    lane_h, top, lx, rx = 92, 20, 16, 1250
    s: list[Shape] = []
    for i, name in enumerate(lanes):
        y = top + i * lane_h
        s.append(Zone(lx, y, rx - lx, lane_h, "", "zone"))
        s.append(Text(30, y + lane_h / 2 + 4, [name], "band"))

    col0, cw, bw, bh = 140, 124, 112, 58

    def box(col: int, lane: int, step: int, title: str, sub: list[str], kind: str = "core") -> Node:
        x = col0 + col * cw
        y = top + lane * lane_h + (lane_h - bh) / 2
        return Node(x, y, bw, bh, title, sub, kind, step=step)

    def cx(n: Node) -> float:
        return n.x + n.w / 2

    def cy(n: Node) -> float:
        return n.y + n.h / 2

    b1 = box(0, 0, 1, "Export list", ["from Tally / Excel"], "person")
    b2 = box(1, 0, 2, "Upload file", ["dashboard or API"], "person")
    b3 = box(1, 1, 3, "Parse & check", ["≤ 5 MB, ≤ 5,000 rows"])
    b4 = box(2, 2, 4, "Save invoices", ["upsert by invoice no."], "ext")
    b5 = box(3, 1, 5, "Daily run", ["09:30 IST"])
    note = box(4, 1, 0, "Skip if", ["paid · STOP · no phone", "promise · billing lapsed"], "plan")
    note.step = None
    note.w = 128
    b6 = box(4, 3, 6, "Send template", ["name, invoice, ₹, link"], "ext")
    b7 = box(4, 2, 7, "Log reminder", ["once per step"], "ext")
    b8 = box(5, 4, 8, "Open pay page", ["/p/<token>"], "person")
    b9 = box(6, 1, 9, "Pay page", ["amount, UPI QR"])
    b10 = box(6, 4, 10, "Pay in UPI app", ["GPay, PhonePe…"], "person")
    b11 = box(7, 5, 11, "Money arrives", ["merchant's account"], "ext")
    b12 = box(8, 0, 12, "Mark paid", ["after checking bank"], "person")
    b13 = box(8, 2, 13, "Invoice closed", ["reminders stop"], "ext")
    s += [b1, b2, b3, b4, b5, note, b6, b7, b8, b9, b10, b11, b12, b13]

    def r(n: Node) -> tuple[float, float]:
        return (n.x + n.w, cy(n))

    def lft(n: Node) -> tuple[float, float]:
        return (n.x, cy(n))

    s += [
        Edge([r(b1), lft(b2)]),
        Edge([(cx(b2), b2.y + bh), (cx(b2), b3.y)]),
        Edge(
            [r(b3), (cx(b4), cy(b3)), (cx(b4), b4.y)],
            ["valid rows"],
            (cx(b4) + 6, cy(b3) + 40),
            "start",
        ),
        Edge(
            [r(b4), (cx(b5), cy(b4)), (cx(b5), b5.y + bh)],
            ["next morning"],
            (cx(b5) - 6, cy(b4) - 20),
            "end",
        ),
        Edge([(b5.x + bw, cy(b5)), (note.x, cy(b5))], dashed=True),
        Edge([(cx(b5), cy(b5) + 4), (cx(b5), cy(b5) + 4)]),  # placeholder, removed below
        Edge(
            [(b5.x + bw - 20, b5.y + bh), (b5.x + bw - 20, cy(b6)), (b6.x, cy(b6))],
            ["if due"],
            (b5.x + bw - 14, cy(b6) - 40),
            "start",
        ),
        Edge(
            [(cx(b6), b6.y), (cx(b7), b7.y + bh)], ["message id"], (cx(b7) + 6, b6.y - 12), "start"
        ),
        Edge(
            [(cx(b6), b6.y + bh), (cx(b6), cy(b8)), (b8.x, cy(b8))],
            ["delivers"],
            (cx(b6) + 6, cy(b8) - 10),
            "start",
        ),
        Edge(
            [(cx(b8) + 30, b8.y), (cx(b8) + 30, cy(b9)), (b9.x, cy(b9))],
            ["taps link"],
            (cx(b8) + 36, cy(b9) + 34),
            "start",
        ),
        Edge([r(b8), lft(b10)]),
        Edge(
            [(cx(b10), b10.y + bh), (cx(b10), cy(b11)), (b11.x, cy(b11))],
            ["₹ direct"],
            (cx(b10) + 6, cy(b11) - 10),
            "start",
            kind="money",
        ),
        Edge(
            [r(b11), (cx(b12), cy(b11)), (cx(b12), b12.y + bh)],
            ["sees credit"],
            (cx(b12) - 6, cy(b11) - 10),
            "end",
            dashed=True,
        ),
        Edge(
            [(b12.x + bw - 14, b12.y + bh), (b12.x + bw - 14, b13.y)],
            ["closes"],
            (b12.x + bw - 20, b13.y - 50),
            "end",
        ),
    ]
    s = [x for x in s if not (isinstance(x, Edge) and x.points[0] == x.points[-1])]
    return Diagram("03-data-flow", "Upload to payment", 1266, 590, s)


# --------------------------------------------------------------------------------------------
# 4. Planned AWS deployment
# --------------------------------------------------------------------------------------------


def aws() -> Diagram:
    s: list[Shape] = [
        Zone(200, 20, 880, 590, "AWS account · ap-south-1 (Mumbai)", "plan"),
        Text(220, 62, ["TERRAFORM WRITTEN · NOT APPLIED YET"], "banner"),
        Zone(420, 100, 640, 320, "VPC 10.20.0.0/16", "plan"),
        Zone(435, 130, 405, 275, "Public subnets, 2 AZs", "zone"),
        Zone(855, 130, 190, 275, "Private subnets", "zone"),
        Node(20, 120, 150, 60, "Merchant browser", [], "person"),
        Node(20, 210, 150, 60, "Customer phone", [], "person"),
        Node(20, 300, 150, 60, "Meta, Razorpay", ["webhooks"], "ext"),
        Node(1110, 40, 160, 80, "Meta + Razorpay", ["public APIs"], "ext"),
        Node(
            220,
            160,
            150,
            84,
            "CloudFront + WAF",
            ["HTTPS, HSTS", "OWASP rules, India", "only, rate limits"],
            "plan",
        ),
        Node(
            465,
            165,
            140,
            74,
            "Load balancer",
            ["CloudFront IPs only", "needs origin secret"],
            "plan",
        ),
        Node(
            660, 165, 165, 74, "Fargate: web app", ["0.25 vCPU ARM", "read-only filesystem"], "plan"
        ),
        Node(220, 310, 150, 74, "EventBridge", ["Scheduler", "09:30 Asia/Kolkata"], "plan"),
        Node(660, 310, 165, 74, "Fargate: daily job", ["one-off task", "run-reminders"], "plan"),
        Node(
            870,
            215,
            160,
            100,
            "RDS PostgreSQL 16",
            ["db.t4g.micro, 1 AZ", "encrypted, TLS forced", "7-day backups + PITR"],
            "plan",
        ),
        Text(230, 478, ["Security and operations (account-wide)"], "band"),
    ]
    ops = [
        ("Budgets", ["email at 50%, 100%"]),
        ("GuardDuty", ["medium+ by email"]),
        ("CloudTrail", ["API audit log"]),
        ("CloudWatch", ["logs kept 365 d"]),
        ("SSM Params", ["secrets, encrypted"]),
        ("ECR", ["image registry"]),
        ("S3", ["ALB + trail logs"]),
    ]
    for i, (t, sub) in enumerate(ops):
        s.append(Node(230 + i * 120, 495, 110, 62, t, sub, "plan"))
    s += [
        Edge([(170, 150), (195, 150), (195, 190), (220, 190)]),
        Edge([(170, 240), (195, 240), (195, 205), (220, 205)]),
        Edge([(170, 330), (205, 330), (205, 222), (220, 222)], ["HTTPS"], (176, 352), "start"),
        Edge([(370, 202), (465, 202)], ["HTTPS +", "origin secret"], (418, 188)),
        Edge([(605, 202), (660, 202)], [":8000"], (632, 194)),
        Edge([(370, 347), (660, 347)], ["starts task"], (515, 339)),
        Edge(
            [(742, 165), (742, 80), (1110, 80)],
            ["outbound via task public IP, no NAT gateway"],
            (930, 72),
        ),
        Edge([(825, 202), (848, 202), (848, 250), (870, 250)], ["TLS"], (842, 196), "end"),
        Edge([(825, 347), (848, 347), (848, 285), (870, 285)]),
        Edge([(742, 384), (742, 495)], ["reads secrets"], (750, 470), "start", dashed=True),
        Text(
            230,
            440,
            [
                "Only CloudFront is public. App tasks accept traffic from the load balancer only;",
                "the database has no internet route at all.",
            ],
            "note",
        ),
    ]
    return Diagram("04-aws-planned", "Planned AWS deployment", 1290, 630, s)


# --------------------------------------------------------------------------------------------
# 5. Trust boundaries
# --------------------------------------------------------------------------------------------


def trust() -> Diagram:
    s: list[Shape] = [
        Zone(20, 20, 250, 350, "Internet (untrusted)", "warn"),
        Zone(20, 390, 250, 170, "Third parties (signed)", "zone"),
        Zone(470, 20, 300, 540, "PayRemind app", "zone"),
        Zone(900, 20, 220, 540, "Data and secrets", "zone"),
        Node(45, 70, 200, 60, "Merchant browser", [], "person"),
        Node(45, 170, 200, 60, "Script / curl", [], "person"),
        Node(45, 270, 200, 60, "Customer phone", [], "person"),
        Node(45, 425, 200, 50, "Meta (WhatsApp)", [], "ext"),
        Node(45, 490, 200, 50, "Razorpay", [], "ext"),
        Node(495, 70, 250, 60, "Dashboard", ["/login, /app/*"], "core"),
        Node(495, 170, 250, 60, "REST API", ["/imports, /invoices, …"], "core"),
        Node(495, 270, 250, 60, "Pay page", ["/p/{token}"], "core"),
        Node(
            495,
            440,
            250,
            80,
            "Webhook handlers",
            ["/webhooks/whatsapp", "/webhooks/razorpay"],
            "core",
        ),
        Node(
            925,
            120,
            170,
            110,
            "PostgreSQL",
            ["tokens, codes and", "sessions stored", "only as hashes"],
            "ext",
        ),
        Node(925, 340, 170, 90, "Secrets", ["API keys, signing", "secrets, secret key"], "ext"),
        Edge(
            [(245, 100), (495, 100)], ["WhatsApp OTP → session", "cookie + CSRF token"], (370, 82)
        ),
        Edge([(245, 200), (495, 200)], ["Bearer API token", "(SHA-256 hash stored)"], (370, 182)),
        Edge(
            [(245, 300), (495, 300)],
            ["random 24-byte pay token", "no login, read-only"],
            (370, 282),
        ),
        Edge(
            [(245, 450), (380, 450), (380, 470), (495, 470)],
            ["HMAC-SHA256", "signature"],
            (380, 425),
        ),
        Edge(
            [(245, 515), (380, 515), (380, 495), (495, 495)],
            ["HMAC signature,", "event id used once"],
            (380, 535),
        ),
        Edge([(745, 175), (925, 175)], ["tenant_id filter on", "every query"], (835, 157)),
        Edge([(925, 385), (772, 385)], ["read at start-up"], (848, 377), dashed=True),
    ]
    return Diagram("05-trust-boundaries", "Trust boundaries", 1140, 580, s)


DIAGRAMS = [context(), components(), dataflow(), aws(), trust()]

# --------------------------------------------------------------------------------------------
# SVG output
# --------------------------------------------------------------------------------------------


def esc(t: str) -> str:
    return html.escape(t, quote=True)


def svg_body(d: Diagram) -> str:
    p = d.name.split("-")[0]
    out = [
        "<defs>",
        f'<marker id="a{p}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path class="ah" d="M0,0 L10,5 L0,10 z"/></marker>',
        f'<marker id="m{p}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path class="ah-money" d="M0,0 L10,5 L0,10 z"/></marker>',
        f'<marker id="w{p}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path class="ah-warn" d="M0,0 L10,5 L0,10 z"/></marker>',
        "</defs>",
        f'<rect class="canvas" x="0" y="0" width="{d.w}" height="{d.h}"/>',
    ]
    zones = [x for x in d.shapes if isinstance(x, Zone)]
    nodes = [x for x in d.shapes if isinstance(x, Node)]
    edges = [x for x in d.shapes if isinstance(x, Edge)]
    texts = [x for x in d.shapes if isinstance(x, Text)]
    for z in zones:
        out.append(
            f'<rect class="z z-{z.kind}" x="{z.x}" y="{z.y}" width="{z.w}" height="{z.h}" rx="10"/>'
        )
        if z.label:
            out.append(
                f'<text class="zl zl-{z.kind}" x="{z.x + 14}" y="{z.y + 22}">{esc(z.label)}</text>'
            )
    for e in edges:
        pts = " ".join(f"{x:g},{y:g}" for x, y in e.points)
        mk = {"money": "m", "warn": "w"}.get(e.kind, "a")
        dash = " dash" if e.dashed else ""
        start = f' marker-start="url(#{mk}{p})"' if e.both else ""
        out.append(
            f'<polyline class="e e-{e.kind}{dash}" points="{pts}" '
            f'marker-end="url(#{mk}{p})"{start}/>'
        )
    for n in nodes:
        rx = 22 if n.kind == "person" and n.w > 150 else (14 if n.kind == "person" else 8)
        rx = min(rx, n.h / 2)
        out.append(
            f'<rect class="n n-{n.kind}" x="{n.x:g}" y="{n.y:g}" width="{n.w:g}" '
            f'height="{n.h:g}" rx="{rx:g}"/>'
        )
        lh_title, lh_sub = 17, 15
        total = lh_title + lh_sub * len(n.sub)
        y0 = n.y + (n.h - total) / 2 + 12
        cx = n.x + n.w / 2
        tcls = "nt mono" if n.mono else "nt"
        out.append(
            f'<text class="{tcls}" x="{cx:g}" y="{y0:g}" text-anchor="middle">{esc(n.title)}</text>'
        )
        for i, sub in enumerate(n.sub):
            out.append(
                f'<text class="ns" x="{cx:g}" y="{y0 + lh_title + i * lh_sub - 1:g}" '
                f'text-anchor="middle">{esc(sub)}</text>'
            )
        if n.step:
            out.append(f'<circle class="badge" cx="{n.x:g}" cy="{n.y:g}" r="11"/>')
            out.append(
                f'<text class="badge-t" x="{n.x:g}" y="{n.y + 4:g}" '
                f'text-anchor="middle">{n.step}</text>'
            )
    for e in edges:
        for i, line in enumerate(e.label):
            out.append(
                f'<text class="el el-{e.kind}" x="{e.at[0]:g}" y="{e.at[1] + i * 14:g}" '
                f'text-anchor="{e.anchor}">{esc(line)}</text>'
            )
    for t in texts:
        for i, line in enumerate(t.lines):
            out.append(
                f'<text class="tx tx-{t.cls}" x="{t.x:g}" y="{t.y + i * 15:g}" '
                f'text-anchor="{t.anchor}">{esc(line)}</text>'
            )
    return "\n".join(out)


def css(c: dict[str, str]) -> str:
    return f"""
.canvas{{fill:{c["canvas"]}}}
text{{font-family:{FONT};fill:{c["ink"]}}}
.nt{{font-size:13px;font-weight:600}}
.nt.mono{{font-family:'IBM Plex Mono',Menlo,Consolas,monospace;font-size:12px}}
.ns{{font-size:11px;fill:{c["muted"]}}}
.n{{stroke-width:1.4}}
.n-core{{fill:{c["core_fill"]};stroke:{c["core"]}}}
.n-ext{{fill:{c["ext_fill"]};stroke:{c["ext"]}}}
.n-person{{fill:{c["person_fill"]};stroke:{c["person"]}}}
.n-plan{{fill:{c["plan_fill"]};stroke:{c["plan"]};stroke-dasharray:5 3}}
.z{{fill:{c["zone_fill"]};stroke:{c["zone"]};stroke-width:1;stroke-dasharray:4 4}}
.z-plan{{fill:none;stroke:{c["plan"]};stroke-width:1.4}}
.z-warn{{stroke:{c["warn"]}}}
.zl{{font-size:12px;font-weight:600;fill:{c["muted"]};letter-spacing:.02em}}
.zl-plan{{fill:{c["plan"]}}}
.zl-warn{{fill:{c["warn"]}}}
.e{{fill:none;stroke:{c["edge"]};stroke-width:1.4}}
.e-money{{stroke:{c["money"]};stroke-width:2.2}}
.e-warn{{stroke:{c["warn"]}}}
.dash{{stroke-dasharray:5 4}}
.ah{{fill:{c["edge"]}}}
.ah-money{{fill:{c["money"]}}}
.ah-warn{{fill:{c["warn"]}}}
.el{{font-size:11px;fill:{c["ink"]};paint-order:stroke;stroke:{c["canvas"]};stroke-width:4px;
stroke-linejoin:round}}
.el-money{{fill:{c["money"]};font-weight:600}}
.el-warn{{fill:{c["warn"]};font-weight:600}}
.badge{{fill:{c["ink"]}}}
.badge-t{{font-size:11px;font-weight:700;fill:{c["canvas"]}}}
.tx-band{{font-size:12px;font-weight:600;fill:{c["muted"]};letter-spacing:.03em}}
.tx-note{{font-size:12px;fill:{c["muted"]}}}
.tx-banner{{font-size:13px;font-weight:700;fill:{c["plan"]};letter-spacing:.08em}}
.tx-warnnote{{font-size:11px;fill:{c["warn"]}}}
"""


def standalone_svg(d: Diagram) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {d.w} {d.h}" width="{d.w}" '
        f'height="{d.h}" role="img" aria-label="{esc(d.title)}">\n'
        f"<style>{css(LIGHT)}</style>\n{svg_body(d)}\n</svg>\n"
    )


# --------------------------------------------------------------------------------------------
# draw.io output (uncompressed mxGraph XML, opens in diagrams.net and imports into Lucidchart)
# --------------------------------------------------------------------------------------------

DRAWIO_NODE = {
    "core": f"fillColor={LIGHT['core_fill']};strokeColor={LIGHT['core']};",
    "ext": f"fillColor={LIGHT['ext_fill']};strokeColor={LIGHT['ext']};",
    "person": f"fillColor={LIGHT['person_fill']};strokeColor={LIGHT['person']};arcSize=40;",
    "plan": f"fillColor={LIGHT['plan_fill']};strokeColor={LIGHT['plan']};dashed=1;",
}
DRAWIO_EDGE = {
    "edge": LIGHT["edge"],
    "money": LIGHT["money"],
    "warn": LIGHT["warn"],
    "plan": LIGHT["plan"],
}


def drawio(d: Diagram) -> str:
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    n = 2

    def add(value: str, style: str, x: float, y: float, w: float, h: float) -> None:
        nonlocal n
        cells.append(
            f'<mxCell id="c{n}" value="{esc(value)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" as="geometry"/>'
            "</mxCell>"
        )
        n += 1

    for z in [x for x in d.shapes if isinstance(x, Zone)]:
        stroke = {"plan": LIGHT["plan"], "warn": LIGHT["warn"]}.get(z.kind, LIGHT["zone"])
        fill = "none" if z.kind == "plan" else LIGHT["zone_fill"]
        add(
            z.label,
            f"rounded=1;arcSize=3;whiteSpace=wrap;html=1;dashed=1;fillColor={fill};"
            f"strokeColor={stroke};verticalAlign=top;align=left;spacingLeft=12;spacingTop=4;"
            f"fontStyle=1;fontColor={stroke};fontSize=12;",
            z.x,
            z.y,
            z.w,
            z.h,
        )
    for e in [x for x in d.shapes if isinstance(x, Edge)]:
        color = DRAWIO_EDGE[e.kind]
        (sx, sy), (tx, ty) = e.points[0], e.points[-1]
        mids = "".join(f'<mxPoint x="{x:g}" y="{y:g}"/>' for x, y in e.points[1:-1])
        arr = f'<Array as="points">{mids}</Array>' if mids else ""
        style = (
            f"endArrow=block;endFill=1;html=1;rounded=0;strokeColor={color};"
            f"strokeWidth={2 if e.kind == 'money' else 1.4};"
            + ("dashed=1;" if e.dashed else "")
            + ("startArrow=block;startFill=1;" if e.both else "")
        )
        cells.append(
            f'<mxCell id="c{n}" style="{style}" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{sx:g}" y="{sy:g}" '
            f'as="sourcePoint"/><mxPoint x="{tx:g}" y="{ty:g}" as="targetPoint"/>{arr}'
            "</mxGeometry></mxCell>"
        )
        n += 1
    for nd in [x for x in d.shapes if isinstance(x, Node)]:
        value = f"<b>{esc(nd.title)}</b>" + "".join(
            f"<br><font style='font-size:11px' color='{LIGHT['muted']}'>{esc(s)}</font>"
            for s in nd.sub
        )
        add(
            value,
            "rounded=1;whiteSpace=wrap;html=1;fontSize=13;" + DRAWIO_NODE[nd.kind],
            nd.x,
            nd.y,
            nd.w,
            nd.h,
        )
        if nd.step:
            add(
                str(nd.step),
                f"ellipse;html=1;fillColor={LIGHT['ink']};strokeColor=none;fontColor=#ffffff;"
                "fontStyle=1;fontSize=11;",
                nd.x - 11,
                nd.y - 11,
                22,
                22,
            )
    for e in [x for x in d.shapes if isinstance(x, Edge)]:
        if not e.label:
            continue
        w = max(len(t) for t in e.label) * 6.4 + 10
        h = 15 * len(e.label) + 4
        x = {"start": e.at[0], "end": e.at[0] - w, "middle": e.at[0] - w / 2}[e.anchor]
        color = {"money": LIGHT["money"], "warn": LIGHT["warn"]}.get(e.kind, LIGHT["ink"])
        add(
            "<br>".join(esc(t) for t in e.label),
            f"text;html=1;fontSize=11;fontColor={color};labelBackgroundColor=#ffffff;"
            f"align={ {'start': 'left', 'end': 'right', 'middle': 'center'}[e.anchor] };"
            "verticalAlign=top;spacing=0;",
            x,
            e.at[1] - 12,
            w,
            h,
        )
    for t in [x for x in d.shapes if isinstance(x, Text)]:
        color = {"banner": LIGHT["plan"], "warnnote": LIGHT["warn"]}.get(t.cls, LIGHT["muted"])
        w = max(len(s) for s in t.lines) * 7 + 10
        add(
            "<br>".join(esc(s) for s in t.lines),
            f"text;html=1;fontSize=12;fontColor={color};align=left;verticalAlign=top;spacing=0;"
            + ("fontStyle=1;" if t.cls in ("band", "banner") else ""),
            t.x,
            t.y - 12,
            w,
            16 * len(t.lines),
        )
    model = "".join(cells)
    return (
        '<mxfile host="payremind-docs">'
        f'<diagram id="{d.name}" name="{esc(d.title)}">'
        f'<mxGraphModel dx="{d.w}" dy="{d.h}" grid="1" gridSize="10" page="1" '
        f'pageWidth="{d.w + 40}" pageHeight="{d.h + 40}" background="#ffffff">'
        f"<root>{model}</root></mxGraphModel></diagram></mxfile>\n"
    )


def main(fragments: Path | None = None) -> None:
    frags = []
    for d in DIAGRAMS:
        (OUT / f"{d.name}.svg").write_text(standalone_svg(d), encoding="utf-8")
        (OUT / f"{d.name}.drawio").write_text(drawio(d), encoding="utf-8")
        frags.append(
            f'<!-- {d.name} -->\n<svg class="dg" viewBox="0 0 {d.w} {d.h}" role="img" '
            f'aria-label="{esc(d.title)}">\n{svg_body(d)}\n</svg>'
        )
    if fragments is not None:
        fragments.write_text("\n\n".join(frags) + "\n", encoding="utf-8")
    print(f"wrote {len(DIAGRAMS)} diagrams to {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
