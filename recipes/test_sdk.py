# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that runs SDK package unit tests.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_relevance',
    'cros_sdk',
    'failures',
]

from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult


def RunSteps(api):
  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot():
    dep_graph = api.build_menu.get_dep_graph([])

    # Exit early if there are no changes to the SDK.
    relevant = False
    if api.build_menu.gerrit_changes:
      relevant = api.cros_sdk.sdk_is_dirty
    else:
      relevant = api.cros_relevance.postsubmit_relevance_check(
          api.build_menu.gitiles_commit, dep_graph.sdk)
    if not relevant:
      return RawResult(status=common.SUCCESS,
                       summary_markdown='build was pointless.')

    with api.step.nest('run SDK package unit tests') as step:
      request = BuildTargetUnitTestRequest(
          build_target=BuildTarget(name=None), chroot=api.cros_sdk.chroot,
          package_blocklist=[], packages=[],
          result_path=str(api.path.mkdtemp()),
          flags=BuildTargetUnitTestRequest.Flags(
              code_coverage=False, empty_sysroot=False,
              testable_packages_optional=False, filter_only_cros_workon=False))
      response = api.cros_build_api.TestService.BuildTargetUnitTest(
          request, response_lambda=api.cros_build_api.failed_pkg_data_names,
          pkg_logs_lambda=api.cros_build_api.failed_pkg_logs)
      pkgs = api.cros_build_api.failed_pkg_logs(request, response,
                                                api.file.read_raw)
      api.failures.set_failed_packages(step, pkgs)

    # SDK has been modified, so ensure it is not reused.
    api.cros_sdk.mark_sdk_as_dirty()


def GenTests(api):

  yield api.test(
      'not-relevant-cq',
      api.buildbucket.try_build(builder='host-packages-cq'),
      api.post_process(post_process.DoesNotRun, 'run SDK package unit tests'),
  )

  yield api.test(
      'not-relevant-postsubmit',
      api.buildbucket.ci_build(builder='host-packages-cq'),
      api.post_process(post_process.DoesNotRun, 'run SDK package unit tests'),
  )

  yield api.test(
      'relevant-cq',
      api.buildbucket.try_build(builder='host-packages-cq'),
      api.build_menu.depgraph_relevance_return(
          'validate SDK reuse.depgraph relevance check', pointless=False),
      api.post_process(post_process.MustRun, 'run SDK package unit tests'),
  )

  yield api.test(
      'relevant-postsubmit',
      api.buildbucket.ci_build(builder='host-packages-cq'),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_process(post_process.MustRun, 'run SDK package unit tests'),
  )

  yield api.test(
      'builder-no-longer-exists',
      api.buildbucket.ci_build(builder='deleted-builder'),
      api.post_process(post_process.DoesNotRun, 'run SDK package unit tests'))
