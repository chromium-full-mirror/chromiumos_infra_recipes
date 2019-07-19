# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.recipes.chromeos.test_platform.cros_test_platform import \
  CrosTestPlatformProperties
from PB.test_platform.steps.enumeration import \
  EnumerationRequest, EnumerationResponse
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest, SchedulerTrafficSplitResponse
from PB.test_platform.steps.execution import ExecuteRequest
from PB.test_platform.request import Request
from PB.test_platform.config.config import Config

from google.protobuf import json_format

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_test_platform'
]

PROPERTIES = CrosTestPlatformProperties


def enumerate_tests(api, request):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * request: test_platform.Request instance.

  Returns: EnumerationResponse.
  """
  with api.step.nest('enumerate tests'):
    enum_request = EnumerationRequest(
      metadata=request.params.metadata,
      test_plan=request.test_plan,
    )
    return api.cros_test_platform.enumerate(enum_request)


def split(api, request):
  """Determine which backend will execute the request.

  Args:
    * api (object): See RunSteps documentation.
    * request: test_platform.Request instance.

  Returns: (test_platform.Request, bool (skylab)) tuple.
  """
  with api.step.nest('traffic split'):
    split_req = SchedulerTrafficSplitRequest(request=request)
    split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)

    autotest_request = split_resp.autotest_request
    skylab_request = split_resp.skylab_request
    # Rely on ByteSize of protos to determine which message is nonempty.
    has_autotest = bool(autotest_request.ByteSize())
    has_skylab = bool(skylab_request.ByteSize())
    if has_autotest and has_skylab:
      raise ValueError('Traffic splits contains both autotest and skylab '
                       'components; this is not supported.')
    if not (has_autotest or has_skylab):
      raise ValueError('Traffic split contains no traffic for either autotest '
                       'or skylab.')

    request = skylab_request if has_skylab else autotest_request
    return request, has_skylab


def execute(api, request, enumeration, config, use_skylab):
  """Execute request in the correct backend.

  Args:
    request: test_platform.Request instance.
    enumeration: EnumerationResponse instance.
    config: test_platform.Config instance.
    use_skylab: bool indicating which backend to run in
                (True -> skylab, False -> autotest).
  """
  with api.step.nest('execute'):
    exec_req = ExecuteRequest(
      request_params=request.params,
      enumeration=enumeration,
      config=config
    )
    if use_skylab:
      return api.cros_test_platform.skylab_execute(exec_req)
    else:
      return api.cros_test_platform.autotest_execute(exec_req)


def RunSteps(api, properties):
  request, skylab = split(api, properties.request)

  enumeration = enumerate_tests(api, request)

  execute(api, request, enumeration, properties.config, skylab)


def GenTests(api):
  # Traffic split with no traffic to either autotest or skylab
  # should cause recipe crash.
  yield (
    api.test('no traffic') + #
    api.expect_exception("ValueError")
  )

  # Traffic split with traffic to both autotest and skylab
  # should cause recipe crash.
  dual_traffic_split = SchedulerTrafficSplitResponse(
    autotest_request=Request(
      test_plan=Request.TestPlan(
        suite=[Request.Suite(name="foo")]
      ),
    ),
    skylab_request=Request(
      test_plan=Request.TestPlan(
        suite=[Request.Suite(name="foo")]
      ),
    ),
  )
  dual_traffic_split_json = json_format.MessageToJson(dual_traffic_split)
  yield (
    api.test('dual traffic') + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
    stdout=api.raw_io.output(dual_traffic_split_json)) + #
    api.expect_exception("ValueError")
  )

  # An end-to-end run with traffic splitting to skylab.
  e2e_request = Request(
    params=Request.Params(
      hardware_attributes=Request.Params.HardwareAttributes(
        model='foo-model'
      ),
      metadata=Request.Params.Metadata(
        test_metadata_url="foo-metadata-url"
      )
    ),
    test_plan=Request.TestPlan(
      suite=[Request.Suite(name="foo-suite")]
    ),
  )
  e2e_config = Config(
    skylab_worker=Config.SkylabWorker(
      luci_project='foo luci project'
    )
  )
  e2e_split_response_skylab = SchedulerTrafficSplitResponse(
    skylab_request=e2e_request
  )
  # Note: using raw JSON here to avoid needing to import the chromite
  # protos.
  e2e_enumeration_response = """
  {
    "autotest_tests": [{"name": "foo-test"}]
  }
    """
  yield (
    api.test('end-to-end with skylab execution') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(json_format.MessageToJson(
                  e2e_split_response_skylab))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_response))
  )

  # An end-to-end run with traffic splitting to autotest.
  e2e_split_response_autotest = SchedulerTrafficSplitResponse(
    autotest_request=e2e_request
  )
  yield (
    api.test('end-to-end with autotest execution') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(json_format.MessageToJson(
                  e2e_split_response_autotest))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_response))
  )