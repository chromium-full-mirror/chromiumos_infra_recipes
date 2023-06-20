# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests a recipe CL by running ChromeOS builders."""

from collections import OrderedDict
import contextlib
from typing import Dict, Generator, List, Optional, Tuple

from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.builds_service import BuildPredicate
from PB.go.chromium.org.luci.led.job import job as job_pb2
from PB.recipes.chromeos.test_recipes import TestRecipesProperties
from RECIPE_MODULES.recipe_engine.led.api import LedApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
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

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestRecipesProperties

# LUCI project to test.
PROJECT = 'chromeos'
# Bucket to test in. Only the staging environment should be used.
BUCKET = 'staging'


class VerifierRunInfo:
  """All of the information about a verifier."""

  def __init__(self, verifier: TestRecipesProperties.Verifier):
    """Collect all of the state for a verifier in one place.

    Args:
      verifier: The verifier.
    """
    self.verifier = verifier
    self.skipped = False
    self.led_job = None
    self.led_launch_result = None
    self.swarming_result = None

  @property
  def name(self) -> str:
    return self.verifier.name

  @property
  def critical(self) -> bool:
    return self.verifier.critical

  @property
  def always_launch(self) -> bool:
    return self.verifier.always_launch


def _verifier(name, critical: bool = False,
              always_launch: bool = False) -> TestRecipesProperties.Verifier:
  """Return a TestRecipesProperties.Verifier."""
  return TestRecipesProperties.Verifier(name=name, critical=critical,
                                        always_launch=always_launch)


# Default verifiers.
# Note: infra/config overrides this by specifying the input property.
DEFAULT_VERIFIERS = [
    _verifier(name='staging-Annealing', critical=True),
    _verifier(name='staging-amd64-generic-postsubmit', critical=True),
    _verifier(name='staging-chromite-postsubmit', critical=True),
    _verifier(name='staging-test-manifest', critical=True),
    _verifier(name='staging-release-triggerer', critical=True,
              always_launch=True),
]

# URL for the ChromeOS CI recipes repo.
RECIPE_REPO_HOST = 'chromium.googlesource.com'
RECIPE_REPO_PROJECT = 'chromiumos/infra/recipes'
RECIPE_REPO_URL = 'https://{}/{}'.format(RECIPE_REPO_HOST, RECIPE_REPO_PROJECT)

# A Git footer than can be included in commit messages to tell the recipe
# tester to skip builders. See the "Test Recipes Presubmit" in the README for
# more details.
SKIP_BUILDERS_FOOTER = 'Test-Recipes-Skip-Builder'


