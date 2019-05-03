# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests a recipe CL by running ChromeOS builders."""

import contextlib

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

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
    'failures',
    'gerrit',
    'git',
    'recipe_analyze',
]

# LUCI project to test.
PROJECT = 'chromeos'
# Bucket to test in. Only the staging environment should be used.
BUCKET = 'staging'
# Builders to run.
BUILDERS = ['staging-Annealing']

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


def _get_last_successful_build(api, builder):
  """Find the most recent successful build for 'builder'.

  Args:
    * api (object): See RunSteps documentation.
    * builder (string): The name of the builder to search for.
  Returns:
    A Build proto.
  Raises:
    A StepFailure if no build is found.
  """
  # Note that buildbucket.search returns results ordered newest-to-oldest.
  # TODO(crbug.com/957600): Use the limit param for search once it is available.
  successful_builds = api.buildbucket.search(
      rpc_pb2.BuildPredicate(
          builder={
              'project': PROJECT,
              'bucket': BUCKET,
              'builder': builder
          }, status=common_pb2.SUCCESS, include_experimental=False))

  if not successful_builds:
    raise api.step.StepFailure(
        'No successful builds found for builder {}'.format(builder))

  return successful_builds[0]


def _launch_builders(api):
  """Launch builders with recipe changes patched in.

  Builders are only launched if the files in the patched changes affect the
  builder's recipe, as determined by 'recipes.py analyze'. recipes.py determines
  this by looking at 3 different files: the recipe itself, the modules it
  depends on, and the .gitattributes file in the root of the repo.

  Args:
    * api (object): See RunSteps documentation.
  Returns:
    A list of dicts. Each should contain a 'swarming' key, which is a dict
    containing 'host_name' and 'task_id' keys. I.e. results can be called like
    "results[0]['swarming']['host_name']".
  """
  with api.step.nest('analyze and launch builders') as launch_step:
    results = []

    with api.step.nest('get affected files') as affected_files_step:
      # Changes should be cherry picked at this point. The relevant diffs should
      # be between the original master and HEAD.
      affected_files = api.git.get_diff_files(from_rev='origin/master',
                                              to_rev='HEAD')
      affected_files_step.presentation.logs['affected files'] = affected_files

    for builder in BUILDERS:
      with api.step.nest(
          'analyze and launch {}'.format(builder)) as builder_step:
        # Get an intermediate result from led to extract the builder definition.
        # Then, chain on calls to launch the builder (if it is relevant).
        last_successful_build = _get_last_successful_build(api, builder)
        intermediate_result = api.led('get-build', last_successful_build.id)

        recipe_names = set(
            job_slice['userland']['recipe_name']
            for job_slice in intermediate_result.result['job_slices'])

        # Every builder should run a single recipe across the slices.
        assert len(recipe_names) == 1, (
            'There should be exactly 1 recipe name in the builder definition. '
            'Actual recipe names: {}'.format(recipe_names))

        recipe = recipe_names.pop()
        if api.recipe_analyze.is_recipe_affected(affected_files, recipe):
          results.append(
              intermediate_result.then('edit-recipe-bundle').then('launch')
              .result)
        else:
          builder_step.presentation.step_text = (
              'builder {} (recipe {}) not affected'.format(builder, recipe))

    launch_step.presentation.step_text = 'launched {} / {} builders'.format(
        len(results), len(BUILDERS))

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
  assert led_results
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

  if led_results:
    swarming_results = _collect_results(api, led_results)
    api.failures.verify_tests(swarming_results)


def GenTests(api):

  def launch_step_name(builder, step_name):
    """Get the full name of a step used during the launch of a builder.

    Args:
      * builder (str): The name of the builder.
      * step_name (str): The name of the step (e.g. 'led launch').

    Returns:
      A str
    """
    return 'analyze and launch builders.analyze and launch {}.{}'.format(
        builder, step_name)

  def buildbucket_search_test_data(builder):
    return api.buildbucket.simulated_search_results(
        builds=[build_pb2.Build(id=1, builder={'builder': builder})],
        step_name=launch_step_name(builder, 'buildbucket.search'))

  def led_get_build_test_data(builder, recipe_name):
    """Get step data for a 'led get-build' command.

    Args:
      * builder (str): The name of the builder.
      * recipe_name (str): The name of the recipe to return in the builder
        def.

    Returns:
      A TestData object.
    """
    return api.step_data(
        launch_step_name(builder, 'led get-build'), stdout=api.json.output({
            'job_slices': [{
                'userland': {
                    'recipe_name': recipe_name
                }
            }]
        }))

  def led_get_launch_test_data(builder):
    """Get step data for a 'led launch' command.

    Args:
      * builder (str): The name of the builder.

    Returns:
      A TestData object.
    """
    return api.step_data(
        launch_step_name(builder, 'led launch').format(builder),
        stdout=api.json.output({
            'swarming': {
                'host_name': 'chromium-swarm.appspot.com',
                'task_id': 'deadbeeeeef',
            }
        }))

  def recipe_analyze_test_data(builder, recipes):
    """Get step data for a 'recipes.py analyze' command.

    Args:
      * builder (str): The name of the builder.
      * recipes (list[str]): The recipes to return in the Output proto.

    Returns:
      A TestData object.
    """
    return api.step_data(
        launch_step_name(builder, 'recipe analyze'),
        api.json.output({
            'recipes': recipes
        }))

  yield (api.test('basic') +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester') +  #
         buildbucket_search_test_data('staging-Annealing') +  #
         led_get_build_test_data(builder='staging-Annealing',
                                 recipe_name='annealing') +  #
         recipe_analyze_test_data(builder='staging-Annealing',
                                  recipes=['annealing']) +  #
         led_get_launch_test_data(builder='staging-Annealing'))

  yield (api.test('builder_not_affected') +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester') +  #
         buildbucket_search_test_data('staging-Annealing') +  #
         led_get_build_test_data('staging-Annealing', 'annealing') +  #
         recipe_analyze_test_data('staging-Annealing', ['build_target']))

  yield (api.test('no_successful_builds') +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester'))

  yield (api.test('no_gerrit_changes') +  #
         api.expect_exception('ValueError'))
