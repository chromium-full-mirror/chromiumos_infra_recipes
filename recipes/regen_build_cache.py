# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Chrome OS Build Metadata Cache Regnerator."""
from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.binhost import RegenBuildCacheRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'failures',
    'git',
    'git_txn',
    'repo',
    'util',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):

  def _add_and_commit():
    api.git.add(['.'])
    api.git.commit('Update Metadata Cache')

  step_failures = []

  with api.workspace_util.setup_workspace(
      default_main=True), api.cros_sdk.cleanup_context():

    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()
    api.cros_sdk.create_chroot(version=None, timeout_sec=None)
    api.cros_sdk.update_chroot(None, None, timeout_sec=None)

    with api.step.nest('update metadata'), api.context(
        cwd=api.cros_source.workspace_path):
      overlays = api.cros_build_api.BinhostService.RegenBuildCache(
          RegenBuildCacheRequest(overlay_type=OVERLAYTYPE_BOTH,
                                 chroot=api.cros_sdk.chroot)).modified_overlays
      # We'll have a list of updated overlays, but some might be in the same git
      # project, so we have to dedupe as we go.
      if overlays:
        overlay_dirs = [overlay.path for overlay in overlays]
        with api.step.nest('commit and push metadata'):
          projects = api.repo.project_infos(projects=overlay_dirs)
          for project in sorted(set(projects)):
            # Don't abort early if updating one project fails -- we still want
            # to update all the others.
            with api.context(
                cwd=api.cros_source.workspace_path.join(project.path)):
              try:
                api.git_txn.update_ref(project.remote, _add_and_commit,
                                       ref=project.branch, automerge=True)
              except StepFailure as e:
                step_failures.append(e)

  # Return RawResult directly to set the markdown (only with luciexe).
  return result_pb2.RawResult(
      status=common_pb2.FAILURE if step_failures else common_pb2.SUCCESS,
      summary_markdown=api.failures.format_step_failures(
          step_failures=step_failures))


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
