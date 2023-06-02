# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_ensure_labpack.py tests that the labpack recipe module reports
success on the ensure_labpack step when the fake file .../labpack/labpack
exists.
"""

from recipe_engine import post_process
from PB.test_platform.skylab_test_runner.common_config import CommonConfig
from google.protobuf.json_format import ParseDict

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/step', 'recipe_engine/path',
    'labpack'
]


def to_message(o, message):
  # Don't modify scalars.
  if isinstance(o, (int, float, str, bool)):
    return o
  return ParseDict(o, message)


def make_common_config(enabled, allow_list, deny_list):
  assert isinstance(enabled, bool)
  assert not isinstance(allow_list, (str, bytes))
  assert not isinstance(deny_list, (str, bytes))
  assert (not allow_list) or (not deny_list)
  out = {"enable_ile_de_france_config": {}}
  out["enable_ile_de_france_config"]["enabled"] = enabled
  if allow_list:
    out["enable_ile_de_france_config"]["allow_list"] = {"models": allow_list}
  if deny_list:
    out["enable_ile_de_france_config"]["deny_list"] = {
        "models": deny_list
    }  # pragma: nocover
  return to_message(out, CommonConfig())


def RunSteps(api):
  with api.step.nest('labpack test suite'):
    with api.step.nest('test utility methods'):
      assert to_message(4, None) == 4
      assert isinstance(to_message({}, CommonConfig()), CommonConfig)
    with api.step.nest('ready dut becomes ready'):
      assert api.labpack.execute_ile_de_france(
          common_config=make_common_config(False, None, None),
          dut_state="ready",
      ) == "ready"
    with api.step.nest('needs repair eve becomes needs_repair'):
      assert api.labpack.execute_ile_de_france(
          dut_state="needs_repair",
          common_config=make_common_config(True, ["eve"], None), models=["eve"],
          hostnames=["fake-hostname"]) == "needs_repair"


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
