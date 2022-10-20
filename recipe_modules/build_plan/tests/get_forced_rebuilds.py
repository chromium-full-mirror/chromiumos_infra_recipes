# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_plan',
    'git_footers',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {'expected_builders': Property(default=[])}


def RunSteps(api, expected_builders):
  gerrit_change_1 = common_pb2.GerritChange(
      host='chromium-review.googlesource.com', change=1234)
  gerrit_change_2 = common_pb2.GerritChange(
      host='chromium-review.googlesource.com', change=5678)
  result = api.build_plan.get_forced_rebuilds(
      [gerrit_change_1, gerrit_change_2])
  api.assertions.assertEqual(result, set(expected_builders))


def GenTests(api):

  yield api.test(
      'No-non-reusable-builders',
      api.git_footers.simulated_get_footers(
          [], parent_step_name='check disallow recycled builds'),
      api.git_footers.simulated_get_footers(
          [], parent_step_name='check disallow recycled builds', step_number=2))

  yield api.test(
      'Non-reusable-builders',
      api.properties(expected_builders={'hersheys', 'snickers', 'milkyway'}),
      api.git_footers.simulated_get_footers(
          ['hersheys, snickers'],
          parent_step_name='check disallow recycled builds'),
      api.git_footers.simulated_get_footers(
          ['snickers, milkyway'],
          parent_step_name='check disallow recycled builds', step_number=2))

  yield api.test(
      'No-reusable-builders', api.properties(expected_builders={'all'}),
      api.git_footers.simulated_get_footers(
          ['twix,milkyway'], parent_step_name='check disallow recycled builds'),
      api.git_footers.simulated_get_footers(
          ['snickers, all, milkyway'],
          parent_step_name='check disallow recycled builds', step_number=2))
