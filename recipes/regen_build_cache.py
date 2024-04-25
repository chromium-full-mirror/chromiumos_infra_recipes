# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the CrOS Build Metadata Cache Regnerator.

If we fail to generate metadata for one repo project, don't fail immediately.
Instead, try to process the other projects, and THEN fail.
"""

from typing import List

from google.protobuf import json_format

from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.binhost import RegenBuildCacheRequest
from PB.chromite.api.binhost import RegenBuildCacheResponse
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'deferrals',
    'git',
    'git_txn',
    'repo',
    'workspace_util',
]



def RunSteps(api: RecipeApi):

  def _add_and_commit():
    api.git.add(['.'])
    commit_lines = ('Update Metadata Cache', '',
                    f'Cr-Build-Url: {api.buildbucket.build_url()}')
    api.git.commit('\n'.join(commit_lines))

  def _commit_and_push_metadata(
      overlays: List[RegenBuildCacheResponse.Overlay]) -> None:
    """Commit and push the metadata for each of these repo projects.

    Local changes to the projects should already be made.
    If updating one project fails, continue updating the other projects, and
    then raise the exceptions at the end.

    Some of these overlays might be in the same git project, so we have to
    dedupe as we go.

    Args:
      overlays: A list of overlays that already contain local changes, as
        returned by BinhostService/RegenBuildCache.
    """
    with api.step.nest('commit and push metadata') as presentation:
      if not overlays:
        presentation.step_text = 'no modified overlays to push'
        return

      overlay_dirs = [overlay.path for overlay in overlays]
      projects = api.repo.project_infos(projects=overlay_dirs)
      with api.deferrals.raise_exceptions_at_end():
        for project in sorted(set(projects)):
          cwd = api.cros_source.workspace_path / project.path
          with api.context(cwd=cwd):
            with api.deferrals.defer_exceptions():
              api.git_txn.update_ref(project.remote, _add_and_commit,
                                     step_name=f'update ref: {project.name}',
                                     ref=project.branch, automerge=True)

  with api.workspace_util.setup_workspace(
      default_main=True), api.cros_sdk.cleanup_context():

    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()
    api.cros_sdk.create_chroot(timeout_sec=None)
    # NB: We don't bother updating the SDK as the latest prebuilt suffices. The
    # only thing we're doing is updating metadata caches, and those are a pretty
    # stable format across portage releases -- they haven't changed in many many
    # years.

    with api.step.nest('update metadata'), api.context(
        cwd=api.cros_source.workspace_path):
      request = RegenBuildCacheRequest(overlay_type=OVERLAYTYPE_BOTH,
                                       chroot=api.cros_sdk.chroot)
      response = api.cros_build_api.BinhostService.RegenBuildCache(request)
      _commit_and_push_metadata(response.modified_overlays)


def GenTests(api: RecipeTestApi):
  """Generate tests for this recipe."""
  # These are the overlays in the BAPI test response for RegenBuildCache.
  # See recipe_modules/cros_build_api/test_api.py.
  FIRST_OVERLAY = '[CLEANUP]/chromiumos_workspace/src/overlay'
  SECOND_OVERLAY = '[CLEANUP]/chromiumos_workspace/src/partner-overlay'

  def mock_git_push_response(overlay: str) -> TestData:
    """Create test data for `git push`. Otherwise it will fail."""
    step_name = '.'.join(
        ('update metadata', 'commit and push metadata',
         f'update ref: {overlay}', 'gerrit transaction', 'git push'))
    return api.step_data(
        step_name, stderr=api.raw_io.output_text(
            'remote:  https://chromium-review.googlesource.com'
            '/c/chromiumos/infra/recipes/+/123 git_txn: test'))

  def mock_update_ref_failure(overlay: str) -> TestData:
    """Cause the update CL for `overlay` to fail to land."""
    step_name = '.'.join(('update metadata', 'commit and push metadata',
                          f'update ref: {overlay}', 'gerrit transaction',
                          'submit CL 123', 'git_cl land'))
    step_data = api.step_data(step_name, retcode=1)
    for retry in range(2, 5):
      step_data += api.step_data(f'{step_name} ({retry})', retcode=1)
    return step_data

  yield api.test(
      'basic',
      mock_git_push_response(FIRST_OVERLAY),
      mock_git_push_response(SECOND_OVERLAY),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  # Even though the first overlay fails, the second overlay should still run.
  # Then the build should present as a failure.
  yield api.test(
      'first-overlay-fails',
      mock_git_push_response(FIRST_OVERLAY),
      mock_git_push_response(SECOND_OVERLAY),
      mock_update_ref_failure(FIRST_OVERLAY),
      api.post_check(
          post_process.StepFailure,
          'update metadata.commit and push metadata.update ref: %s' %
          FIRST_OVERLAY),
      api.post_check(
          post_process.StepSuccess,
          'update metadata.commit and push metadata.update ref: %s' %
          SECOND_OVERLAY),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'no-modified-overlays',
      api.cros_build_api.set_api_return(
          'update metadata', 'BinhostService/RegenBuildCache',
          json_format.MessageToJson(
              RegenBuildCacheResponse(modified_overlays=[]))),
      api.post_check(post_process.StepTextEquals,
                     'update metadata.commit and push metadata',
                     'no modified overlays to push'),
      api.post_check(
          post_process.DoesNotRunRE,
          r'update metadata\.commit and push metadata\.update ref.*'),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )
