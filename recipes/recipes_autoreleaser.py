# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release recipes by running the release.sh script in infra/recipes."""

import datetime
from google.protobuf import json_format

from PB.recipes.chromeos.recipes_autoreleaser import RecipesAutoreleaserProperties, ReleaseResult
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

from recipe_engine import recipe_api
from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
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
  if not properties.bundle:
    raise ValueError('bundle must be set')

  # We only need to clone the recipes repo, so don't do a full ChromeOS
  # checkout. Clone into the workspace path so it'll get cleaned up after the
  # builder runs.
  with api.context(
      cwd=api.path.mkdtemp(prefix='autorelease'), infra_steps=True):
    _clone_recipes_repo(api)
    release_script = api.context.cwd.join('release.sh')

    step_name = f"release bundle '{properties.bundle}'"
    args = [
        release_script,
        '--max-releasable',
        '--verbose',
        '--show-instances',
        '--bundle',
        properties.bundle,
        '--yes',
    ]

    if not properties.push:
      args.append('--dry-run')
      step_name += ' (dry-run)'

    with api.step.nest(step_name):
      result_jsonpb = api.path.mkstemp(prefix='result_jsonpb')
      args.extend(['--result-out', result_jsonpb])

      # TODO(b/287276108): Handle different return codes from the release script.
      api.step(
          'run release.sh',
          args,
      )

      result = ReleaseResult()
      json_format.Parse(
          api.file.read_text('read result jsonproto', result_jsonpb),
          result,
      )
      api.easy.set_properties_step(
          'set email properties',
          subject=result.announcement_email.subject,
          body=result.announcement_email.body,
      )


def GenTests(api):

  def result_step_data(bundle, dry_run):
    result_text = json_format.MessageToJson(
        ReleaseResult(
            announcement_email=ReleaseResult.AnnouncementEmail(
                subject=f'We released {bundle}',
                body='Released commits 1, 2, and 3',
            ),
        ),
    )

    step_name = f"release bundle '{bundle}'{' (dry-run)' if dry_run else ''}.read result jsonproto"
    return api.step_data(step_name, api.file.read_text(result_text))

  yield api.test(
      'basic',
      api.properties(
          bundle='infra',
          push=True,
      ),
      result_step_data(bundle='infra', dry_run=False),
      api.post_process(post_process.PropertyEquals, 'subject',
                       'We released infra'),
      api.post_process(post_process.PropertyEquals, 'body',
                       'Released commits 1, 2, and 3'),
  )

  yield api.test(
      'dry run',
      api.properties(
          bundle='infra',
          push=False,
      ),
      result_step_data(bundle='infra', dry_run=True),
  )

  yield api.test(
      'no bundles',
      api.properties(bundles=[]),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
