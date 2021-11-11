# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Orchestrator for Android uprev builders.

The orchestrator determines the latest Android version for the specified Android
package, then passes the info down into child builders running the
build_android_uprev recipe.

Once all builds and tests passed, it submits a CL to update the Android LKGB
file. The change will in turn trigger the PUpr generator to publish an actual
Android uprev.
"""

DEPS = [
    'recipe_engine/properties',
    'android',
    'build_menu',
    'orch_menu',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.recipes.chromeos.android_uprev import AndroidUprevProperties

PROPERTIES = AndroidUprevProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api, properties)
    return api.orch_menu.create_recipe_result()


def DoRunSteps(api, properties):
  android_package = properties.android_package
  if not android_package:
    raise StepFailure('android_package not set')

  android_version = (
      properties.android_version or
      api.android.get_latest_build(android_package))

  extra_child_props = {
      'android_package': android_package,
      'android_version': android_version,
  }

  # Run the child builders.
  builds_status = api.orch_menu.plan_and_run_children(
      extra_child_props=extra_child_props,
  )

  # Aggregate any metadata produced by the child builds into our own GS bucket
  api.orch_menu.aggregate_metadata(builds_status.completed_builds)

  # Run any HW tests.
  builds_status = api.orch_menu.plan_and_run_tests()

  if builds_status.fatal_failures:
    # Do not proceed if any critical builds/tests failed.
    # api.orch_menu.create_recipe_result() will return an error for us.
    return

  # TODO(b/210065671): submit LKGB update

  # Launch any specified follow on orchestrator.
  api.orch_menu.run_follow_on_orchestrator()


def GenTests(api):

  data = api.orch_menu.standard_test_data()

  yield api.orch_menu.test('basic', data.ctp_normal,
                           api.properties(android_package='android-package'),
                           api.post_check(post_process.StatusSuccess),
                           with_history=True, collect_builds=data.builds)

  yield api.orch_menu.test('android-package-not-set',
                           api.post_check(post_process.StatusFailure))

  yield api.orch_menu.test('build-failure', data.ctp_normal,
                           api.properties(android_package='android-package'),
                           api.post_check(post_process.StatusFailure),
                           with_history=True, collect_builds=data.crit_fail)

  yield api.orch_menu.test('test-failure', data.ctp_failure,
                           api.properties(android_package='android-package'),
                           api.post_check(post_process.StatusFailure),
                           with_history=True, collect_builds=data.builds)
