# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/buildbucket',
    'recipe_engine/properties', 'recipe_engine/raw_io', 'recipe_engine/step',
    'analysis_service'
]

from PB.chromite.api.sysroot import InstallPackagesRequest, InstallPackagesResponse
from PB.recipe_modules.chromeos.analysis_service.analysis_service import (
    AnalysisServiceProperties)

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

# Test JSON protos.
INSTALL_PACKAGES_REQUEST = """
{
   "sysroot":{
      "path":"/a/b/c"
   }
}
"""

INSTALL_PACKAGES_RESPONSE = """
{
   "failed_packages":[
      {
         "package_name":"A package"
      }
   ]
}
"""


def RunSteps(api):
  test_step_data = api.step('basic_with_stdout', cmd=['echo', 'hello world'],
                            stdout=api.raw_io.output(),
                            stderr=api.raw_io.output())

  install_packages_request = json_format.Parse(INSTALL_PACKAGES_REQUEST,
                                               InstallPackagesRequest())
  install_packages_response = json_format.Parse(INSTALL_PACKAGES_RESPONSE,
                                                InstallPackagesResponse())

  request_time = timestamp_pb2.Timestamp()
  request_time.FromSeconds(100)
  response_time = timestamp_pb2.Timestamp()
  response_time.FromSeconds(200)

  api.assertions.assertTrue(
      api.analysis_service.can_publish_event(
          request=install_packages_request, response=install_packages_response))
  api.analysis_service.publish_event(request=install_packages_request,
                                     response=install_packages_response,
                                     request_time=request_time,
                                     response_time=response_time,
                                     step_data=test_step_data,
                                     step_output=test_step_data.stdout)

  # Publish a step with non-zero retcode
  try:
    api.step('A test step with retcode', cmd=['echo', 'hello world'])
  except api.step.StepFailure as e:
    api.analysis_service.publish_event(request=install_packages_request,
                                       response=install_packages_response,
                                       request_time=request_time,
                                       response_time=response_time,
                                       step_data=e.result)

  try:
    api.step('A test step with timeout', cmd=['echo', 'hello world'], timeout=1)
  except api.step.StepFailure as e:
    api.analysis_service.publish_event(request=install_packages_request,
                                       response=install_packages_response,
                                       request_time=request_time,
                                       response_time=response_time,
                                       step_data=e.result)

  # Pass in the request and response backwards, shouldn't work in this case
  # because the types are wrong.
  api.assertions.assertFalse(
      api.analysis_service.can_publish_event(request=install_packages_response,
                                             response=install_packages_request))
  # Try calling anyway, should raise an error.
  api.assertions.assertRaises(ValueError, api.analysis_service.publish_event,
                              request=install_packages_response,
                              response=install_packages_request,
                              request_time=request_time,
                              response_time=response_time,
                              step_data=test_step_data)

  request_time.FromSeconds(300)
  # If request_time is after response_time, the call should fail.
  api.assertions.assertRaises(ValueError, api.analysis_service.publish_event,
                              request=install_packages_request,
                              response=install_packages_response,
                              request_time=request_time,
                              response_time=response_time,
                              step_data=test_step_data)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(),
      api.step_data('A test step with retcode', retcode=5),
      api.step_data('A test step with timeout', times_out_after=5),
      api.step_data('basic_with_stdout',
                    stdout=api.raw_io.output('Test output'),
                    stderr=api.raw_io.output('Errors')),
      api.properties(
          **{
              '$chromeos/analysis_service':
                  AnalysisServiceProperties(max_stdout_stderr_bytes=1024)
          }),
  )

  yield api.test(
      'basic-nonascii',
      api.buildbucket.ci_build(),
      api.step_data(
          'basic_with_stdout',
          # coding: utf8
          stdout=api.raw_io.output('國華'),
          stderr=api.raw_io.output('Errors')),
      api.properties(
          **{
              '$chromeos/analysis_service':
                  AnalysisServiceProperties(max_stdout_stderr_bytes=1024)
          }),
  )

  yield api.test(
      'basic-truncated',
      api.buildbucket.ci_build(),
      api.step_data('basic_with_stdout',
                    stdout=api.raw_io.output('Test output'),
                    stderr=api.raw_io.output('Errors')),
      api.properties(
          **{
              '$chromeos/analysis_service':
                  AnalysisServiceProperties(max_stdout_stderr_bytes=4)
          }),
  )
