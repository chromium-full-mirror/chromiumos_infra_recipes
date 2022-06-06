# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import json
import six
import zlib
from RECIPE_MODULES.chromeos.skylab import structs

from recipe_engine import recipe_test_api

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState

from google.protobuf import struct_pb2
from google.protobuf import json_format


class SkylabTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def hw_test_unit(self, common=None, hw_tests=None):
    if common is None:
      common = TestUnitCommon(
          build_target=BuildTarget(name='build_target_name'),
          build_payload=BuildPayload(
              artifacts_gs_bucket='gsbucket',
              artifacts_gs_path='gspath',
          ),
      )
    if hw_tests is None:
      hw_test_cfg = HwTestCfg(hw_test=[self.hw_test()])  # pragma: no cover
    else:
      hw_test_cfg = HwTestCfg(hw_test=hw_tests)
    return HwTestUnit(common=common, hw_test_cfg=hw_test_cfg)

  def hw_test(self, name=None, suite=None, board=None, critical=True):
    return HwTestCfg.HwTest(
        common=TestSuiteCommon(
            display_name=name or 'target.hw.bvt-cq',
            critical={'value': critical},
        ),
        suite=suite or 'bvt-cq',
        skylab_board=board or 'target',
        pool='recipe_test_pool',
    )

  def skylab_task(self, bid=None, url=None, test=None, unit=None):
    if test is None and unit is None:
      unit = self.hw_test_unit()  # pragma: no cover
      test = unit.hw_test_cfg.hw_test[0]  # pragma: no cover
    elif test is None:
      test = unit.hw_test_cfg.hw_test[0]  # pragma: no cover
    else:
      unit = self.hw_test_unit(hw_tests=[test])
    return structs.SkylabTask(id=bid or 1234, url=url or 'https://google.com',
                              test=test, unit=unit)

  def skylab_result(self, task=None, status=common_pb2.SUCCESS,
                    child_results=None):
    return structs.SkylabResult(
        task=task or self.skylab_task(),
        status=status,
        child_results=child_results or [],
    )  # pragma: no cover

  @staticmethod
  def marshal_responses(responses):
    """Get the tagged responses from a response json, as a dict."""
    responses_dict = json_format.MessageToDict(responses)
    return responses_dict.get('taggedResponses', {})

  @staticmethod
  def base64_compress_dict(some_dict):
    """Compress a dict into zlib format, and then base64-encode it."""
    # TODO(b/217973414): Clean up when we no longer need to fix the separator
    # spacing between py2 and py3
    dict_json = json.dumps(some_dict, separators=(',', ':'), sort_keys=True)
    return base64.b64encode(zlib.compress(six.ensure_binary(dict_json)))

  @staticmethod
  def base64_compress_proto(proto):
    """Serialize a proto to binary, compress it into zlib, and b64-encode it."""
    # TODO(b/217973414): No need to ensure deterministic ordering once we no
    # longer need to ensure parity between PY2 and PY3.
    wire_format = proto.SerializeToString(deterministic=True)
    return base64.b64encode(zlib.compress(wire_format))

  def test_with_multi_response(
      self, bid, names, task_state=TaskState(verdict=TaskState.VERDICT_PASSED),
      exclude_json=False):
    return self._with_multi_response(bid, names, task_state,
                                     _json=not exclude_json)

  def _with_multi_response(self, bid, names, task_state, _json=True):
    return build_pb2.Build(
        id=bid, output=build_pb2.Build.Output(
            properties=self._multi_response(names, task_state, _json)))

  def _multi_response(self, names, task_state, _json):
    responses_blob = self._responses_json_dict(names, task_state)
    responses_obj = json_format.Parse(
        json.dumps({'tagged_responses': responses_blob}), ExecuteResponses(),
        ignore_unknown_fields=True)
    second_responses_blob = self.marshal_responses(responses_obj)
    comp_string = self.base64_compress_proto(responses_obj)
    overall = {'compressed_responses': six.ensure_str(comp_string)}
    if _json:
      overall['responses'] = second_responses_blob
      overall['compressed_json_responses'] = six.ensure_str(
          self.base64_compress_dict(second_responses_blob))
    return json_format.Parse(json.dumps(overall), struct_pb2.Struct())

  def _responses_json_dict(self, names, task_state):
    response_obj = json.loads(self._response_json(task_state))
    return {name: response_obj for name in names}

  def _response_json(self, task_state):
    return """{
    "state": {
        "verdict": "%s",
        "lifeCycle": "%s"
    },
    "taskResults": [
        {
            "state": {
                "verdict": "VERDICT_PASSED",
                "lifeCycle": "LIFE_CYCLE_COMPLETED"
            },
            "taskUrl": "https://chromeos-swarming.appspot.com/task?id=471a63bc9c481010",
            "name": "cheets_NotificationTest",
            "logUrl": "https://stainless.corp.google.com/browse/chromeos-autotest-results/swarming-471a63bc9c481010/",
            "testCases": [
                {
                    "name": "tast",
                    "verdict": "VERDICT_PASSED"
                },
                {
                    "name": "tast.camera.TakesGreatPhotos",
                    "verdict": "VERDICT_PASSED"
                }
            ]
        }
    ]
}
""" % (
        task_state.verdict,
        task_state.life_cycle,
    )
