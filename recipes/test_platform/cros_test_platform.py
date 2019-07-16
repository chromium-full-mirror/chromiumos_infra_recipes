# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.recipes.chromeos.test_platform.cros_test_platform import \
  CrosTestPlatformProperties
from PB.test_platform.steps.enumeration import EnumerationRequest
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest
from PB.test_platform.steps.execution import ExecuteRequest


DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_test_platform'
]

PROPERTIES = CrosTestPlatformProperties


def enumerate_tests(api, properties):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * properties (CrosTestPlatformProperties): The input request.

  Returns: EnumerationResponse.
  """
  with api.step.nest('enumerate tests'):
    enum_request = EnumerationRequest()
    enum_request.metadata.CopyFrom(properties.request.params.metadata)
    enum_request.test_plan.CopyFrom(properties.request.test_plan)
    return api.cros_test_platform.enumerate(enum_request)


def split(api, properties):
  """Determine which backend will execute the request."""
  with api.step.nest('traffic split'):
    split_req = SchedulerTrafficSplitRequest()
    split_req.request.CopyFrom(properties.request)
    return api.cros_test_platform.scheduler_traffic_split(split_req)


def execute(api, properties, enumeration, traffic_split):
  """Execute request in the correct backend."""
  with api.step.nest('execute'):
    exec_req = ExecuteRequest()
    exec_req.request_params.CopyFrom(properties.request.params)
    exec_req.enumeration.CopyFrom(enumeration)
    exec_req.config.CopyFrom(properties.config)
    # TODO(akeshet): Respect traffic splitter; don't just blindly use skylab.
    return api.cros_test_platform.skylab_execute(exec_req)


def RunSteps(api, properties):
  enumeration = enumerate_tests(api, properties)
  traffic_split = split(api, properties)
  execute(api, properties, enumeration, traffic_split)


def GenTests(api):
  yield (api.test('basic'))
