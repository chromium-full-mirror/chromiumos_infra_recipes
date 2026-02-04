# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures."""

from typing import Generator

from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'bot_cost',
    'build_menu',
    'cros_infra_config',
    'cros_release',
    'cros_source',
    'cros_version',
    'easy',
    'gerrit',
    'git',
    'orch_menu',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'src_state',
    'test_util',
]

PROPERTIES = OrchestratorProperties


def RunSteps(api: RecipeApi,
             properties: OrchestratorProperties) -> result_pb2.RawResult:
  with api.bot_cost.build_cost_context():
    is_staging = api.cros_infra_config.is_staging

    commit = api.src_state.gitiles_commit
    if api.orch_menu.gitiles_commit:
      commit = api.orch_menu.gitiles_commit
    branch = api.git.extract_branch(commit.ref, commit.ref)

    named_builder = '{}{}'.format('staging-' if is_staging else '',
                                  branch.replace('.B', '-cq'))
    named_child_config = api.cros_infra_config.get_builder_config(
        named_builder, missing_ok=True)
    api.easy.set_properties_step(manifest_branch=branch)
    api.step('launch', ['child'])
    config = None
    if named_child_config:
      config = api.cros_source.configure_builder()
      api.easy.set_properties_step(child_verifier=named_builder)
      api.orch_menu.schedule_wait_build(named_builder, await_completion=True,
                                        check_failures=True,
                                        step_name='launch child')
    else:
      with api.step.nest('launch child') as pres:
        pres.step_text = 'Builder {} is not configured, attempting to launch dynamic children'.format(
            named_builder)
      config = api.orch_menu.setup_orchestrator()
      if config:
        api.easy.set_properties_step(child_verifier='dynamic')
        if api.orch_menu.bump_version:
          with api.build_menu.configure_builder(commit=commit) \
          as _, api.build_menu.setup_workspace():
            api.cros_version.bump_version(dry_run=is_staging)
            api.cros_release.create_buildspec(
                dry_run=is_staging, gs_location=properties.buildspec_gs_path)
        api.orch_menu.plan_and_run_children()

    if config:
      api.orch_menu.run_follow_on_orchestrator()

    return api.orch_menu.create_recipe_result()

def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  test_base = 'firmware-board-5555'
  test_branch = f'{test_base}.B'
  test_builder = f'{test_base}-cq'

  def test(name, *args, **kwargs):
    kwargs.setdefault('builder', 'firmware-cq-orchestrator')
    kwargs.setdefault('cq', True)
    branch = kwargs.pop('branch', test_branch)
    collect_builds = kwargs.pop('collect_builds', [])
    expected_properties = kwargs.pop('expected_properties', {})

    # Mock the ref on the gitiles_commit property
    input_props = kwargs.get('input_properties', {})
    input_props.setdefault('$chromeos/src_state', {})

    # Pass gitiles_commit to buildbucket explicitly via individual fields
    kwargs[
        'git_repo'] = 'https://chromium.googlesource.com/chromiumos/manifest-internal'
    kwargs['revision'] = 'deadbeef' * 10
    kwargs['git_ref'] = f'refs/heads/{branch}'

    kwargs['input_properties'] = input_props

    child_builder_name = test_builder
    if kwargs.get('bucket') == 'staging':
      child_builder_name = f'staging-{test_builder}'
      kwargs['builder'] = 'staging-firmware-cq-orchestrator'

    builder_config_data = BuilderConfigs()
    # Always add the orchestrator's own config
    orch_config = builder_config_data.builder_configs.add()
    orch_config.id.name = kwargs['builder']
    orch_config.orchestrator.child_specs.add().name = 'dynamic-child'
    orch_config.build.apply_gerrit_changes = True

    # Add config for the dynamic child
    dynamic_child = builder_config_data.builder_configs.add()
    dynamic_child.id.name = 'dynamic-child'

    # Add the named child config only if not 'no-child' test
    if name not in ['no-child', 'bump-version']:
      builder = builder_config_data.builder_configs.add()
      builder.id.name = child_builder_name
      # Add bucket to ensure config is valid/found
      builder.id.bucket = kwargs.get('bucket', 'cq')

    # print(f"DEBUG: {name} builder_config_data: {builder_config_data}")

    args += (api.cros_infra_config.override_builder_configs_test_data(
        builder_config_data),)

    # args += (api.post_process(DropExpectation),)
    return api.orch_menu.test(name, *args, collect_builds=collect_builds,
                              properties=expected_properties, **kwargs)

  yield test(
      'cq', expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': test_builder
      })

  yield test(
      'staging-cq', expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': f'staging-{test_builder}'
      }, bucket='staging')

  yield test(
      'cq-tagged', expected_properties={
          'manifest_branch': f'{test_base}-main',
          'child_verifier': test_builder
      }, branch=f'{test_base}-main')

  yield test(
      'failed-child',
      status='FAILURE',
      expected_properties={'manifest_branch': test_branch,
                             'child_verifier': test_builder}) + \
        api.buildbucket.simulated_collect_output(
            [
                api.test_util.test_build(builder=test_builder, status='FAILURE',
                                         critical='YES').message
            ],
            step_name='launch child.collect'
        )

  yield test(
      'no-child', expected_properties={
          'manifest_branch': f'{test_base}6.B',
          'child_verifier': 'dynamic'
      }, branch=f'{test_base}6.B')

  yield test(
      'bump-version', expected_properties={
          'manifest_branch': f'{test_base}6.B',
          'child_verifier': 'dynamic'
      }, branch=f'{test_base}6.B', bucket='staging',
      input_properties={'$chromeos/orch_menu': {
          'bump_version': True
      }})
