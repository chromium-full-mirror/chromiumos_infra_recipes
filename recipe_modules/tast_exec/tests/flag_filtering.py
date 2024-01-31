# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.testplans.generate_test_plan import BuildPayload

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'tast_exec',
]



def RunSteps(api):
  test_artifacts = api.path.mkdtemp(prefix='temp')
  tast_inputs = api.tast_exec.TastInputs(
      ['!informational'], test_artifacts,
      BuildPayload(
          artifacts_gs_bucket='artifacts-bucket',
          artifacts_gs_path='artifacts-path',
      ), shard_args=['-shardmethod=hash'])

  # pylint: disable=protected-access
  tast_inputs = api.tast_exec._amend_tast_inputs(tast_inputs)

  if api.properties.get('expect_shardmethod'):
    api.assertions.assertIn('-shardmethod=hash', tast_inputs.shard_args)
  else:
    api.assertions.assertNotIn('-shardmethod=hash', tast_inputs.shard_args)

  if api.properties.get('expect_systemservicestimeout'):
    api.assertions.assertIn('-systemservicestimeout=600', tast_inputs.run_args)
  else:
    api.assertions.assertNotIn('-systemservicestimeout=600',
                               tast_inputs.run_args)


def GenTests(api):

  yield api.test(
      'basic',
      api.properties(expect_systemservicestimeout=True,
                     expect_shardmethod=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'neither-implemented',
      api.step_data('tast help run', stdout=api.raw_io.output('-randomflag')),
      api.properties(expect_systemservicestimeout=False,
                     expect_shardmethod=False),
      api.post_process(post_process.DropExpectation),
  )
