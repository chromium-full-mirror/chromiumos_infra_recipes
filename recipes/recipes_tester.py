# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests a recipe CL by running ChromeOS builders."""

import contextlib

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/led',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'depot_tools/gclient',
    'gerrit',
    'git',
    'test_manager',
]

# Builders to run. Should be in the format led expects:
# "bucket_name:builder_name". Only builders in the staging bucket should be
# included.
BUILDERS = ['luci.chromeos.staging:staging-Annealing']

# URL for the ChromeOS CI recipes repo.
RECIPE_REPO_URL = 'https://chromium.googlesource.com/chromiumos/infra/recipes'


@contextlib.contextmanager
def _checkout_recipes_repo(api):
  """Yields a context where the cwd is the root of the recipes repo.

  Args:
    * api (object): See RunSteps documentation.
  """
  # Just use a temporary dir for the checkout, as it is small. Caching is
  # probably not worth the complexity (because changes are patched in).
  recipes_workdir = api.path['cleanup'].join('recipes')

  with api.step.nest('checkout recipes repo'):
    api.file.ensure_directory('ensure recipes workdir', recipes_workdir)
    with api.context(cwd=recipes_workdir):
      cfg = api.gclient.make_config()
      soln = cfg.solutions.add()
      soln.name = 'src'
      soln.url = RECIPE_REPO_URL

      api.gclient.checkout(gclient_config=cfg)

  # Yield a context that isn't in the checkout step, but is in the checkout dir.
  with api.context(cwd=recipes_workdir.join('src')):
    yield


def _apply_gerrit_changes(api):
  """Cherry-picks the gerrit changes for the build into the cwd.

  Args:
    * api (object): See RunSteps documentation.
  """
  with api.step.nest('apply gerrit changes'):
    patch_sets = api.gerrit.fetch_patch_sets(
        api.buildbucket.build.input.gerrit_changes)

    for patch_set in patch_sets:
      commit_id = api.git.fetch_ref(patch_set.git_fetch_url,
                                    patch_set.git_fetch_ref)
      api.git.cherry_pick(commit_id)


def _launch_builders(api):
  """Launch builders with recipe changes patched in.

  Args:
    * api (object): See RunSteps documentation.
  Returns:
    A list of dicts. Each should contain a 'swarming' key, which is a dict
    containing 'host_name' and 'task_id' keys. I.e. results can be called like
    "results[0]['swarming']['host_name']".
  """
  with api.step.nest('launch builders'):
    results = []

    for builder in BUILDERS:
      results.append(
          api.led('get-builder',
                  builder).then('edit-recipe-bundle').then('launch').result)

    return results


def _collect_results(api, led_results):
  """Collect results from swarming, blocking if necessary.

  Args:
    * api (object): See RunSteps documentation.
    * led_results (list[dict]): A list of results from 'led launch'. Each must
      contain a 'swarming' key, which is a dict containing 'host_name' and
      'task_id' keys. I.e. results can be called like
      "results[0]['swarming']['host_name']".

  Returns:
    A list of swarming TaskResult.
  """
  with api.step.nest('collect results'):
    host_names = set(result['swarming']['host_name'] for result in led_results)

    # All builders should be in the staging bucket, and run on the same
    # swarming server.
    assert len(host_names) == 1, (
        'There should be exactly 1 swarming host name.'
        ' Actual host names: {}').format(host_names)

    with api.swarming.with_server(list(host_names)[0]):
      return api.swarming.collect(
          'collect swarming tasks',
          [result['swarming']['task_id'] for result in led_results])


def RunSteps(api):
  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('gerrit_changes required as input.')

  with _checkout_recipes_repo(api):
    _apply_gerrit_changes(api)
    led_results = _launch_builders(api)

  swarming_results = _collect_results(api, led_results)
  api.test_manager.verify_tests(swarming_results)


def GenTests(api):
  yield (api.test('basic') +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester') +  #
         api.step_data(
             'launch builders.led launch', stdout=api.json.output({
                 'swarming': {
                     'host_name': 'chromium-swarm.appspot.com',
                     'task_id': 'deadbeeeeef',
                 }
             })))

  yield (api.test('no gerrit changes') +  #
         api.expect_exception('ValueError'))
