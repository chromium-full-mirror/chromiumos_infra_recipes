# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating CoverageRules for a given set of GerritChanges.

This Recipe is a wrapper around functions in the cros_test_plan_v2 module. Since
some calls (e.g. generate_coverage_rules) require a source checkout and SDK to
be present, this Recipe is intended for use in contexts when these are not
present, e.g. calls from the orchestrator.

If a Recipe already has a checkout and SDK present, it should call the
cros_test_plan_v2 functions directly.
"""

from google.protobuf import json_format

DEPS = [
    'recipe_engine/buildbucket',
    'cros_source',
    'cros_test_plan_v2',
    'easy',
    'src_state',
]


def RunSteps(api):
  gerrit_changes = api.buildbucket.build.input.gerrit_changes
  if not gerrit_changes:
    raise ValueError('At least one GerritChange must be passed.')

  relevant_plans = api.cros_test_plan_v2.relevant_plans(
      api.buildbucket.build.input.gerrit_changes)

  api.cros_source.configure_builder()
  with api.cros_source.checkout_overlays_context():
    # TODO(b/182898188): Add property to allow checking out branches.
    api.cros_source.checkout_tip_of_tree()
    coverage_rules = api.cros_test_plan_v2.generate_coverage_rules(
        relevant_plans)
    api.easy.set_properties_step(coverage_rules=','.join(
        json_format.MessageToJson(cr) for cr in coverage_rules))


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.try_build(),
  )

  yield api.test(
      'no gerrit changes',
      api.expect_exception('ValueError'),
  )
