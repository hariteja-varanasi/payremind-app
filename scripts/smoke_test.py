"""End-to-end smoke test against a running PayRemind (local or the AWS test stack).

The server must run in dev-log mode (PAYREMIND_DEV_LOG_MESSAGES=true, no WhatsApp keys), so
login codes and reminders are written to the log instead of being sent. This script reads
them back from a local log file or from CloudWatch Logs.

  python scripts/smoke_test.py --base-url http://localhost:8000 --phone 9000000001 \\
      --log-file app.log
  python scripts/smoke_test.py --base-url https://dxxxx.cloudfront.net --phone 9000000001 \\
      --cloudwatch-group /payremind/app

Exits non-zero on the first failed check. Creates sample invoices for the signed-in business.
"""

import argparse
import json
import re
import subprocess  # nosec B404  (fixed aws CLI invocation, no shell)
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

IST = ZoneInfo("Asia/Kolkata")
PASS, FAIL = "✓", "✗"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"{PASS if ok else FAIL} {label}", flush=True)
    if not ok:
        summary()
        sys.exit(1)


def summary() -> None:
    passed = sum(ok for ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")


class LogReader:
    def __init__(self, log_file: str | None, group: str | None, region: str):
        self.file, self.group, self.region = log_file, group, region
        self.since_ms = int(time.time() * 1000) - 5_000

    def lines(self) -> list[str]:
        if self.file:
            return Path(self.file).read_text(errors="replace").splitlines()
        out = subprocess.run(  # noqa: S603  # nosec B603 B607
            [  # noqa: S607
                "aws",
                "logs",
                "filter-log-events",
                "--region",
                self.region,
                "--log-group-name",
                str(self.group),
                "--start-time",
                str(self.since_ms),
                "--filter-pattern",
                '"DEV WhatsApp"',
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return [e["message"] for e in json.loads(out.stdout).get("events", [])]

    def wait_for(self, pattern: str, timeout: int = 90) -> list[str]:
        rx = re.compile(pattern)
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = [m.group(1) for line in self.lines() if (m := rx.search(line))]
            if found:
                return found
            time.sleep(3)
        return []


def sample_csv() -> str:
    today = datetime.now(IST).date()
    d = lambda days: (today + timedelta(days=days)).strftime("%d-%m-%Y")  # noqa: E731
    return (
        "Party Name,Mobile,Invoice No,Invoice Date,Due Date,Amount,Balance,Language\n"
        f'Smoke Sharma Traders,9000000101,SMK-1,{d(-60)},{d(-31)},"1,000.00",1000,en\n'
        f"Smoke Gupta Stores,9000000102,SMK-2,{d(-27)},{d(3)},500,500,en\n"
        f"Smoke Verma Agencies,9000000103,SMK-3,{d(-40)},{d(-7)},750,750,hi\n"
        f"Smoke Rao & Sons,,SMK-4,{d(-120)},{d(-95)},2500,2500,en\n"
        f"Smoke Promise Co,9000000105,SMK-5,{d(-30)},{d(-15)},300,300,en\n"
        "Broken Row,,,,,\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--phone", required=True, help="owner phone created with `payremind invite`")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--log-file")
    src.add_argument("--cloudwatch-group")
    ap.add_argument("--region", default="ap-south-1")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    logs = LogReader(args.log_file, args.cloudwatch_group, args.region)
    c = httpx.Client(base_url=base, follow_redirects=False, timeout=30)
    digits = re.sub(r"\D", "", args.phone)[-10:]
    e164 = f"+91{digits}"

    r = c.get("/health")
    check(r.status_code == 200 and r.json() == {"status": "ok"}, "health check")

    r = c.get("/app")
    check(r.status_code == 303 and r.headers["location"] == "/login", "dashboard needs login")

    r = c.get("/login")
    csp = r.headers.get("content-security-policy", "")
    check(r.status_code == 200 and "default-src 'none'" in csp, "login page with strict CSP")
    check(r.headers.get("x-frame-options") == "DENY", "clickjacking protection header")
    if base.startswith("https://"):
        check("max-age" in r.headers.get("strict-transport-security", ""), "HSTS header")

    for path in ("/privacy", "/terms"):
        r = c.get(path)
        check(r.status_code == 200 and "DRAFT" in r.text, f"{path} served with DRAFT banner")

    r = c.post("/login", data={"phone": "9123400000"})
    check(
        r.status_code == 200 and "If +919123400000 is registered" in r.text,
        "unknown phone gets the same answer (no account enumeration)",
    )

    r = c.post("/login", data={"phone": digits})
    check(r.status_code == 200 and "Enter your code" in r.text, "login code requested")
    codes = logs.wait_for(rf"login code for {re.escape(e164)}: (\d{{6}})")
    check(bool(codes), "login code written to the log (not sent)")

    bad = "000000" if codes[-1] != "000000" else "111111"
    r = c.post("/login/verify", data={"phone": digits, "code": bad})
    check(r.status_code == 401, "wrong code rejected")
    r = c.post("/login/verify", data={"phone": digits, "code": codes[-1]})
    check(r.status_code == 303 and "pr_session" in r.headers.get("set-cookie", ""), "signed in")
    cookie = r.headers["set-cookie"]
    check(
        "HttpOnly" in cookie and "SameSite=lax" in cookie, "session cookie is HttpOnly + SameSite"
    )
    if base.startswith("https://"):
        check("Secure" in cookie, "session cookie is Secure")

    page = c.get("/app").text
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    check(m is not None, "dashboard loads")
    csrf = m.group(1) if m else ""

    r = c.post(
        "/app/upload",
        data={"csrf": csrf},
        files={"file": ("smoke.csv", sample_csv().encode(), "text/csv")},
    )
    check(
        "1 rows were skipped" in r.text and "Smoke Sharma Traders" in r.text,
        "Excel/CSV upload with a bad row reported",
    )
    check("31 days late" in r.text and "no phone" in r.text, "overdue days and missing phone shown")

    ids = dict(re.findall(r"<td>(SMK-\d)</td>.*?/app/invoices/(\d+)/paid", r.text, re.S))
    check({"SMK-1", "SMK-5"} <= ids.keys(), "invoice actions available")

    promised = (datetime.now(IST).date() + timedelta(days=10)).isoformat()
    r = c.post(
        f"/app/invoices/{ids['SMK-5']}/promise", data={"csrf": csrf, "promised_date": promised}
    )
    check(r.status_code == 303, "promise to pay saved")

    r = c.post(f"/app/invoices/{ids['SMK-1']}/paid", data={"csrf": "wrong"})
    check(r.status_code == 403, "form without the right CSRF token rejected")

    logs.since_ms = int(time.time() * 1000) - 2_000
    r = c.post("/app/reminders/run", data={"csrf": csrf})
    m = re.search(r"Sent (\d+) reminders", r.text)
    check(m is not None and int(m.group(1)) >= 3, f"reminders sent now ({m.group(1) if m else 0})")

    links = logs.wait_for(r"DEV WhatsApp reminder to .*pay at (\S+)")
    check(len(links) >= 3, "reminders logged with pay links (not sent)")
    hindi = logs.wait_for(r"DEV WhatsApp reminder to \+919000000103 \[(hi)\]")
    check(bool(hindi), "Hindi customer gets the Hindi template")
    promise_sent = logs.wait_for(r"(SMK-5)", timeout=5)
    check(not promise_sent, "customer with an active promise is not reminded")

    r = c.post("/app/reminders/run", data={"csrf": csrf})
    check("Sent 0 reminders" in r.text, "running again sends nothing twice")

    pay_path = links[0].replace(base, "")
    p = httpx.get(base + pay_path, timeout=30)
    check(
        p.status_code == 200 and "upi://pay?pa=" in p.text and "data:image/svg+xml" in p.text,
        "pay page shows UPI button and QR",
    )
    check(
        p.headers.get("x-robots-tag") == "noindex, nofollow", "pay page hidden from search engines"
    )
    check(
        httpx.get(base + "/p/" + "x" * 32, timeout=30).status_code == 404, "unknown pay link is 404"
    )

    r = c.post(f"/app/invoices/{ids['SMK-1']}/paid", data={"csrf": csrf})
    check(r.status_code == 303, "mark paid")
    page = c.get("/app").text
    check("Smoke Sharma Traders" not in page, "paid invoice leaves the open list")

    billing = c.get("/app/billing").text
    check("Starter" in billing and "Growth" in billing, "billing page lists plans")

    r = httpx.post(base + "/webhooks/whatsapp", content=b'{"entry":[]}', timeout=30)
    check(r.status_code == 401, "WhatsApp webhook rejects unsigned calls")
    r = httpx.post(base + "/webhooks/razorpay", content=b"{}", timeout=30)
    check(r.status_code == 401, "Razorpay webhook rejects unsigned calls")

    r = c.post("/logout", data={"csrf": csrf})
    check(r.status_code == 303 and c.get("/app").status_code == 303, "sign out ends the session")

    summary()


if __name__ == "__main__":
    main()
