# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests a recipe CL by running ChromeOS builders."""

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

import contextlib
import re
from recipe_engine.recipe_api import StepFailure

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.led.job import job as job_pb2

from PB.recipes.chromeos.test_recipes import TestRecipesProperties

PROPERTIES = TestRecipesProperties

# LUCI project to test.
PROJECT = 'chromeos'
# Bucket to test in. Only the staging environment should be used.
BUCKET = 'staging'

# Note: infra/config overrides this by specifying the input property.
DEFAULT_BUILDERS = [
    'staging-Annealing', 'staging-amd64-generic-postsubmit',
    'staging-chromite-postsubmit', 'staging-test-manifest'
]

# Default builders to *ALWAYS* launch.
ALWAYS_DEFAULT = ['staging-release-triggerer']

# URL for the ChromeOS CI recipes repo.
RECIPE_REPO_HOST = 'chromium.googlesource.com'
RECIPE_REPO_PROJECT = 'chromiumos/infra/recipes'
RECIPE_REPO_URL = 'https://{}/{}'.format(RECIPE_REPO_HOST, RECIPE_REPO_PROJECT)

# A Git footer than can be included in commit messages to tell the recipe
# tester to skip builders. See the "Test Recipes Presubmit" in the README for
# more details.
SKIP_BUILDERS_FOOTER = 'Test-Recipes-Skip-Builder'


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
        x for x in api.buildbucket.build.input.gerrit_changes
        if x.project == RECIPE_REPO_PROJECT)

    for patch_set in patch_sets:
      commit_id = api.git.fetch_ref(patch_set.git_fetch_url,
                                    patch_set.git_fetch_ref)
      api.git.cherry_pick(commit_id, infra_step=False)


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
      builds_service_pb2.BuildPredicate(
          builder={
              'project': PROJECT,
              'bucket': BUCKET,
              'builder': builder
          }, status=common_pb2.SUCCESS, include_experimental=False), limit=1,
      url_title_fn=api.naming.get_build_title)

  if not successful_builds:
    raise StepFailure(
        'No successful builds found for builder {}'.format(builder))

  return successful_builds[0]


def _launch_builders(api, test_builders, always_launch_builders):
  """Launch builders with recipe changes patched in.

  Builders are only launched if the files in the patched changes affect the
  builder's recipe, as determined by 'recipes.py analyze'. recipes.py determines
  this by looking at 3 different files: the recipe itself, the modules it
  depends on, and the .gitattributes file in the root of the repo.

  Args:
    * api (object): See RunSteps documentation.
    * test_builders (list[str]): Builders to CONDITIONALLY launch.
    * always_launch_builders (list[str]): Builders to ALWAYS launch.

  Returns:
    A list of led.LedLaunchData.
  """
  with api.step.nest('analyze and launch builders') as launch_pres:
    results = []

    with api.step.nest('get affected files') as affected_files_pres:
      # Changes should be cherry picked at this point. The relevant diffs should
      # be between the original master and HEAD.
      affected_files = api.git.get_diff_files(from_rev='origin/master',
                                              to_rev='HEAD')
      affected_files_pres.logs['affected files'] = affected_files

    builders = list(test_builders)
    builders += [x for x in always_launch_builders if x not in test_builders]
    my_id = api.swarming.task_id

    # TODO(crbug/1012763) small bots do not work well with led launch.
    def _bad_bot_size(led_result):
      swarm = led_result.result.buildbucket.bbagent_args.build.infra.swarming
      for d in swarm.task_dimensions:
        if d.key == "bot_size":
          if d.value and d.value != "small":
            return False
          break
      return True

    for builder in builders:
      with api.step.nest(
          'analyze and launch {}'.format(builder)) as builder_pres:
        # Get a led result from led to extract the builder definition.
        # Then, chain on calls to launch the builder (if it is relevant).
        # Mark this as a dry_run so that builders with side effects (for
        # example, annealing pushes a manifest_ref) can avoid them.
        last_successful_build = _get_last_successful_build(api, builder)
        led_result = api.led('get-build', last_successful_build.id).then(
            'edit', '-p', 'dry_run=true')

        buildbucket = led_result.result.buildbucket
        recipe = buildbucket.bbagent_args.build.input.properties['recipe']

        if _bad_bot_size(led_result):
          led_result = led_result.then('edit', '-d', 'bot_size=large')

        if (builder in always_launch_builders or
            api.recipe_analyze.is_recipe_affected(affected_files, recipe)):
          # Run the child task with priority=20, to put it ahead of actual
          # staging jobs.  We could run it with the dimension 'role=infra',
          # but there are no large role=infra bots.
          name = '%s %s' % (builder, last_successful_build.id)
          tag = buildbucket.bbagent_args.build.tags.add()
          tag.key = "test_recipes_task_id"
          tag.value = my_id
          result = led_result.then('edit-recipe-bundle').then(
              'edit-system', '-p', '20').then('edit', '-name',
                                              name).then('launch').launch_result
          url = 'https://{}/task?id={}'.format(result.swarming_hostname,
                                               result.task_id)
          launch_pres.links[builder] = url
          results.append(result)
        else:
          builder_pres.step_text = (
              'builder {} (recipe {}) not affected'.format(builder, recipe))

    launch_pres.step_text = 'launched {} / {} builders'.format(
        len(results), len(builders))

    return results


def _extract_host_name(api, led_results):
  """Extract host name from the results of 'led launch'.

  Asserts there is only one host name.

  Args:
    * api (object): See RunSteps documentation.
    * led_results (list[led.LedLaunchData])

  Returns:
    A str.
  """
  with api.step.nest('extract host name'):
    host_names = set(result.swarming_hostname for result in led_results)

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
    * led_results (list[led.LedLaunchData]):

  Returns:
    A list of swarming TaskResult.
  """
  assert led_results
  with api.step.nest('collect results'):
    with api.swarming.with_server(_extract_host_name(api, led_results)):
      return api.swarming.collect('collect swarming tasks',
                                  [result.task_id for result in led_results])


def _get_non_skipped_builders(api, builders):
  """Return a subset of 'builders' that are not skipped by CL footers.

  Args:
    * api (object): See RunSteps documentation.
    * builders (list[str]): A list of builders to test.

  Returns:
    A list[str].
  """
  with api.step.nest('get non-skipped builders') as presentation:
    # TODO(crbug/1039875): tryserver.get_footer only supports one CL.  When a
    # replacement solution is implemented, divergent skip_builders instructions
    # should result in an error.
    if len(api.buildbucket.build.input.gerrit_changes) > 1:
      presentation.step_text = 'multiple CLs, not skipping builders'
      return builders

    skip_builders = api.tryserver.get_footer(SKIP_BUILDERS_FOOTER)

    for skip_builder in skip_builders:
      if skip_builder not in builders:
        raise ValueError(
            ('Builder {} is specified in the {} footer, but is '
             'not in the builders list ({})').format(skip_builder,
                                                     SKIP_BUILDERS_FOOTER,
                                                     builders))

      builders.remove(skip_builder)

    presentation.step_text = 'Non-skipped builders: {}'.format(builders)
    presentation.logs['Skipped builders'] = skip_builders

    return builders


def _analyze_swarming_results(api, swarming_results, led_results):
  """Raise a StepFailure if any swarming task was unsuccessful.

  Args:
    * api(object): See RunSteps documentation.
    * swarming_results (list[swarming TaskResult]): Results returned from
      swarming.collect.
    * led_results (list[led.LedLaunchData]):

  Raises:
    StepFailure
  """
  with api.step.nest('analyze swarming results') as presentation:
    host_name = _extract_host_name(api, led_results)
    fail_count = 0
    for result in swarming_results:
      if not result.success:
        fail_count += 1

        url = 'https://{}/task?id={}'.format(host_name, result.id)
        presentation.links['[FAILED] {}'.format(result.name)] = url

    if fail_count:
      presentation.step_text = '{} tasks failed, {} succeeded'.format(
          fail_count,
          len(swarming_results) - fail_count)
      presentation.status = api.step.FAILURE

      raise StepFailure('{} tasks failed'.format(fail_count))
    else:
      presentation.step_text = 'all tasks succeeded'


def RunSteps(api, properties):
  api.step.nest('set up')
  builders = properties.builders or DEFAULT_BUILDERS
  always_launch_builders = properties.always_launch_builders or ALWAYS_DEFAULT

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
    led_results = _launch_builders(api, non_skipped_builders,
                                   always_launch_builders)

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

    ret = api.step_data(
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
        }]))
    ret += api.step_data(
        'get non-skipped builders.parse description',
        api.json.output({SKIP_BUILDERS_FOOTER: skipped_builders}
                        if skipped_builders else {}))
    return ret

  def _mock_edit(job, cmd, cwd):
    """Handler for `led edit -d` (set task_dimension).

    We use this to mock setting the bot_size in the recipe.
    """
    vals = api.led.get_arg_values(cmd, 'd')
    k, v = vals[0].split('=')
    swarm = job.buildbucket.bbagent_args.build.infra.swarming
    for d in swarm.task_dimensions:
      if d.key == k:
        d.value = v
      return job
    dim = swarm.task_dimensions.add()
    dim.key = k
    dim.value = v
    return job

  def buildbucket_search_and_get_build(builder, recipe_name, fake_id):
    fake_build = job_pb2.Definition()
    build_proto = fake_build.buildbucket.bbagent_args.build
    build_proto.input.properties['recipe'] = recipe_name
    build_proto.builder.builder = builder

    if recipe_name != 'no_size_recipe':
      dim = build_proto.infra.swarming.task_dimensions.add()
      dim.key = 'bot_size'
      dim.value = 'small' if recipe_name == 'release_triggerer' else 'large'

    ret = api.buildbucket.simulated_search_results(
        builds=[build_pb2.Build(id=fake_id, builder={'builder': builder})],
        step_name=launch_step_name(builder, 'buildbucket.search'))
    ret += api.led.mock_edit(_mock_edit, cmd_filter=['edit', '-d'])
    return ret + api.led.mock_get_build(fake_build, fake_id)

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
        api.json.output({'recipes': recipes}))

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

  def try_build(project, bucket, builder):
    """Return a tryb_build for the recipes repo.

    Returns:
      recipe_test_api.TestData object.
    """
    return api.buildbucket.try_build(project=project, bucket=bucket,
                                     builder=builder, git_repo=RECIPE_REPO_URL,
                                     priority=30)

  def two_cl_try_build(project, bucket, builder):
    """Return a try_build with two CLs attached to it.

    Returns:
      recipe_test_api.TestData object.
    """
    msg = api.buildbucket.try_build_message(project, bucket, builder,
                                            git_repo=RECIPE_REPO_URL)
    cl1 = msg.input.gerrit_changes[0]
    msg.input.gerrit_changes.extend([
        common_pb2.GerritChange(host=cl1.host, project=cl1.project,
                                change=cl1.change + 1,
                                patchset=cl1.patchset + 3)
    ])
    return api.buildbucket.build(msg)

  def two_cl_try_build_with_other_repo(project, bucket, builder):
    """Return a try_build with two CLs attached to it.

    Returns:
      recipe_test_api.TestData object.
    """
    msg = api.buildbucket.try_build_message(project, bucket, builder,
                                            git_repo=RECIPE_REPO_URL)
    cl1 = msg.input.gerrit_changes[0]
    msg.input.gerrit_changes.extend([
        common_pb2.GerritChange(host=cl1.host, project='chromiumos/chromite',
                                change=cl1.change + 1,
                                patchset=cl1.patchset + 3)
    ])
    return api.buildbucket.build(msg)

  yield api.test(
      'basic',
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(builders=[
              'staging-Annealing', 'staging-chromite-postsubmit',
              'staging-no-size'
          ])),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'),
      # No builders are skipped
      get_non_skipped_builders_test_data(),
      # Buildbucket search and led get-build results.
      buildbucket_search_and_get_build('staging-Annealing', 'annealing', 1),
      buildbucket_search_and_get_build('staging-chromite-postsubmit',
                                       'test_chromite', 2),
      buildbucket_search_and_get_build('staging-release-triggerer',
                                       'release_triggerer', 3),
      buildbucket_search_and_get_build('staging-no-size', 'no_size_recipe', 4),
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-no-size',
                               recipes=['no_size_recipe']),
      recipe_analyze_test_data(builder='staging-Annealing',
                               recipes=['annealing']),
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]))

  yield api.test(
      'two_changes',
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(
              builders=['staging-Annealing', 'staging-chromite-postsubmit'])),
      two_cl_try_build(project='chromeos', bucket='infra',
                       builder='test-recipes'),
      # Buildbucket search and led get-build results.
      buildbucket_search_and_get_build('staging-Annealing', 'annealing', 1),
      buildbucket_search_and_get_build('staging-chromite-postsubmit',
                                       'test_chromite', 2),
      buildbucket_search_and_get_build('staging-release-triggerer',
                                       'release_triggerer', 3),
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-Annealing',
                               recipes=['annealing']),
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]))

  yield api.test(
      'two_changes_mixed_repos',
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(
              builders=['staging-Annealing', 'staging-chromite-postsubmit'])),
      two_cl_try_build_with_other_repo(project='chromeos', bucket='infra',
                                       builder='test-recipes'),
      # Buildbucket search and led get-build results.
      buildbucket_search_and_get_build('staging-Annealing', 'annealing', 1),
      buildbucket_search_and_get_build('staging-chromite-postsubmit',
                                       'test_chromite', 2),
      buildbucket_search_and_get_build('staging-release-triggerer',
                                       'release_triggerer', 3),
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-Annealing',
                               recipes=['annealing']),
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]))

  yield api.test(
      'skipped_builder',
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(
              builders=['staging-Annealing', 'staging-chromite-postsubmit'])),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'),
      # The annealing builder is skipped
      get_non_skipped_builders_test_data(skipped_builders=['staging-Annealing']
                                        ),
      # Buildbucket search and led get-build results.
      buildbucket_search_and_get_build('staging-chromite-postsubmit',
                                       'test_chromite', 1),
      buildbucket_search_and_get_build('staging-release-triggerer',
                                       'release_triggerer', 2),
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]))

  yield api.test(
      'failed_swarming_task',
      # Specify one builder to run.
      api.properties(TestRecipesProperties(builders=['staging-Annealing'])),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'),
      # No builders are skipped
      get_non_skipped_builders_test_data(),
      # Buildbucket search and led get-build results.
      buildbucket_search_and_get_build('staging-Annealing', 'annealing', 1),
      buildbucket_search_and_get_build('staging-release-triggerer',
                                       'release_triggerer', 2),
      # recipe analyze results. Note that the annealing recipe is affected
      recipe_analyze_test_data(builder='staging-Annealing',
                               recipes=['annealing']),
      # swarming TaskResults contain a failed task.
      collect_results_failed_test_data())

  yield api.test(
      'invalid_skip_builder_footer',
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(
              builders=['staging-Annealing', 'staging-chromite-postsubmit'])),
      # The skipped builder isn't part of the specified builders.
      get_non_skipped_builders_test_data(skipped_builders=['other-builder']),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'),
      api.expect_exception('ValueError'))

  yield api.test(
      'no_successful_builds', get_non_skipped_builders_test_data(),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'))

  yield api.test('no_gerrit_changes', api.expect_exception('ValueError'))

  yield api.test(
      'invalid_builders',
      api.properties(TestRecipesProperties(builders=['production-builder'])),
      api.expect_exception('ValueError'))
