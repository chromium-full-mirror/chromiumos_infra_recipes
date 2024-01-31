# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Release recipes by running the release.sh script in infra/recipes."""

from typing import Dict, Iterable
import datetime
from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.recipes_autoreleaser import RecipesAutoreleaserProperties, ReleaseResult
from PB.recipe_engine import result as result_pb2
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


PROPERTIES = RecipesAutoreleaserProperties


@exponential_retry(3, datetime.timedelta(minutes=1))
def _clone_recipes_repo(api: recipe_api.RecipeApi):
  api.git.clone('https://chromium.googlesource.com/chromiumos/infra/recipes',
                verbose=True, progress=True)

# A map from return codes from the release.sh script to results to return from
# the recipe. Some notes:
#
# - See recipes_release/common.py for the return codes from the release.sh
# script.
# - If release.sh returns one of these codes the recipe will immediately return
# the RawResult.
# - If release.sh returns 0, the recipe will continue with later steps such as
# setting output properties, and return success (assuming none of the later
# steps fail).
# - If release.sh returns a non-zero code that is not in this dict, the step
# will immediately fail the recipe with an InfraFailure.
_ERROR_HANDLERS: Dict[int, result_pb2.RawResult] = {
    11:
        result_pb2.RawResult(
            summary_markdown='No pending changes to release',
            status=common_pb2.SUCCESS,
        ),
    12:
        result_pb2.RawResult(
            summary_markdown='Failures in staging builders blocking release',
            status=common_pb2.FAILURE,
        ),
    21:
        result_pb2.RawResult(
            # TODO(b/302345208): Make the return codes from the release script
            # differentiate not covered vs. blocked by staging failures more
            # clearly.
            summary_markdown='No releasable changes found. This likely is because staging failures are making changes non-releasable.',
            status=common_pb2.FAILURE,
        )
}


# TODO(b/287276108): Improve summary markdown formatting.
def _build_summary_markdown(released_commits: Iterable[ReleaseResult.GitCommit],
                            dry_run: bool):
  commit_lines = []
  for commit in released_commits:
    commit_lines.append(
        f'- {commit.hash[:9]} [{commit.author}] {commit.subject}')

  commit_string = '\n'.join(commit_lines)
  return f'''
{'[DRY RUN]' if dry_run else ''}Released commits:

{commit_string}
'''


def RunSteps(api: recipe_api.RecipeApi,
             properties: RecipesAutoreleaserProperties) -> result_pb2.RawResult:
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

      # Only accept return codes that are 0 or in _ERROR_HANDLERS. All other
      # codes will raise an InfraFailure. Then it is safe to index into
      # _ERROR_HANDLERS below (at that point we know the return code is not 0).
      step_data = api.step(
          'run release.sh',
          args,
          ok_ret=[0] + list(_ERROR_HANDLERS.keys()),
      )
      if step_data.retcode:
        return _ERROR_HANDLERS[step_data.retcode]

      result = ReleaseResult()
      json_format.Parse(
          api.file.read_text('read result jsonproto', result_jsonpb),
          result,
      )
      api.easy.set_properties_step(
          'set output properties',
          subject=result.announcement_email.subject,
          body=result.announcement_email.body,
          released_commits=[
              json_format.MessageToDict(c) for c in result.released_commits
          ],
      )

      return result_pb2.RawResult(
          summary_markdown=_build_summary_markdown(result.released_commits,
                                                   dry_run=not properties.push),
          status=common_pb2.SUCCESS,
      )


def GenTests(api):

  def result_step_data(bundle, dry_run):
    result_text = json_format.MessageToJson(
        ReleaseResult(
            announcement_email=ReleaseResult.AnnouncementEmail(
                subject=f'We released {bundle}',
                body='Released commits 1, 2, and 3',
            ), released_commits=[
                ReleaseResult.GitCommit(
                    hash='123',
                    author='user1',
                    subject='Commit 1',
                ),
                ReleaseResult.GitCommit(
                    hash='456',
                    author='user2',
                    subject='Commit 2',
                ),
            ]),
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
      api.post_process(post_process.PropertyEquals, 'released_commits', [{
          'author': 'user1',
          'hash': '123',
          'subject': 'Commit 1'
      }, {
          'author': 'user2',
          'hash': '456',
          'subject': 'Commit 2'
      }]),
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
      'handled return code',
      api.properties(
          bundle='infra',
          push=True,
      ),
      api.step_data("release bundle 'infra'.run release.sh", retcode=21),
      api.expect_status('FAILURE'),
      api.post_process(
          post_process.SummaryMarkdown,
          'No releasable changes found. This likely is because staging failures are making changes non-releasable.'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'unhandled return code',
      api.properties(
          bundle='infra',
          push=True,
      ),
      api.step_data("release bundle 'infra'.run release.sh", retcode=99),
      api.expect_status('INFRA_FAILURE'),
      api.post_process(
          post_process.SummaryMarkdown,
          'Infra Failure: Step("release bundle \'infra\'.run release.sh") (retcode: 99)'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no bundles',
      api.properties(bundles=[]),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
