#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Lists expected (board, model, test_plan) targets from staging configs."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> None:
  parser = argparse.ArgumentParser(
      description="Parse expected staging canary targets from fw_qual_automation."
  )
  parser.add_argument(
      "repo_dir",
      type=pathlib.Path,
      help="Path to the checked-out fw_qual_automation repository.",
  )
  args = parser.parse_args()

  protos_dir = args.repo_dir / "gen" / "protos"
  sys.path.insert(0, str(protos_dir))
  # pylint: disable=import-outside-toplevel,import-error
  from auto_qual import builder_config_pb2
  from google.protobuf import text_format

  staging_dir = args.repo_dir / "builder_configs" / "staging"
  seen: set[tuple[str, str, str]] = set()
  targets: list[dict[str, str]] = []

  for cfg_path in sorted(staging_dir.glob("*.txtpb")):
    cfg = text_format.Parse(
        cfg_path.read_text(encoding="utf-8"),
        builder_config_pb2.TestEffortBuilderConfigs(),
    )
    for bc in cfg.configs:
      for tmpl in bc.test_effort_templates:
        board = ""
        models: list[str] = []
        for dut in tmpl.duts:
          if not dut.HasField("dut"):
            continue
          which = dut.dut.WhichOneof("build")
          if which == "unibuild":
            if not board and dut.dut.unibuild.board:
              board = dut.dut.unibuild.board
            models.extend(
                m.model_name for m in dut.dut.unibuild.models if m.model_name)
          elif which == "individual" and dut.dut.individual.model_name:
            if not board:
              board = dut.dut.individual.model_name
            models.append(dut.dut.individual.model_name)

        plans = [
            tp.test_plan_name for tp in tmpl.test_plan if tp.test_plan_name
        ]
        for fot in tmpl.follow_on_testing:
          plans.extend(
              tp.test_plan_name for tp in fot.test_plan if tp.test_plan_name)
        for st in tmpl.scheduled_testing:
          plans.extend(
              tp.test_plan_name for tp in st.test_plan if tp.test_plan_name)

        if not board or not models or not plans:
          continue
        for model in models:
          for plan in plans:
            key = (board, model, plan)
            if key not in seen:
              seen.add(key)
              targets.append({
                  "board": board,
                  "model": model,
                  "test_plan": plan,
              })

  print(json.dumps(targets))


if __name__ == "__main__":
  main()
