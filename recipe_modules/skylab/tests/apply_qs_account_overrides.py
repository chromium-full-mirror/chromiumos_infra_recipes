# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'git_footers',
    'skylab',
]



def RunSteps(api):
  api.skylab.apply_qs_account_overrides(
      api.buildbucket.build.input.gerrit_changes)
  api.assertions.assertEqual(api.skylab._qs_account,
                             api.properties.get('expected_qs_account', 'pcq'))


def GenTests(api):

  yield api.test(
      'quota-scheduler-override-p0-cq-unmanaged',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p0_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.properties(expected_qs_account='p0_cq_unmanaged'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'quota-scheduler-override-p1-cq-unmanaged',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p1_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.properties(expected_qs_account='p1_cq_unmanaged'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'quota-scheduler-override-p2-cq-unmanaged',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p2_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.properties(expected_qs_account='p2_cq_unmanaged'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'quota-scheduler-override-p3-cq-unmanaged',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p3_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.properties(expected_qs_account='p3_cq_unmanaged'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'quota-scheduler-override-p4-cq-unmanaged-no-override',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p4_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'quota-scheduler-override-too-short-bug-id',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p3_cq_unmanaged b/12345678'],
                                            'apply qs account overrides'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multi-footer-uses-highest-prio',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers([
          'p3_cq_unmanaged b/1234567893', 'p0_cq_unmanaged b/1234567890',
          'an incorrect value', 'p2_cq_unmanaged b/1234567892',
          'p1_cq_unmanaged b/1234567891'
      ], 'apply qs account overrides'),
      api.properties(expected_qs_account='p0_cq_unmanaged'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'quota-scheduler-override-cq-unmanaged-no-bug-id',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['p0_cq_unmanaged'],
                                            'apply qs account overrides'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-account',
      api.buildbucket.try_build('cq-orchestrator'),
      api.git_footers.simulated_get_footers(['b/123456789'],
                                            'apply qs account overrides'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'pupr',
      api.buildbucket.try_build(
          'cq-orchestrator', tags=api.cros_tags.tags(
              **{'cq_cl_tag': 'pupr:chromeos-base/lacros-ash-atomic'})),
      api.properties(expected_qs_account='pupr'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'prefer-footer-value-over-pupr',
      api.buildbucket.try_build(
          'cq-orchestrator', tags=api.cros_tags.tags(
              **{'cq_cl_tag': 'pupr:chromeos-base/lacros-ash-atomic'})),
      api.git_footers.simulated_get_footers(['p3_cq_unmanaged b/123456789'],
                                            'apply qs account overrides'),
      api.properties(expected_qs_account='p3_cq_unmanaged'),
      api.post_process(post_process.DropExpectation),
  )
