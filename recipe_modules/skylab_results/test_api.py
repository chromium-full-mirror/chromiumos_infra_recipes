# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Mock returns from HW Tests."""

import base64
import json
import zlib

from RECIPE_MODULES.chromeos.skylab_results import structs
from google.protobuf import json_format
from google.protobuf import struct_pb2

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from recipe_engine import recipe_test_api


class SkylabResultsTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def hw_test_unit(self, common=None, hw_tests=None, suite=None):
    if common is None:
      common = TestUnitCommon(
          build_target=BuildTarget(name='build_target_name'),
          builder_name='builder_name',
          build_payload=BuildPayload(
              artifacts_gs_bucket='gsbucket',
              artifacts_gs_path='gspath',
          ),
      )
    if hw_tests is None:
      hw_test_cfg = HwTestCfg(hw_test=[self.hw_test(suite=suite)
                                      ])  # pragma: no cover
    else:
      hw_test_cfg = HwTestCfg(hw_test=hw_tests)
    return HwTestUnit(common=common, hw_test_cfg=hw_test_cfg)

  def hw_test(self, name=None, suite=None, board=None, critical=True):
    suite = suite or 'bvt-cq'
    name = name or 'target.hw.' + suite
    return HwTestCfg.HwTest(
        common=TestSuiteCommon(
            display_name=name,
            critical={'value': critical},
        ),
        suite=suite,
        skylab_board=board or 'target',
        pool='recipe_test_pool',
    )

  def skylab_task(self, bid=None, url=None, test=None, unit=None, suite=None):
    if test is None and unit is None:
      unit = self.hw_test_unit(suite=suite)
      test = unit.hw_test_cfg.hw_test[0]
    elif test is None:
      test = unit.hw_test_cfg.hw_test[0]  # pragma: no cover
    else:
      unit = self.hw_test_unit(hw_tests=[test], suite=suite)
    return structs.SkylabTask(id=bid or 1234, url=url or 'https://google.com',
                              test=test, unit=unit)

  def skylab_result(self, task=None, status=common_pb2.SUCCESS,
                    child_results=None):
    return structs.SkylabResult(
        task=task or self.skylab_task(),
        status=status,
        child_results=child_results or [],
    )

  @staticmethod
  def marshal_responses(responses):
    """Get the tagged responses from a response json, as a dict."""
    responses_dict = json_format.MessageToDict(responses)
    return responses_dict.get('taggedResponses', {})

  @staticmethod
  def base64_compress_dict(some_dict):
    """Compress a dict into zlib format, and then base64-encode it."""
    dict_json = json.dumps(some_dict)
    return base64.b64encode(zlib.compress(dict_json.encode()))

  @staticmethod
  def base64_compress_proto(proto) -> bytes:
    """Serialize a proto to binary, compress it into zlib, and b64-encode it."""
    wire_format = proto.SerializeToString(deterministic=True)
    return base64.b64encode(zlib.compress(wire_format))

  def test_with_multi_response(
      self, bid, names, task_state=TaskState(verdict=TaskState.VERDICT_PASSED),
      exclude_json=False, test_cases_verdict=TaskState.VERDICT_PASSED):
    return self._with_multi_response(bid, names, task_state,
                                     _json=not exclude_json,
                                     test_cases_verdict=test_cases_verdict)

  def _with_multi_response(self, bid, names, task_state, _json=True,
                           test_cases_verdict=TaskState.VERDICT_PASSED):
    return build_pb2.Build(
        id=bid, output=build_pb2.Build.Output(
            properties=self._multi_response(names, task_state, _json,
                                            test_cases_verdict)))

  def _multi_response(self, names, task_state, _json, test_cases_verdict):
    responses_blob = self._responses_json_dict(names, task_state,
                                               test_cases_verdict)
    responses_obj = json_format.Parse(
        json.dumps({'tagged_responses': responses_blob}), ExecuteResponses(),
        ignore_unknown_fields=True)
    second_responses_blob = self.marshal_responses(responses_obj)
    comp_string = self.base64_compress_proto(responses_obj).decode()
    overall = {'compressed_responses': comp_string}
    if _json:
      overall['responses'] = second_responses_blob
      overall['compressed_json_responses'] = self.base64_compress_dict(
          second_responses_blob).decode()
    return json_format.Parse(json.dumps(overall), struct_pb2.Struct())

  def _responses_json_dict(self, names, task_state, test_cases_verdict):
    response_obj = json.loads(
        self._response_json(task_state, test_cases_verdict))
    return {name: response_obj for name in names}

  def _response_json(self, task_state, test_cases_verdict):
    return '''{
    "state": {
        "verdict": "%s",
        "lifeCycle": "%s"
    },
    "taskResults": [
        {
            "state": {
                "verdict": "%s",
                "lifeCycle": "LIFE_CYCLE_COMPLETED"
            },
            "taskUrl": "https://chromeos-swarming.appspot.com/task?id=471a63bc9c481010",
            "name": "cheets_NotificationTest",
            "logUrl": "https://tests.chromeos.goog/p/chromeos/logs/unified/chromeos-autotest-results/swarming-471a63bc9c481010/",
            "testCases": [
                {
                    "name": "tast",
                    "verdict": "%s"
                },
                {
                    "name": "tast.camera.TakesGreatPhotos",
                    "verdict": "%s"
                }
            ]
        }
    ]
}
''' % (
        task_state.verdict,
        task_state.life_cycle,
        test_cases_verdict,
        test_cases_verdict,
        test_cases_verdict,
    )
