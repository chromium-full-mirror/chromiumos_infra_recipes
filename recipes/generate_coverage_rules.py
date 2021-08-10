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
    'build_menu',
    'cros_test_plan_v2',
    'easy',
]


def RunSteps(api):
  gerrit_changes = api.buildbucket.build.input.gerrit_changes
  if not gerrit_changes:
    raise ValueError('At least one GerritChange must be passed.')

  relevant_plans = api.cros_test_plan_v2.relevant_plans(gerrit_changes)

  with api.build_menu.configure_builder(missing_ok=True), \
      api.build_menu.setup_workspace_and_chroot():
    coverage_rules = api.cros_test_plan_v2.generate_coverage_rules(
        relevant_plans,
        api.build_menu.chroot,
    )
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
