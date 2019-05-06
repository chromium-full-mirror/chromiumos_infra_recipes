# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests chromite.

Though this recipe appears to be almost a subset of build_target, it lives
on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'gerrit',
]

from PB.chromite.api.sdk import CreateRequest as SdkCreateRequest
from PB.chromite.api.test import ChromiteUnitTestRequest


def RunSteps(api):
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

      gerrit_changes = api.buildbucket.build.input.gerrit_changes
      if gerrit_changes:
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      with api.step.nest('init sdk') as step:
        response = api.cros_build_api.SdkService.Create(
            SdkCreateRequest(
                flags=SdkCreateRequest.Flags(no_replace=True, bootstrap=False,
                                             no_use_image=True),
                chroot=api.cros_sdk.chroot))
        step.presentation.logs['sdk version'] = [str(response.version.version)]

      with api.step.nest('run chromite unit tests'):
        api.cros_build_api.TestService.ChromiteUnitTest(
            ChromiteUnitTestRequest(chroot=api.cros_sdk.chroot))


def GenTests(api):
  yield api.test('no-gerrit-changes')

  yield api.test('one-gerrit-change') + api.buildbucket.try_build(
      project='chromeos', bucket='cq', builder='chromite-cq')
