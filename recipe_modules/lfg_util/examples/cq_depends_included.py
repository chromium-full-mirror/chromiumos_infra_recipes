# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Testing whether cq-depended CLs are being tested in the run."""

from recipe_engine import post_process
from PB.recipe_modules.chromeos.lfg_util.examples.test import \
  CQDependsIncludedProperties
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'git_footers',
    'lfg_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CQDependsIncludedProperties


def RunSteps(api, properties):
  host = 'chromium-review.googlesource.com'
  project = 'kernel'
  changes = [
      GerritChange(change=c, host=host, project=project)
      for c in properties.change_ids
  ]
  result = api.lfg_util.cq_depends_included(gerrit_changes=changes)
  api.assertions.assertEqual(result, properties.expected_result)


def GenTests(api):
  yield api.test(
      'no-cq-depend',
      api.properties(expected_result=True, change_ids=[123, 456]),
      api.git_footers.simulated_get_footers(
          [], parent_step_name='check if all Cq-Depend CLs are included'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'included',
      api.properties(expected_result=True, change_ids=[123, 456]),
      api.git_footers.simulated_get_footers(
          ['chromium:456'],
          parent_step_name='check if all Cq-Depend CLs are included'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'included-numeric',
      api.properties(expected_result=True, change_ids=[123, 456]),
      api.git_footers.simulated_get_footers(
          ['456'], parent_step_name='check if all Cq-Depend CLs are included'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-included',
      api.properties(expected_result=False, change_ids=[123, 456]),
      api.git_footers.simulated_get_footers(
          ['chromium:456, chrome-internal:321'],
          parent_step_name='check if all Cq-Depend CLs are included'),
      api.post_process(post_process.DropExpectation))
