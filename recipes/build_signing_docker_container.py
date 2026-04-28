# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build signing docker container for testing."""

from typing import Generator
from recipe_engine import post_process

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/step',
    'build_menu',
    'cros_source',
    'src_state',
]


def RunSteps(api: RecipeApi) -> None:
  with api.cros_source.checkout_overlays_context():
    api.cros_source.configure_builder(
        api.buildbucket.gitiles_commit,
        api.buildbucket.build.input.gerrit_changes)
    with api.build_menu.setup_workspace():
      api.cros_source.ensure_synced_cache()

      api.step('gcloud auth configure-docker',
               ['gcloud', 'auth', 'configure-docker', 'us-docker.pkg.dev'])

      with api.context(api.src_state.workspace_path / 'crostools' /
                       'signing_docker'):
        api.step('docker build',
                 ['./setup.py', '-r', '-d', '-t signing:latest'])


def GenTests(api: RecipeTestApi) -> Generator:
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )
