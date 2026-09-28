"""Boot the real app and print what /connectivity actually reports."""
import json
import subprocess
import sys
import time
import urllib.request

proc = subprocess.Popen(
    [sys.executable, "-m", "amr.main", "--mock", "--web", "--port", "0"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
port = None
for _ in range(80):
    time.sleep(0.25)
    line = proc.stdout.readline()
    if not line:
        break
    if "web control on" in line:
        port = int(line.rsplit(":", 1)[1].strip())
        break
if port is None:
    print("FAILED TO BOOT")
    proc.kill()
    raise SystemExit(1)
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/connectivity", timeout=10) as r:
        body = json.loads(r.read().decode("utf-8"))
    print("HTTP 200 /connectivity")
    print("counts  :", body["counts"])
    print("wifi    :", body["wifi"]["status"], "| connected:", body["wifi"]["connected"],
          "| ssid:", body["wifi"]["ssid"])
    print("bluetooth:", body["bluetooth"]["status"], "| paired:",
          body["bluetooth"]["paired_devices"])
    print("ifaces  :", [(i["name"], i["kind"], i["up"]) for i in body["interfaces"]])
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/applications/state", timeout=10) as r:
        state = json.loads(r.read().decode("utf-8"))
    conn = [a for a in state["applications"]
            if a["category"] == "diagnostics" and a["id"] in
            ("connectivity_overview", "wifi_link", "bluetooth_link")]
    print("\nhub cards:")
    for a in conn:
        print(f"  {a['name']:34} {a['status']:18} {a['url']}")
finally:
    proc.terminate()
    proc.wait(timeout=10)
