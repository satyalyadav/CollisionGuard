"""Tiny local web demo for the CollisionGuard product.

    PYTHONPATH=src python3 scripts/serve_product.py
    open http://127.0.0.1:8765
"""

import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from collisionguard.cli import build_report

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>CollisionGuard</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 860px; margin: 40px auto; padding: 0 20px; color: #182026; }}
 h1 {{ font-size: 1.4rem; }}
 label {{ display: block; margin-top: 12px; font-weight: 600; }}
 input[type=text] {{ width: 100%; padding: 8px; box-sizing: border-box; }}
 textarea {{ width: 100%; min-height: 70px; padding: 8px; box-sizing: border-box; }}
 button {{ margin-top: 14px; padding: 9px 16px; }}
 .band {{ padding: 10px 14px; border-radius: 6px; display: inline-block; font-weight: 700; }}
 .low {{ background: #e7f4e8; color: #1f5c2a; }}
 .elevated {{ background: #fff4d6; color: #6d4c00; }}
 .high {{ background: #fde7e7; color: #7a1f1f; }}
 code {{ background: #f2f4f6; padding: 1px 4px; }}
 .muted {{ color: #5a6672; }}
 ul {{ margin: 6px 0 0 18px; padding: 0; }}
</style>
<h1>CollisionGuard</h1>
<p class="muted">Experimental pre-start merge-risk triage. It ranks pairs; it does not guarantee a merge.</p>
<form method="post" action="/score">
 <label>Repository path</label>
 <input type="text" name="repo" value="{repo}">
 <label>Task A</label>
 <textarea name="task_a">{task_a}</textarea>
 <label>Task B</label>
 <textarea name="task_b">{task_b}</textarea>
 <label>Agent A</label><input type="text" name="agent_a" value="{agent_a}">
 <label>Agent B</label><input type="text" name="agent_b" value="{agent_b}">
 <button type="submit">Score pair</button>
</form>
{result}
</html>"""


def _render_result(report):
    risk = report["risk"]
    reference = report.get("band_reference") or {}
    files_a = "".join(f"<li>{html.escape(row['path'])}</li>"
                      for row in report["likely_files"]["a"][:5])
    files_b = "".join(f"<li>{html.escape(row['path'])}</li>"
                      for row in report["likely_files"]["b"][:5])
    shared = "".join(f"<li>{html.escape(path)}</li>"
                     for path in report["likely_files"]["shared"][:5])
    reasons = "".join(
        f"<li>{html.escape(item['reason'])} ({item['direction']} risk)</li>"
        for item in report["reasons"])
    rate = f"{reference.get('rate', 0):.1%} ({reference.get('conflicts', 0)}/{reference.get('pairs', 0)} historical pairs)"
    return f"""
<hr>
<h2>Result</h2>
<p><span class="band {risk['band']}">{risk['band'].upper()} risk</span>
 &nbsp; percentile {risk['percentile'] * 100:.0f}, calibrated probability {risk['calibrated_probability']:.2f}</p>
<p class="muted">Historical conflict rate for this band: {rate}</p>
<h3>Likely files for A</h3><ul>{files_a}</ul>
<h3>Likely files for B</h3><ul>{files_b}</ul>
<h3>Shared predicted files</h3><ul>{shared or '<li>None</li>'}</ul>
<h3>Top factors</h3><ul>{reasons or '<li>None</li>'}</ul>
<p class="muted">{html.escape(report['caveat'])}</p>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(PAGE.format(repo=".", task_a="", task_b="",
                               agent_a="", agent_b="", result=""))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode("utf-8"))
        repo = values.get("repo", ["."])[0]
        task_a = values.get("task_a", [""])[0]
        task_b = values.get("task_b", [""])[0]
        agent_a = values.get("agent_a", [""])[0] or None
        agent_b = values.get("agent_b", [""])[0] or None
        try:
            report = build_report(repo, task_a, task_b, agent_a, agent_b)
            result = _render_result(report)
        except Exception as exc:  # show input errors in the page
            result = f"<p><strong>Error:</strong> {html.escape(str(exc))}</p>"
        self._send(PAGE.format(repo=html.escape(repo), task_a=html.escape(task_a),
                               task_b=html.escape(task_b),
                               agent_a=html.escape(agent_a or ""),
                               agent_b=html.escape(agent_b or ""),
                               result=result))

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("CollisionGuard demo on http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
