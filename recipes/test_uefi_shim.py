# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to test the UEFI shim for the reven board."""

import hashlib
from typing import List

from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'gerrit',
    'git',
]


REPO_URL = 'https://chromium.googlesource.com/chromiumos/shim-review'

# List of shim binary file names built by this repo. These files
# should be committed to the repo rather than just being built by the
# repo, as that is required by the external shim-review process.
SHIM_FILE_NAMES = ['shimia32.efi', 'shimx64.efi']


def _calc_sha256_digest(api: RecipeApi, repo_dir: Path, name: str) -> str:
  """Calculate the SHA256 digest for the contents of the file at `name`."""
  # The shim binaries are fairly small (currently less than one MB) so
  # no need to chunk the read.
  path = repo_dir.join(name)
  content = api.file.read_raw('read file ' + name, path, test_data=name)
  return hashlib.sha256(content).hexdigest()


def _get_shim_sha256_digests(api: RecipeApi, repo_dir: Path) -> List[str]:
  """Calculate the SHA256 digests for the shim files as a list of strings."""
  return [_calc_sha256_digest(api, repo_dir, name) for name in SHIM_FILE_NAMES]


def RunSteps(api: RecipeApi):
  repo_dir = api.path.mkdtemp()
  api.git.clone(REPO_URL, target_path=repo_dir, timeout_sec=3 * 60)

  with api.step.nest('apply gerrit changes'), api.context(cwd=repo_dir):
    patch_sets = api.gerrit.fetch_patch_sets(
        x for x in api.buildbucket.build.input.gerrit_changes
        if x.project == 'chromiumos/shim-review')
    for patch_set in patch_sets:
      commit_id = api.git.fetch_ref(patch_set.git_fetch_url,
                                    patch_set.git_fetch_ref)
      api.git.cherry_pick(commit_id)

  # Get the hashes of the current files in the repo.
  with api.step.nest('get current file hashes'), api.context(cwd=repo_dir):
    original_hashes = _get_shim_sha256_digests(api, repo_dir)

  # Do a fresh build shim inside a container (which is required by the
  # shim-review process), then copy the files outside the container.
  env = {'CONTAINER_CMD': 'sudo docker'}
  with api.step.nest('build shim'), api.context(cwd=repo_dir, env=env):
    api.step('make build-no-cache', ['make', 'build-no-cache'])
    api.step('make copy', ['make', 'copy'])

  # Calculate the new file hashes, verify the match the original hashes.
  with api.step.nest('validate hashes'), api.context(cwd=repo_dir):
    new_hashes = _get_shim_sha256_digests(api, repo_dir)

    # Check that the build is reproducible.
    if original_hashes != new_hashes:
      raise StepFailure('shim binaries are stale')


def GenTests(api: RecipeTestApi):
  yield api.test(
      'success', api.buildbucket.try_build(project='chromeos',
                                           git_repo=REPO_URL),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'hash-mismatch',
      api.buildbucket.try_build(project='chromeos', git_repo=REPO_URL),
      api.step_data('get current file hashes.read file shimx64.efi',
                    api.file.read_raw('some arbitrary test data')),
      api.post_check(post_process.ResultReason, 'shim binaries are stale'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
