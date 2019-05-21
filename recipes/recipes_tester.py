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
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'depot_tools/gclient',
    'depot_tools/tryserver',
    'failures',
    'gerrit',
    'git',
    'naming',
    'recipe_analyze',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
    'builders':
        Property(
            kind=list, default=[
                'staging-Annealing', 'staging-chromite-postsubmit',
                'staging-amd64-generic-cq'
            ],
            help=("A list of builders to test the CL on. Only builders in the "
                  "staging environment should be used."))
}

# LUCI project to test.
PROJECT = 'chromeos'
# Bucket to test in. Only the staging environment should be used.
BUCKET = 'staging'

# URL for the ChromeOS CI recipes repo.
RECIPE_REPO_URL = 'https://chromium.googlesource.com/chromiumos/infra/recipes'

# A Git footer than can be included in commit messages to tell the recipe
# tester to skip builders. See the "Recipe Tester Presubmit" in the README for
# more details.
SKIP_BUILDERS_FOOTER = 'Recipes-Tester-Skip-Builder'


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
      # By default, gclient uses a cache (independently of the dir where it is
      # used). This may be causing the checkout to not get the latest commit,
      # leading to cherry-pick conflicts.
      #
      # As a workaround, set the gclient cache dir to be a temporary dir, so it
      # won't cache.
      cfg = api.gclient.make_config(
          CACHE_DIR=api.path['cleanup'].join('gclient'))
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
  successful_builds = api.buildbucket.search(
      rpc_pb2.BuildPredicate(
          builder={
              'project': PROJECT,
              'bucket': BUCKET,
              'builder': builder
          }, status=common_pb2.SUCCESS, include_experimental=False), limit=1,
      url_title_fn=api.naming.get_build_title)

  if not successful_builds:
    raise api.step.StepFailure(
        'No successful builds found for builder {}'.format(builder))

  return successful_builds[0]


def _launch_builders(api, builders):
  """Launch builders with recipe changes patched in.

  Builders are only launched if the files in the patched changes affect the
  builder's recipe, as determined by 'recipes.py analyze'. recipes.py determines
  this by looking at 3 different files: the recipe itself, the modules it
  depends on, and the .gitattributes file in the root of the repo.

  Args:
    * api (object): See RunSteps documentation.
    * builders (list[str]): Builders to launch.
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

    for builder in builders:
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
        len(results), len(builders))

    return results


def _extract_host_name(api, led_results):
  """Extract host name from the results of 'led launch'.

  Asserts there is only one host name.

  Args:
    * api (object): See RunSteps documentation.
    * led_results (list[dict]): A list of results from 'led launch'. Each must
      contain a 'swarming' key, which is a dict containing 'host_name' and
      'task_id' keys. I.e. results can be called like
      "results[0]['swarming']['host_name']".

  Returns:
    A str.
  """
  with api.step.nest('extract host name'):
    host_names = set(result['swarming']['host_name'] for result in led_results)

    # All builders should be in the staging bucket, and run on the same
    # swarming server.
    assert len(host_names) == 1, (
        'There should be exactly 1 swarming host name.'
        ' Actual host names: {}').format(host_names)

    return list(host_names)[0]


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
    with api.swarming.with_server(_extract_host_name(api, led_results)):
      return api.swarming.collect(
          'collect swarming tasks',
          [result['swarming']['task_id'] for result in led_results])


def _get_non_skipped_builders(api, builders):
  """Return a subset of 'builders' that are not skipped by CL footers.

  Args:
    * api (object): See RunSteps documentation.
    * builders (list[str]): A list of builders to test.

  Returns:
    A list[str].
  """
  with api.step.nest('get non-skipped builders') as step:
    skip_builders = api.tryserver.get_footer(SKIP_BUILDERS_FOOTER)

    for skip_builder in skip_builders:
      if skip_builder not in builders:
        raise ValueError(('Builder {} is specified in the {} footer, but is '
                          'not in the builders list ({})').format(
                              skip_builder, SKIP_BUILDERS_FOOTER, builders))

      builders.remove(skip_builder)

    step.presentation.step_text = 'Non-skipped builders: {}'.format(builders)
    step.presentation.logs['Skipped builders'] = skip_builders

    return builders


def _analyze_swarming_results(api, swarming_results, led_results):
  """Raise a StepFailure if any swarming task was unsuccessful.

  Args:
    * api(object): See RunSteps documentation.
    * swarming_results (list[swarming TaskResult]): Results returned from
      swarming.collect.
    * led_results (list[dict]): A list of results from 'led launch'. Each must
      contain a 'swarming' key, which is a dict containing 'host_name' and
      'task_id' keys. I.e. results can be called like
      "results[0]['swarming']['host_name']".

  Raises:
    StepFailure
  """
  with api.step.nest('analyze swarming results') as step:
    host_name = _extract_host_name(api, led_results)
    fail_count = 0
    for result in swarming_results:
      if not result.success:
        fail_count += 1

        url = 'https://{}/task?id={}'.format(host_name, result.id)
        step.presentation.links['[FAILED] {}'.format(result.name)] = url

    if fail_count:
      step.presentation.step_text = '{} tasks failed, {} succeeded'.format(
          fail_count,
          len(swarming_results) - fail_count)
      step.presentation.status = api.step.FAILURE

      raise api.step.StepFailure('{} tasks failed'.format(fail_count))
    else:
      step.presentation.step_text = 'all tasks succeeded'


def RunSteps(api, builders):
  if len(builders) == 0:
    raise ValueError('builders must be non-empty')

  for builder in builders:
    if 'staging' not in builder:
      raise ValueError(
          'only staging builders can be used (builder {} not valid)'.format(
              builder))

  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('gerrit_changes required as input.')

  non_skipped_builders = _get_non_skipped_builders(api, builders)

  with _checkout_recipes_repo(api):
    _apply_gerrit_changes(api)
    led_results = _launch_builders(api, non_skipped_builders)

  if led_results:
    swarming_results = _collect_results(api, led_results)
    _analyze_swarming_results(api, swarming_results, led_results)


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

  def get_non_skipped_builders_test_data(skipped_builders=None):
    """Get step data for the 'gerrit changes' and 'parse description' steps.

    Args:
      * skipped_builders (list[str] or None): If not none, a list of builders to
          skip with a CL footer.

    Returns:
      A tuple of TestData objects.
    """
    commit_message = 'A test change'

    if skipped_builders:
      footers = [
          '{}:{}'.format(SKIP_BUILDERS_FOOTER, builder)
          for builder in skipped_builders
      ]
      commit_message += '''

{}
'''.format('\n'.join(footers))

    return (api.step_data(
        'get non-skipped builders.gerrit changes',
        api.json.output([{
            'revisions': {
                1: {
                    '_number': 7,
                    'commit': {
                        'message': commit_message
                    }
                }
            }
        }])) +  #
            api.step_data(
                'get non-skipped builders.parse description',
                api.json.output({
                    SKIP_BUILDERS_FOOTER: skipped_builders
                } if skipped_builders else {})))

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

  def collect_results_failed_test_data():
    """Get step data for failures in a 'swarming.collect' command.

    Returns:
      A TestData object.
    """
    return api.step_data(
        'collect results.collect swarming tasks',
        api.swarming.collect([
            api.swarming.task_result(id='1', name="A swarming task",
                                     failure=True)
        ]))

  yield (
      api.test('basic') +
      # Specify two builders to run.
      api.properties(
          builders=['staging-Annealing', 'staging-chromite-postsubmit']) +  #
      api.buildbucket.try_build(project='chromeos', bucket='infra',
                                builder='recipes-tester') +
      # No builders are skipped
      get_non_skipped_builders_test_data() +  #
      # Buildbucket search results.
      buildbucket_search_test_data('staging-Annealing') +  #
      buildbucket_search_test_data('staging-chromite-postsubmit') +
      # led get-build results.
      led_get_build_test_data(builder='staging-Annealing',
                              recipe_name='annealing') +  #
      led_get_build_test_data(builder='staging-chromite-postsubmit',
                              recipe_name='test_chromite') +  #
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-Annealing',
                               recipes=['annealing']) +  #
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]) +
      # led launch results. Note that only annealing is launched.
      led_get_launch_test_data(builder='staging-Annealing'))

  yield (
      api.test('skipped_builder') +  #
      # Specify two builders to run.
      api.properties(
          builders=['staging-Annealing', 'staging-chromite-postsubmit']) +  #
      api.buildbucket.try_build(project='chromeos', bucket='infra',
                                builder='recipes-tester') +
      # The annealing builder is skipped
      get_non_skipped_builders_test_data(skipped_builders=['staging-Annealing']
                                        ) +  #
      # Buildbucket search results.
      buildbucket_search_test_data('staging-chromite-postsubmit') +
      # led get-build results.
      led_get_build_test_data(builder='staging-chromite-postsubmit',
                              recipe_name='test_chromite') +  #
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]))

  yield (api.test('failed_swarming_task') +
         # Specify one builder to run.
         api.properties(builders=['staging-Annealing']) +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester') +
         # No builders are skipped
         get_non_skipped_builders_test_data() +
         # Buildbucket search results
         buildbucket_search_test_data('staging-Annealing') +
         # led get-build results
         led_get_build_test_data(builder='staging-Annealing',
                                 recipe_name='annealing') +
         # recipe analyze results. Note that the annealing recipe is affected
         recipe_analyze_test_data(builder='staging-Annealing',
                                  recipes=['annealing']) +
         # led launch results
         led_get_launch_test_data(builder='staging-Annealing') +
         # swarming TaskResults contain a failed task.
         collect_results_failed_test_data())

  yield (api.test('invalid_skip_builder_footer') +
         # Specify two builders to run.
         api.properties(
             builders=['staging-Annealing', 'staging-chromite-postsubmit']) +  #
         # The skipped builder isn't part of the specified builders.
         get_non_skipped_builders_test_data(skipped_builders=['other-builder'])
         +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester') +  #
         api.expect_exception('ValueError'))

  yield (api.test('no_successful_builds') +  #
         get_non_skipped_builders_test_data() +  #
         api.buildbucket.try_build(project='chromeos', bucket='infra',
                                   builder='recipes-tester'))

  yield (api.test('no_gerrit_changes') +  #
         api.expect_exception('ValueError'))

  yield (api.test('no_builders') +  #
         api.properties(builders=[]) +  #
         api.expect_exception('ValueError'))

  yield (api.test('invalid_builders') +  #
         api.properties(builders=['production-builder']) +  #
         api.expect_exception('ValueError'))
