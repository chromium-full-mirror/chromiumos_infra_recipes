# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.testplans.generate_test_plan import BuildPayload

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'tast_exec',
]



def RunSteps(api):
  test_artifacts = api.path.mkdtemp(prefix='temp')
  api.tast_exec.download_tast(
      BuildPayload(
          artifacts_gs_bucket='bucket',
          artifacts_gs_path='path',
      ), test_artifacts)


  results_dir = api.path.mkdtemp(prefix='temp')
  api.tast_exec.run_direct(
      'my-dut-name',
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               )), results_dir)
  api.tast_exec.run_direct(
      'my-dut-name',
      api.tast_exec.TastInputs(['example.Pass'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               ), run_args=['-var=myVar=myVal']), results_dir)

def GenTests(api):
  yield api.test('basic', api.buildbucket.ci_build(),
                 api.tast_exec.simulate_test_list_ret('some.test'))

  yield api.test(
      'public',
      api.buildbucket.ci_build(),
      api.tast_exec.simulate_test_list_ret('some.test'),
      api.properties(**{'$chromeos/tast_exec': {
          'public_builder': True
      }}),
  )