@contextlib.contextmanager
def _checkout_recipes_repo(api: RecipeApi) -> Generator[None, None, None]:
  """Yields a context where the cwd is the root of the recipes repo.

  Args:
    api: See RunSteps documentation.
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


def _apply_gerrit_changes(api: RecipeApi) -> None:
  """Cherry-picks the gerrit changes for the build into the cwd.

  Args:
    api: See RunSteps documentation.
  """
  with api.step.nest('apply gerrit changes'):
    patch_sets = api.gerrit.fetch_patch_sets([
        x for x in api.buildbucket.build.input.gerrit_changes
        if x.project == RECIPE_REPO_PROJECT
    ])

    for patch_set in patch_sets:
      commit_id = api.git.fetch_ref(patch_set.git_fetch_url,
                                    patch_set.git_fetch_ref)
      api.git.cherry_pick(commit_id, infra_step=False)


def _get_last_successful_build(api: RecipeApi, builder: str) -> build_pb2.Build:
  """Find the most recent successful build for 'builder'.

  Args:
    api: See RunSteps documentation.
    builder: The name of the builder to search for.
  Returns:
    A Build proto.
  Raises:
    A StepFailure if no build is found.
  """
  # Note that buildbucket.search returns results ordered newest-to-oldest.
  successful_builds = api.buildbucket.search(
      BuildPredicate(
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


def _launch_verifiers(api: RecipeApi, verifiers: Dict[str, VerifierRunInfo],
                      head: str) -> Dict[str, VerifierRunInfo]:
  """Launch verifiers with recipe changes patched in.

  Verifiers are only launched if the files in the patched changes affect the
  verifier's recipe, as determined by 'recipes.py analyze'. recipes.py
  determines this by looking at 3 different files: the recipe itself, the
  modules it depends on, and the .gitattributes file in the root of the repo.

  Args:
    api: See RunSteps documentation.
    verifiers:VerifierRunInfo): Verifiers to consider.
    head: The HEAD commit before applying patches.

  Returns:
    verifiers dict, mutated to include led and launch results.
  """
  with api.step.nest('analyze and launch builders') as launch_pres:
    results = []

    with api.step.nest('get affected files') as affected_files_pres:
      # Changes should be cherry picked at this point. The relevant diffs should
      # be between the original checkout and HEAD.
      affected_files = api.git.get_diff_files(from_rev=head, to_rev='HEAD')
      affected_files_pres.logs['affected files'] = affected_files

    # TODO(crbug/1012763) small bots do not work well with led launch.
    def _bad_bot_size(swarm: build_pb2.BuildInfra.Swarming) -> bool:
      for d in swarm.task_dimensions:
        if d.key == "bot_size":
          if d.value and d.value != "small":
            return False
          break
      return True

    my_id = api.swarming.task_id
    considered = 0
    for idx, verifier in enumerate(verifiers.values()):
      if verifier.skipped:
        continue
      builder = verifier.name
      considered += 1
      with api.step.nest(
          'analyze and launch {}'.format(builder)) as builder_pres:
        # Get a led result from led to extract the builder definition.
        # Then, chain on calls to launch the builder (if it is relevant).
        # Mark this as a dry_run so that builders with side effects (for
        # example, annealing pushes a manifest_ref) can avoid them.
        last_successful_build = _get_last_successful_build(api, builder)
        led_result = api.led('get-build', last_successful_build.id)

        buildbucket = led_result.result.buildbucket
        build = buildbucket.bbagent_args.build
        swarm = build.infra.swarming
        recipe = build.input.properties['recipe']

        if (verifier.always_launch or
            api.recipe_analyze.is_recipe_affected(affected_files, recipe)):

          # Pass the output gitiles commit to the re-run.
          if not build.input.gitiles_commit.project:
            build.input.gitiles_commit.CopyFrom(
                last_successful_build.output.gitiles_commit)

          # Set the buildbucket test_recipes_task_id tag.
          tag = buildbucket.bbagent_args.build.tags.add()
          tag.key = "test_recipes_task_id"
          tag.value = my_id

          # Provide a unique id for testing.
          if api._test_data.enabled:  # pylint: disable=protected-access
            swarm.task_id = 'fake-id-{}'.format(idx + 1)

          build.input.properties.update(api.cq.props_for_child_build)
          led_result = led_result.then('edit', '-p', 'dry_run=true')
          if _bad_bot_size(swarm):
            led_result = led_result.then('edit', '-d', 'bot_size=large')

          # Skip paygen on release builds since we launch paygen directly.
          if recipe == 'build_release':
            led_result = led_result.then('edit', '-p', 'skip_paygen=true')

          # Run the child task with priority=20, to put it ahead of actual
          # staging jobs.  We could run it with the dimension 'role=infra',
          # but there are no large role=infra bots.
          name = '%s %s' % (builder, last_successful_build.id)
          led_result = led_result.then('edit-recipe-bundle').then(
              'edit-system', '-p', '20').then('edit', '-name', name)
          verifier.led_job = led_result
          result = led_result.then('launch').launch_result
          verifier.led_launch_result = result
          url = 'https://{}/task?id={}'.format(result.swarming_hostname,
                                               result.task_id)
          launch_pres.links[builder] = url
          results.append(result)
        else:
          builder_pres.step_text = (
              'builder {} (recipe {}) not affected'.format(builder, recipe))

    launch_pres.step_text = 'launched {} / {} builders'.format(
        len(results), considered)

    return verifiers


def _extract_host_name(api: RecipeApi,
                       led_results: List[LedApi.LedLaunchData]) -> str:
  """Extract host name from the results of 'led launch'.

  Asserts there is only one host name.

  Args:
    api: See RunSteps documentation.
    led_results: List of led results.

  Returns:
    The swarming host name.
  """
  with api.step.nest('extract host name'):
    host_names = set(result.swarming_hostname for result in led_results)

    # All builders should be in the staging bucket, and run on the same
    # swarming server.
    assert len(host_names) == 1, (
        'There should be exactly 1 swarming host name.'
        ' Actual host names: {}').format(host_names)

    return list(host_names)[0]


def _collect_results(
    api: RecipeApi,
    verifiers: Dict[str, VerifierRunInfo]) -> Dict[str, VerifierRunInfo]:
  """Collect results from swarming, blocking if necessary.

  Args:
    api: See RunSteps documentation.
    verifiers: The verifiers.

  Returns:
    verifiers dict, mutated to include swarming results.
  """
  verifier_by_id = OrderedDict((v.led_launch_result.task_id, v)
                               for v in verifiers.values()
                               if v.led_launch_result)
  assert verifier_by_id
  with api.step.nest('collect results'):
    results = api.swarming.collect(
        'collect swarming tasks',
        [v.led_launch_result.task_id for v in verifier_by_id.values()])
    for result in results:
      verifier_by_id[result.id].swarming_result = result
    return verifiers


def _update_skipped_verifiers(
    api: RecipeApi,
    verifiers: Dict[str, VerifierRunInfo]) -> Dict[str, VerifierRunInfo]:
  """Return a subset of 'builders' that are not skipped by CL footers.

  Args:
    api: See RunSteps documentation.
    verifiers: A dictionary of verifiers.

  Returns:
    verifiers dict, mutated to mark skipped builders.
  """
  with api.step.nest('get non-skipped builders') as presentation:
    # TODO(crbug/1039875): tryserver.get_footer only supports one CL.  When a
    # replacement solution is implemented, divergent skip_builders instructions
    # should result in an error.
    if len(api.buildbucket.build.input.gerrit_changes) > 1:
      presentation.step_text = 'multiple CLs, not skipping builders'
      return verifiers

    skip_builders = api.tryserver.get_footer(SKIP_BUILDERS_FOOTER)

    for skip_builder in skip_builders:
      if skip_builder not in verifiers:
        raise StepFailure(('Builder {} is specified in the {} footer, but is '
                           'not in the builders list ({})').format(
                               skip_builder, SKIP_BUILDERS_FOOTER,
                               ' '.join(x.name for x in verifiers.values())))

      verifiers[skip_builder].skipped = True

    builders = [v.name for v in verifiers.values() if not v.skipped]
    presentation.step_text = 'Non-skipped builders: {}'.format(builders)
    presentation.logs['Skipped builders'] = skip_builders

    return verifiers


def _analyze_swarming_results(api: RecipeApi, verifiers: Dict[str,
                                                              VerifierRunInfo]):
  """Raise a StepFailure if any swarming task was unsuccessful.

  Args:
    api: See RunSteps documentation.
    verifiers: The verifiers.

  Raises:
    StepFailure
  """
  with api.step.nest('analyze swarming results') as presentation:
    host_name = _extract_host_name(api, [
        v.led_launch_result for v in verifiers.values() if v.led_launch_result
    ])
    fail_count = 0
    total_count = 0
    for verifier in verifiers.values():
      result = verifier.swarming_result
      if result:
        total_count += 1
        if not result.success:
          if verifier.critical:
            fail_count += 1
          url = 'https://{}/task?id={}'.format(host_name, result.id)
          presentation.links['[FAILED] {}{}'.format(
              result.name, '' if verifier.critical else '(non-critical)')] = url

    if fail_count:
      presentation.step_text = '{} tasks failed, {} succeeded'.format(
          fail_count, total_count - fail_count)
      presentation.status = api.step.FAILURE

      raise StepFailure(
          '{} tasks failed. Please file a go/cros-recipes-cq-fail if you believe the failures are unrelated to your change.'
          .format(fail_count))
    presentation.step_text = 'all tasks succeeded'


def RunSteps(api: RecipeApi, properties: TestRecipesProperties) -> None:
  api.step.nest('set up')
  verifier_list = properties.verifiers or DEFAULT_VERIFIERS
  verifiers = OrderedDict(((v.name, VerifierRunInfo(v)) for v in verifier_list))

  for verifier in verifiers.values():
    if not verifier.name.startswith('staging-'):
      raise StepFailure(
          'only staging builders can be used (builder {} not valid)'.format(
              verifier.name))

  if not api.buildbucket.build.input.gerrit_changes:
    raise StepFailure('gerrit_changes required as input.')

  verifiers = _update_skipped_verifiers(api, verifiers)

  with _checkout_recipes_repo(api):
    head = api.git.head_commit()
    _apply_gerrit_changes(api)
    _launch_verifiers(api, verifiers, head)

  if any(v.led_launch_result for v in verifiers.values()):
    _collect_results(api, verifiers)
    _analyze_swarming_results(api, verifiers)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def launch_step_name(builder: str, step_name: str) -> str:
    """Get the full name of a step used during the launch of a builder.

    Args:
      builder: The name of the builder.
      step_name: The name of the step (e.g. 'led launch').

    Returns:
      The full name of the step.
    """
    return 'analyze and launch builders.analyze and launch {}.{}'.format(
        builder, step_name)

  def get_non_skipped_builders_test_data(
      skipped_builders: Optional[List[str]] = None) -> Tuple[TestData]:
    """Get step data for the 'gerrit changes' and 'parse description' steps.

    Args:
      skipped_builders: A list of builders to skip with a CL footer, or None.

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

  def _mock_edit(job: job_pb2.Definition, cmd: List[str],
                 _cwd: Path) -> job_pb2.Definition:
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

  def buildbucket_search_and_get_build(builder: str, recipe_name: str,
                                       fake_id: int) -> TestData:
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

  def recipe_analyze_test_data(builder: str, recipes: List[str]) -> TestData:
    """Get step data for a 'recipes.py analyze' command.

    Args:
      builder: The name of the builder.
      recipes: The recipes to return in the Output proto.

    Returns:
      A TestData object.
    """
    return api.step_data(
        launch_step_name(builder, 'recipe analyze'),
        api.json.output({'recipes': recipes}))

  def collect_results_failed_test_data() -> TestData:
    """Get step data for failures in a 'swarming.collect' command.

    Returns:
      A TestData object.
    """
    return api.step_data(
        'collect results.collect swarming tasks',
        api.swarming.collect([
            api.swarming.task_result(id='fake-id-1', name="A swarming task",
                                     failure=True),
            api.swarming.task_result(id='fake-id-2', name="Another task")
        ]))

  def try_build(project: str, bucket: str, builder: str) -> TestData:
    """Return a tryb_build for the recipes repo.

    Returns:
      A TestData object.
    """
    return api.buildbucket.try_build(project=project, bucket=bucket,
                                     builder=builder, git_repo=RECIPE_REPO_URL,
                                     priority=30)

  def two_cl_try_build(project: str, bucket: str, builder: str) -> TestData:
    """Return a try_build with two CLs attached to it.

    Returns:
      A TestData object.
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

  def two_cl_try_build_with_other_repo(project: str, bucket: str,
                                       builder: str) -> TestData:
    """Return a try_build with two CLs attached to it.

    Returns:
      A TestData object.
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
      api.cq(run_mode=api.cq.FULL_RUN),
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'staging-Annealing',
              'critical': True
          }, {
              'name': 'staging-chromite-postsubmit',
              'critical': True
          }, {
              'name': 'staging-no-size',
              'critical': True
          }, {
              'name': 'staging-release-triggerer',
              'always_launch': True,
              'critical': True
          }, {
              'name': 'staging-release-main-octopus',
              'always_launch': True,
              'critical': True
          }])),
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
      buildbucket_search_and_get_build('staging-release-main-octopus',
                                       'build_release', 5),
      # recipe analyze results. Note that the test_chromite recipe isn't
      # affected.
      recipe_analyze_test_data(builder='staging-no-size',
                               recipes=['no_size_recipe']),
      recipe_analyze_test_data(builder='staging-Annealing',
                               recipes=['annealing']),
      recipe_analyze_test_data(builder='staging-chromite-postsubmit',
                               recipes=[]))

  yield api.test(
      'two-changes',
      api.cq(run_mode=api.cq.FULL_RUN),
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'staging-Annealing',
              'critical': True
          }, {
              'name': 'staging-chromite-postsubmit',
              'critical': True
          }, {
              'name': 'staging-release-triggerer',
              'always_launch': True,
              'critical': True
          }])),
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
      'two-changes-mixed-repos',
      api.cq(run_mode=api.cq.FULL_RUN),
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'staging-Annealing',
              'critical': True
          }, {
              'name': 'staging-chromite-postsubmit',
              'critical': True
          }, {
              'name': 'staging-release-triggerer',
              'always_launch': True,
              'critical': True
          }])),
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
      'skipped-builder',
      api.cq(run_mode=api.cq.FULL_RUN),
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'staging-Annealing',
              'critical': True
          }, {
              'name': 'staging-chromite-postsubmit',
              'critical': True
          }, {
              'name': 'staging-release-triggerer',
              'always_launch': True,
              'critical': True
          }])),
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
      'failed-swarming-task',
      api.cq(run_mode=api.cq.FULL_RUN),
      # Specify one builder to run.
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'staging-Annealing',
              'critical': True
          }, {
              'name': 'staging-release-triggerer',
              'always_launch': True,
              'critical': True
          }])),
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
      collect_results_failed_test_data(),
      status='FAILURE',
  )

  yield api.test(
      'invalid-skip-builder-footer',
      api.cq(run_mode=api.cq.FULL_RUN),
      # Specify two builders to run.
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'staging-Annealing',
              'critical': True
          }, {
              'name': 'staging-chromite-postsubmit',
              'critical': True
          }, {
              'name': 'staging-release-triggerer',
              'always_launch': True,
              'critical': True
          }])),
      # The skipped builder isn't part of the specified builders.
      get_non_skipped_builders_test_data(skipped_builders=['other-builder']),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'),
      status='FAILURE',
  )

  yield api.test(
      'no-successful-builds',
      api.cq(run_mode=api.cq.FULL_RUN),
      get_non_skipped_builders_test_data(),
      try_build(project='chromeos', bucket='infra', builder='test-recipes'),
      status='FAILURE',
  )

  yield api.test(
      'no_gerrit_changes',
      api.cq(run_mode=api.cq.FULL_RUN),
      status='FAILURE',
  )

  yield api.test(
      'invalid-builders',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          TestRecipesProperties(verifiers=[{
              'name': 'production-builder',
              'critical': True
          }])),
      status='FAILURE',
  )
