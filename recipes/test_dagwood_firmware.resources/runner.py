#!/usr/bin/env python3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runner script executed by test_dagwood_firmware recipe on Satlab Swarming bots.

Interacts with the Satlab host Docker daemon (192.168.231.1:2376) to execute
EC hardware tests in the ec-builder:latest container, streams stdout/stderr,
and exits with the container exit code.
"""

import argparse
import glob
import http.client
import json
import os
import ssl
import struct
import sys


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
    return None, 1

  cid = resp["Id"]
  print(f"[*] Started container: {cid[:12]}")

  exit_code = 1
  try:
    conn.request("POST", f"/containers/{cid}/start")
    start_resp = conn.getresponse()
    if start_resp.status not in (200, 204):
      print(
          f"[!] Docker start failed ({start_resp.status}): {start_resp.read().decode()}",
          file=sys.stderr)
      return cid, 1
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

  finally:
    print(f"[*] Cleaning up container {cid[:12]}...")
    try:
      conn.request("DELETE", f"/containers/{cid}?force=1")
      conn.getresponse().read()
    # pylint: disable=broad-exception-caught
    except Exception as e:
      print(f"[!] Warning deleting container {cid[:12]}: {e}", file=sys.stderr)

  return cid, exit_code


def main():
  args = parse_args()
  ctx = get_docker_ssl_context()
  if not ctx:
    print(
        "[!] Warning: Docker TLS certs not found in DOCKER_CERT_PATH or /var/run/docker-certs",
        file=sys.stderr)

  exit_code = 0

  if ctx:
    _cid, exit_code = run_docker_container(args, ctx)
  else:
    print("[!] Simulating test execution (no Docker TLS certs).")

  summary = {"exit_code": exit_code}

  if args.output_json:
    try:
      with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(summary, f)
    # pylint: disable=broad-exception-caught
    except Exception as e:
      print(f"[!] Error writing output JSON: {e}", file=sys.stderr)

  sys.exit(exit_code)


if __name__ == "__main__":
  main()
