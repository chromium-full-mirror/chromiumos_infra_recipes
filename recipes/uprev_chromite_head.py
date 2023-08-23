# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uprev'ing chromite-HEAD.version file for go/deployable-chromite"""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.uprev_chromite_head import (UprevChromiteHeadProperties
                                                    )
from RECIPE_MODULES.chromeos.gerrit.api import Label
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'gerrit',
    'git',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = UprevChromiteHeadProperties


def RunSteps(api: RecipeApi, properties) -> None:
  # 1. get the chromite remote head commit.
  api.step('git init', ['git', 'init'])
  with api.step.nest('get latest commit') as step:
    commit = api.git.fetch_ref(
        'https://chromium.googlesource.com/chromiumos/chromite/',
        'refs/heads/main')
    step.step_text = f'commit: {commit}'
  # 2. clone the recipes repo in a temp dir.
  checkout = api.path.mkdtemp()
  with api.context(cwd=checkout):
    api.git.clone('https://chromium.googlesource.com/chromiumos/infra/recipes/',
                  depth=1)
    # 3. modify the version file.
    version_file_name = f'{checkout}/infra/config/chromite-HEAD.version'
    api.file.write_text(
        'update chromite-HEAD version file',
        version_file_name,
        commit,
        include_log=True,
    )
    # 3.5. check to make sure there was actually a change.
    if not api.git.diff_check(version_file_name):
      return result_pb2.RawResult(
          summary_markdown='No new commits since last uprev',
          status=common_pb2.SUCCESS,
      )
    # 4. create a cl updating the file.
    api.git.add([version_file_name])
    api.git.commit('update chromite-HEAD version')
    change = api.gerrit.create_change('chromiumos/infra/recipes',
                                      ref=api.git.get_branch_ref('main'),
                                      project_path=checkout)
    labels = {
        Label.BOT_COMMIT: 1,
    }
    api.gerrit.set_change_labels_remote(change, labels)
    if properties.dry_run:
      # 5. in dry_run mode, we abandon the cl.
      api.gerrit.abandon_change(change)
    else:
      # 5. in production mode, we submit the cl.
      api.gerrit.submit_change(change, project_path=checkout, retries=3)
    return result_pb2.RawResult(
        summary_markdown=f'Updated chromite-HEAD pin to {commit}',
        status=common_pb2.SUCCESS,
    )


def GenTests(api: RecipeTestApi) -> None:
  yield api.test(
      'dry-run',
      api.properties(dry_run=True),
      api.git.diff_check(True),
      api.post_check(post_process.StepTextEquals, 'get latest commit',
                     'commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'),
      api.post_check(post_process.MustRun, 'git init'),
      api.post_check(post_process.MustRun, 'git clone'),
      api.post_check(post_process.MustRun, 'update chromite-HEAD version file'),
      api.post_check(post_process.MustRun, 'git add'),
      api.post_check(post_process.MustRun, 'write commit message'),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.MustRun,
                     'create gerrit change for chromiumos/infra/recipes'),
      api.post_check(post_process.MustRun, 'set labels on CL 1'),
      api.post_check(post_process.MustRun, 'abandon CL 1'),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'no-diff',
      api.git.diff_check(False),
      api.post_check(post_process.StepTextEquals, 'get latest commit',
                     'commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'),
      api.post_check(post_process.MustRun, 'git init'),
      api.post_check(post_process.MustRun, 'git clone'),
      api.post_check(post_process.MustRun, 'update chromite-HEAD version file'),
      api.post_check(post_process.DoesNotRun, 'git add'),
      api.post_check(post_process.DoesNotRun, 'write commit message'),
      api.post_check(post_process.DoesNotRun, 'git commit'),
      api.post_check(post_process.DoesNotRun,
                     'create gerrit change for chromiumos/infra/recipes'),
      api.post_check(post_process.DoesNotRun, 'set labels on CL 1'),
      api.post_check(post_process.DoesNotRun, 'submit CL 1'),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'full-run',
      api.git.diff_check(True),
      api.post_check(post_process.StepTextEquals, 'get latest commit',
                     'commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'),
      api.post_check(post_process.MustRun, 'git init'),
      api.post_check(post_process.MustRun, 'git clone'),
      api.post_check(post_process.MustRun, 'update chromite-HEAD version file'),
      api.post_check(post_process.MustRun, 'git add'),
      api.post_check(post_process.MustRun, 'write commit message'),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.MustRun,
                     'create gerrit change for chromiumos/infra/recipes'),
      api.post_check(post_process.MustRun, 'set labels on CL 1'),
      api.post_check(post_process.MustRun, 'submit CL 1'),
      api.post_process(post_process.DropExpectation),
  )
