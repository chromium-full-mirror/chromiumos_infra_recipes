# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import binhost
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_build_api.cros_build_api import CrosBuildApiProperties
from recipe_engine.post_process import MustRun, DropExpectation, \
  StepCommandContains

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_build_api',
]



def RunSteps(api):
  _ = api.cros_build_api.GetVersion()
  _ = api.cros_build_api.new_result_path()
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
          }))

  yield api.test(
      'reset-chromite',
      api.buildbucket.ci_build(
          builder='atlas-cq',
          experiments=['chromeos.cros_build_api.deployable_chromite']),
      api.step_data(
          'call chromite.api.BinhostService/PrepareBinhostsUploads.read chromite version',
          api.file.read_text('deadbeef')),
      api.post_check(
          MustRun,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout'
      ),
      api.post_check(
          StepCommandContains,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout',
          ['deadbeef']),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'reset-chromite-with-fetch',
      api.buildbucket.ci_build(
          builder='atlas-cq',
          experiments=['chromeos.cros_build_api.deployable_chromite']),
      api.step_data(
          'call chromite.api.BinhostService/PrepareBinhostsUploads.read chromite version',
          api.file.read_text('deadbeef')),
      api.step_data(
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout',
          stdout=api.raw_io.output_text(
              'fatal: reference is not a tree: deadbeef'), retcode=1),
      api.post_check(
          MustRun,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout'
      ),
      api.post_check(
          MustRun,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.fast-forwarding git checkout.git fetch'
      ),
      api.post_check(
          MustRun,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.fast-forwarding git checkout.git checkout'
      ),
      api.post_check(
          StepCommandContains,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.fast-forwarding git checkout.git checkout',
          ['deadbeef']),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'reset-chromite-other-err',
      api.buildbucket.ci_build(
          builder='atlas-cq',
          experiments=['chromeos.cros_build_api.deployable_chromite']),
      api.step_data(
          'call chromite.api.BinhostService/PrepareBinhostsUploads.read chromite version',
          api.file.read_text('deadbeef')),
      api.step_data(
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout',
          retcode=1),
      api.post_check(
          MustRun,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout'
      ), api.post_process(DropExpectation), status='INFRA_FAILURE')
