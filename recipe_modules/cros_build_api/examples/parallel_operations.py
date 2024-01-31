# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import binhost
from PB.chromiumos.common import BuildTarget
from recipe_engine.post_process import MustRun, DropExpectation, \
  StepCommandContains, DoesNotRun

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_build_api',
]



def RunSteps(api):
  with api.cros_build_api.parallel_operations():
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
    # second call
    api.cros_build_api('chromite.api.BinhostService/PrepareBinhostsUploads',
                       input_proto, output_type,
                       test_output_data='{"uploads_dir": "/binhosts/path"}',
                       test_teelog_data='Logfile contents for build_cmd.')
    api.assertions.assertEqual(output_proto.uploads_dir, '/binhosts/path')


def GenTests(api):
  yield api.test(
      'only-does-git-checkout-once',
      api.buildbucket.ci_build(
          builder='atlas-cq',
          experiments=['chromeos.cros_build_api.deployable_chromite']),
      api.step_data('read chromite version', api.file.read_text('deadbeef')),
      api.post_check(MustRun, 'git checkout'),
      api.post_check(StepCommandContains, 'git checkout', ['deadbeef']),
      api.post_check(
          DoesNotRun,
          'call chromite.api.BinhostService/PrepareBinhostsUploads.git checkout'
      ),
      api.post_process(DropExpectation),
  )
