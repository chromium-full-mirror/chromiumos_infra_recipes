# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromite.api.sysroot import InstallPackagesResponse
from PB.recipe_modules.chromeos.analysis_service.examples.full import FullProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'analysis_service',
]


PROPERTIES = FullProperties

# Test JSON protos.
INSTALL_PACKAGES_REQUEST = '''
{
   "sysroot":{
      "path":"/a/b/c"
   }
}
'''

INSTALL_PACKAGES_RESPONSE = '''
{
   "failed_package_data":[
      {
         "name":{
             "package_name":"A package"
         },
         "log_path":{
             "path":"/path/to/log"
         }
      }
   ]
}
'''


def RunSteps(api: RecipeApi, properties: FullProperties) -> None:
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
  api.analysis_service.publish_event(
      request=install_packages_request,
      response=install_packages_response,
      request_time=request_time,
      response_time=response_time,
      step_data=test_step_data,
      step_output=test_step_data.stdout,
      max_stdout_stderr_bytes=properties.max_stdout_stderr_bytes,
  )

  # Publish a step with non-zero retcode
  try:
    api.step('A test step with retcode', cmd=['echo', 'hello world'])
  except api.step.StepFailure as e:
    api.analysis_service.publish_event(
        request=install_packages_request,
        response=install_packages_response,
        request_time=request_time,
        response_time=response_time,
        step_data=e.result,
        max_stdout_stderr_bytes=properties.max_stdout_stderr_bytes,
    )

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


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(),
      api.step_data('A test step with retcode', retcode=5),
      api.step_data('A test step with timeout', times_out_after=5),
      api.step_data('basic_with_stdout',
                    stdout=api.raw_io.output('Test output'),
                    stderr=api.raw_io.output('Errors')),
      api.properties(FullProperties(max_stdout_stderr_bytes=1024)),
  )

  yield api.test(
      'basic-nonascii',
      api.buildbucket.ci_build(),
      api.step_data(
          'basic_with_stdout',
          # coding: utf8
          stdout=api.raw_io.output('國華'),
          stderr=api.raw_io.output('Errors')),
      api.properties(FullProperties(max_stdout_stderr_bytes=1024)),
  )

  yield api.test(
      'basic-truncated',
      api.buildbucket.ci_build(),
      api.step_data('basic_with_stdout',
                    stdout=api.raw_io.output('Test output'),
                    stderr=api.raw_io.output('Errors')),
      api.properties(FullProperties(max_stdout_stderr_bytes=4)),
  )

  # This test uses unicode characters aligned to force the truncation method to
  # try to split a character in half.
  yield api.test(
      'unicode-truncated',
      api.buildbucket.ci_build(),
      api.step_data('basic_with_stdout',
                    stdout=api.raw_io.output('Test ομτρμt'),
                    stderr=api.raw_io.output('Errors')),
      api.properties(FullProperties(max_stdout_stderr_bytes=4)),
  )
