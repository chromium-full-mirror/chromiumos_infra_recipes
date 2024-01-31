# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.chromiumos.test_disablement import TestDisablement
from PB.chromiumos.test_disablement import TestDisablementCfg

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/assertions',
    'exonerate',
]



def RunSteps(api):
  expected_configs = {'fake.test': ['target']}
  api.assertions.assertDictEqual(expected_configs,
                                 api.exonerate.manual_exoneration_configs)

  # Test that it does not load configs on subsequent calls.
  api.assertions.assertDictEqual(expected_configs,
                                 api.exonerate.manual_exoneration_configs)

  # Test that updating self._exoneration_configs does not change
  # self._manual_exoneration_configs.
  api.exonerate._exoneration_configs = {}  # pylint: disable=protected-access
  api.assertions.assertDictEqual(expected_configs,
                                 api.exonerate.manual_exoneration_configs)


def GenTests(api):
  exoneration_cfg = TestDisablementCfg(disablements=[
      TestDisablement(
          name='fake.test', bug_ids=['123456'], dut_criteria=[
              TestDisablement.FilterCriterion(key='build_target',
                                              values=['target'])
          ])
  ])
  yield api.test(
      'basic',
      api.step_data(
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto',
          api.gitiles.make_encoded_file_from_bytes(
              exoneration_cfg.SerializeToString())),
      api.post_check(
          post_process.MustRun,
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto'),
      api.post_check(
          post_process.DoesNotRun,
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto (2)'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto (3)'
      ),
      api.post_process(post_process.DropExpectation),
  )
