# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_relevance.examples.forced_relevance import ForcedRelevanceTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
    'git_footers',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = ForcedRelevanceTest


def RunSteps(api, properties):
  api.assertions.assertEqual(
      api.cros_relevance.check_force_relevance_footer(properties.gerrit_changes,
                                                      properties.configs),
      properties.expected_forced_targets)


def GenTests(api):
  targets = [
      'example-target-1-cq', 'example-target-2-cq', 'example-target-3-something'
  ]
  configs = [BuilderConfig(id=BuilderConfig.Id(name=name)) for name in targets]
  gerrit_changes = [
      bbcommon_pb2.GerritChange(change=123, host='cr.googlesource.com'),
      bbcommon_pb2.GerritChange(change=456, host='cr.googlesource.com'),
  ]

  yield api.test(
      'nothing-forced-relevant',
      api.properties(
          ForcedRelevanceTest(gerrit_changes=gerrit_changes, configs=configs,
                              expected_forced_targets=[])),
      api.git_footers.simulated_get_footers(
          [], parent_step_name='check force relevance'))

  yield api.test(
      'all-forced-relevant',
      api.properties(
          ForcedRelevanceTest(gerrit_changes=gerrit_changes, configs=configs,
                              expected_forced_targets=targets)),
      api.git_footers.simulated_get_footers(
          ['all'], parent_step_name='check force relevance'))

  yield api.test(
      'some-forced-relevant',
      api.properties(
          ForcedRelevanceTest(gerrit_changes=gerrit_changes, configs=configs,
                              expected_forced_targets=targets[1:])),
      api.git_footers.simulated_get_footers(
          ['example-target-2-cq,example-target-3-something'],
          parent_step_name='check force relevance'))
