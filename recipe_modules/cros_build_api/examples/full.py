# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api import binhost
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.analysis_service.analysis_service import AnalysisServiceProperties
from PB.recipe_modules.chromeos.cros_build_api.cros_build_api import CrosBuildApiProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  _ = api.cros_build_api.GetVersion()
  # Check that a simple build API call works. Use protos defined in
  # chromiumos_infra_proto/src/analysis_service/analysis_service.proto so that
  # the analysis_service will write an event for the result.
  input_proto = binhost.PrepareBinhostUploadsRequest(
      build_target=BuildTarget(name='target'))
  output_type = binhost.PrepareBinhostUploadsResponse.DESCRIPTOR
  output_proto = api.cros_build_api(
      'chromite.api.BinhostService/PrepareBinhostsUploads', input_proto,
      output_type, test_output_data='{"uploads_dir": "/binhosts/path"}',
      test_teelog_data='Logfile contents for build_cmd.')
  api.assertions.assertEqual(output_proto.uploads_dir, '/binhosts/path')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'basic-with-output',
      api.properties(
          **{
              # This property is needed to capture tee_log output of build_api.
              '$chromeos/cros_build_api':
                  CrosBuildApiProperties(capture_stdout_stderr=True),
              # This property is needed to attach build api output to event.
              '$chromeos/analysis_service':
                  AnalysisServiceProperties(max_stdout_stderr_bytes=64)
          }))
