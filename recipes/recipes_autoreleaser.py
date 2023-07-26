# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release recipes by running the release.sh script in infra/recipes."""

import datetime

from PB.recipes.chromeos.recipes_autoreleaser import RecipesAutoreleaserProperties
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

from recipe_engine import recipe_api
from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'git',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = RecipesAutoreleaserProperties


@exponential_retry(3, datetime.timedelta(minutes=1))
def _clone_recipes_repo(api: recipe_api.RecipeApi):
  api.git.clone('https://chromium.googlesource.com/chromiumos/infra/recipes',
                verbose=True, progress=True)


def RunSteps(api: recipe_api.RecipeApi,
             properties: RecipesAutoreleaserProperties):
  if not properties.bundles:
    raise ValueError('At least one bundle must be set')

  # We only need to clone the recipes repo, so don't do a full ChromeOS
  # checkout. Clone into the workspace path so it'll get cleaned up after the
  # builder runs.
  with api.context(
      cwd=api.path.mkdtemp(prefix='autorelease'), infra_steps=True):
    _clone_recipes_repo(api)
    release_script = api.context.cwd.join('release.sh')

    for bundle in properties.bundles:
      step_name = f"release bundle '{bundle}'"
      args = [
          release_script,
          '--max-releasable',
          '--verbose',
          '--show-instances',
          '--bundle',
          bundle,
          '--yes',
      ]

      # TODO(b/287276108): Send emails from this recipe notifying the infra
      # team of the status of the release or dry run.
      if not properties.push:
        args.append('--dry-run')
        step_name += ' (dry-run)'

      api.step(
          step_name,
          args,
      )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          bundles=['infra', 'release'],
          push=True,
      ),
  )

  yield api.test(
      'dry run',
      api.properties(
          bundles=['infra'],
          push=False,
      ),
  )

  yield api.test(
      'no bundles',
      api.properties(bundles=[]),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
