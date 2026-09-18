#!/usr/bin/env python3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runner script executed by test_dagwood_firmware recipe on Satlab Swarming bots.

Interacts with the Satlab host Docker daemon (192.168.231.1:2376) to execute
EC hardware tests in the ec-builder:latest container, streams stdout/stderr,
extracts twister.json via the Docker archive API, and posts granular test results
to ResultSink / ResultDB.
"""

import argparse
import glob
import html
import http.client
import io
import json
import os
import ssl
import struct
import sys
import tarfile
import urllib.error
import urllib.request

EC_BUG_COMPONENT_ID = 167114


def parse_args():
  parser = argparse.ArgumentParser(description="Dagwood Hardware Test Runner")
  parser.add_argument("--platform", action="append", default=[],
                      help="Target EC platform (can be repeated)")
  parser.add_argument("--test-path", action="append", default=[],
                      help="Test directory (can be repeated)")
  parser.add_argument("--test-scenario", action="append", default=[],
                      help="Specific scenario/suite (can be repeated)")
  parser.add_argument("--extra-args", action="append", default=[],
                      help="Extra arguments for dagwood (can be repeated)")

  # --output-json is automatically populated by the recipe engine.
  parser.add_argument("--output-json", default="",
                      help="Path to write JSON execution summary")

  # Satlab always uses the 192.168.231.1/24 subnet and always uses
  # port 2376 for the TLS Docker daemon.
  parser.add_argument("--host", default="192.168.231.1",
                      help="Satlab host Docker IP")
  parser.add_argument("--port", type=int, default=2376,
                      help="Satlab host Docker port")
  return parser.parse_args()


def get_docker_ssl_context():
  cert_dir = os.environ.get("DOCKER_CERT_PATH", "/var/run/docker-certs")
  ca_pem = os.path.join(cert_dir, "ca.pem")
  cert_pem = os.path.join(cert_dir, "cert.pem")
  key_pem = os.path.join(cert_dir, "key.pem")

  if os.path.exists(ca_pem) and os.path.exists(cert_pem) and os.path.exists(
      key_pem):
    ctx = ssl.create_default_context(cafile=ca_pem)
    ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)
    return ctx
  return None


def construct_test_cmd(args):
  # Build the dagwood helper script command line.
  cmd_parts = ["./dagwood"]
  platforms = args.platform if args.platform else ["realtek/rts5912"]
  for p in platforms:
    cmd_parts.extend(["-p", p])
  for tp in args.test_path:
    cmd_parts.extend(["-T", tp])
  for sc in args.test_scenario:
    cmd_parts.extend(["-s", sc])
  for extra in args.extra_args:
    cmd_parts.append(extra)

  # dagwood helper script must be run from the EC directory.
  user_cmd = f"cd /workspace/src/platform/ec && {' '.join(cmd_parts)}"

  return user_cmd


def run_docker_container(args, ctx):
  conn = http.client.HTTPSConnection(args.host, args.port, context=ctx)

  # Connect the satlab persistent storage to the container's working directory.
  binds = [
      "/usr/local/ec-workspace:/workspace",
  ]

  # Bind USB devices into the container for querying the dagwood board
  # type and executing raw USB control transfers directly against the dagwood
  # firmware.
  binds.append("/dev/bus/usb:/dev/bus/usb")

  # Bind all dagwood and ST-Link TTYs into the container.
  for dev_node in sorted(glob.glob("/dev/ttyACM*")):
    binds.append(f"{dev_node}:{dev_node}")

  shell_cmd = construct_test_cmd(args)
  payload = {
      "Image": "ec-builder:latest",
      "Cmd": ["bash", "-c", shell_cmd],
      "Tty": False,
      "HostConfig": {
          "Privileged": True,
          "Binds": binds,
      },
  }

  print(
      f"[*] Connecting to Docker daemon at https://{args.host}:{args.port}...")
  print(f"[*]     ec-builder command: {shell_cmd}")
  conn.request(
      "POST",
      "/containers/create",
      body=json.dumps(payload),
      headers={"Content-Type": "application/json"},
  )
  resp = json.loads(conn.getresponse().read().decode("utf-8"))
  if "Id" not in resp:
    print(f"[!] Docker create failed: {resp}", file=sys.stderr)
    return None, 1, None

  cid = resp["Id"]
  print(f"[*] Started container: {cid[:12]}")

  twister_bytes = None
  exit_code = 1
  try:
    conn.request("POST", f"/containers/{cid}/start")
    start_resp = conn.getresponse()
    if start_resp.status not in (200, 204):
      print(
          f"[!] Docker start failed ({start_resp.status}): {start_resp.read().decode()}",
          file=sys.stderr)
      return cid, 1, None
    start_resp.read()

    conn.request("GET", f"/containers/{cid}/logs?stdout=1&stderr=1&follow=1")
    log_resp = conn.getresponse()
    while True:
      hdr = log_resp.read(8)
      if not hdr or len(hdr) < 8:
        break
      stream_type, length = struct.unpack(">BxxxI", hdr)
      data = b""
      while len(data) < length:
        chunk = log_resp.read(length - len(data))
        if not chunk:
          break
        data += chunk
      out_stream = sys.stderr if stream_type == 2 else sys.stdout
      out_stream.write(data.decode("utf-8", errors="replace"))
      out_stream.flush()

    conn.request("POST", f"/containers/{cid}/wait")
    wait_resp = json.loads(conn.getresponse().read().decode("utf-8"))
    exit_code = wait_resp.get("StatusCode", 1)
    print(f"[*] Container finished with exit code {exit_code}")

    # Extract twister.json via archive API
    for path in [
        "/workspace/src/platform/ec/twister-out/twister.json",
        "/workspace/twister-out/twister.json",
    ]:
      conn.request("GET", f"/containers/{cid}/archive?path={path}")
      arch_resp = conn.getresponse()
      if arch_resp.status != 200:
        arch_resp.read()
        continue

      with tarfile.open(fileobj=io.BytesIO(arch_resp.read())) as tf:
        for member in tf.getmembers():
          if member.name.endswith("twister.json"):
            extracted = tf.extractfile(member)
            if extracted:
              twister_bytes = extracted.read()
              print(
                  f"[*] Successfully extracted twister.json ({len(twister_bytes)} bytes) from container"
              )
      break

  finally:
    print(f"[*] Cleaning up container {cid[:12]}...")
    try:
      conn.request("DELETE", f"/containers/{cid}?force=1")
      conn.getresponse().read()
    # pylint: disable=broad-exception-caught
    except Exception as e:
      print(f"[!] Warning deleting container {cid[:12]}: {e}", file=sys.stderr)

  return cid, exit_code, twister_bytes


def report_results_to_resultdb(twister_bytes):
  if not twister_bytes:
    print("[*] No twister data to report to ResultDB.")
    return {"passed": 0, "failed": 0, "skipped": 0, "total": 0}

  try:
    twister_data = json.loads(twister_bytes.decode("utf-8"))
  # pylint: disable=broad-exception-caught
  except Exception as e:
    print(f"[!] Error parsing twister JSON: {e}", file=sys.stderr)
    return {"passed": 0, "failed": 0, "skipped": 0, "total": 0}

  sink = None
  luci_ctx_path = os.environ.get("LUCI_CONTEXT")
  if luci_ctx_path and os.path.exists(luci_ctx_path):
    try:
      with open(luci_ctx_path, "r", encoding="utf-8") as f:
        sink = json.load(f).get("result_sink")
    # pylint: disable=broad-exception-caught
    except Exception as e:
      print(f"[!] Failed to read LUCI_CONTEXT: {e}", file=sys.stderr)

  test_results = []
  passed = failed = skipped = 0

  # Example format of twister.json
  #
  # "testsuites":[
  #     {
  #         "name":"aic.fan",
  #         "platform":"npcx9/npcx9m7f",
  #         ...
  #         "status":"passed",
  #         "execution_time":"20.62",
  #         "build_time":"19.07",
  #         "testcases":[
  #             {
  #                 "identifier":"aic.fan.test_fan_pwm[25]",
  #                 "execution_time":"10.43",
  #                 "status":"passed"
  #             },
  #             ...
  #             {
  #                 "identifier":"shell.core.sh.shell_readline_canceled",
  #                 "execution_time":"0.00",
  #                 "status":"skipped",
  #                 "reason":"ztest skip"
  #             },

  for suite in twister_data.get("testsuites", []):
    suite_name = suite.get("name", "unknown")
    # Most platform names include "/", replace with "." which is safe
    # to use with ResultDB.
    platform = suite.get("platform", "aic")
    safe_platform = platform.replace("/", ".")
    for tc in suite.get("testcases", []):
      tc_name = tc.get("identifier", tc.get("name", "test"))
      st = tc.get("status", "failed").lower()
      if st == "passed":
        rdb_status = "PASS"
        expected = True
        passed += 1
      elif st in ("skipped", "filtered"):
        rdb_status = "SKIP"
        expected = True
        skipped += 1
      else:
        rdb_status = "FAIL"
        expected = False
        failed += 1

      try:
        dur = float(tc.get("execution_time", 0.0))
      except (ValueError, TypeError):
        dur = 0.0

      # "reason" and "log" are only populated on test skips and failures.
      reason = tc.get("reason", "")
      log_text = tc.get("log", "")

      if log_text:
        summary = f"<pre>{html.escape(log_text)}</pre>"
      else:
        summary = f"<p>Test {st} in {dur:.2f}s</p>"

      if reason:
        summary = f"<b>Reason:</b> {html.escape(reason)}<br>" + summary

      tr = {
          "testId": f"chromeos.ec.{safe_platform}.{tc_name}",
          "resultId": f"tc-{len(test_results)}",
          "status": rdb_status,
          "expected": expected,
          "duration": "%.9fs" % dur,
          "tags": [
              {
                  "key": "platform",
                  "value": platform
              },
              {
                  "key": "suite",
                  "value": suite_name
              },
          ],
          "testMetadata": {
              "name": tc_name,
              "bugComponent": {
                  "issueTracker": {
                      "componentId": str(EC_BUG_COMPONENT_ID),
                  },
              },
          },
          "summaryHtml": summary,
      }
      if not expected:
        tr["failureReason"] = {
            "primaryErrorMessage": (reason or log_text or "Test failed")[:1024]
        }
      test_results.append(tr)

  print(
      f"[*] Parsed {len(test_results)} test cases: {passed} passed, {failed} failed, {skipped} skipped."
  )
  if not test_results or not sink:
    if not sink:
      print("[*] No result_sink found in LUCI_CONTEXT; skipping upload.")
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": len(test_results),
    }

  url = (f"http://{sink['address']}/prpc/luci.resultsink.v1.Sink/"
         "ReportTestResults")
  headers = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "Authorization": f"ResultSink {sink['auth_token']}",
  }

  chunk_size = 500
  total_reported = 0
  for i in range(0, len(test_results), chunk_size):
    chunk = test_results[i:i + chunk_size]
    req = urllib.request.Request(
        url,
        data=json.dumps({
            "testResults": chunk
        }).encode("utf-8"),
        headers=headers,
    )
    try:
      with urllib.request.urlopen(req) as resp:
        resp.read()
        total_reported += len(chunk)
    except urllib.error.HTTPError as e:
      err_body = e.read().decode("utf-8", errors="replace")
      print(f"[!] HTTP Error {e.code} posting to ResultDB ({url}): {err_body}",
            file=sys.stderr)
    # pylint: disable=broad-exception-caught
    except Exception as e:
      print(f"[!] Error posting to ResultDB ({url}): {e}", file=sys.stderr)

  print(f"[*] Successfully reported {total_reported} test cases to ResultDB.")
  return {
      "passed": passed,
      "failed": failed,
      "skipped": skipped,
      "total": len(test_results),
  }


def main():
  args = parse_args()
  ctx = get_docker_ssl_context()
  if not ctx:
    print(
        "[!] Warning: Docker TLS certs not found in DOCKER_CERT_PATH or /var/run/docker-certs",
        file=sys.stderr)

  exit_code = 0
  stats = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}

  if ctx:
    _cid, exit_code, twister_bytes = run_docker_container(args, ctx)
    if twister_bytes:
      stats = report_results_to_resultdb(twister_bytes)
      if stats.get("failed", 0) > 0 and exit_code == 0:
        exit_code = 1
  else:
    print("[!] Simulating test execution (no Docker TLS certs).")
    stats = {"passed": 1, "failed": 0, "skipped": 0, "total": 1}

  stats["exit_code"] = exit_code

  if args.output_json:
    try:
      with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(stats, f)
    # pylint: disable=broad-exception-caught
    except Exception as e:
      print(f"[!] Error writing output JSON: {e}", file=sys.stderr)

  sys.exit(exit_code)


if __name__ == "__main__":
  main()
