# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures."""

from typing import Generator

from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.firmware_orchestrator import FirmwareOrchestratorProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'bot_cost',
    'cros_infra_config',
    'cros_source',
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

PROPERTIES = FirmwareOrchestratorProperties


def RunSteps(
    api: RecipeApi,
    _properties: FirmwareOrchestratorProperties) -> result_pb2.RawResult:
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
    config = None
    if named_child_config:
      config = api.cros_source.configure_builder()
      api.easy.set_properties_step(child_verifier=named_builder)
      api.orch_menu.schedule_wait_build(named_builder, await_completion=True,
                                        check_failures=True,
                                        step_name='launch child')
      # This is used to run android firmware builders after the rest with a distinct version number.
      api.orch_menu.run_follow_on_builders(config=config)

      return api.orch_menu.create_recipe_result()

    with api.step.nest('launch child') as pres:
      pres.step_text = 'Builder {} is not configured, attempting to launch dynamic children'.format(
          named_builder)
    with api.orch_menu.setup_orchestrator() as config:
      if config:
        api.easy.set_properties_step(child_verifier='dynamic')
        api.orch_menu.plan_and_run_children()

      # This is used to run android firmware builders after the rest with a distinct version number.
      api.orch_menu.run_follow_on_builders(config=config)

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

    if name == 'follow-on-builders':
      followers = orch_config.orchestrator.follow_on_builders
      followers.names.extend(
          ['chromeos/firmware/firmware-android-R148-16640.2.B-branch'])
      followers.await_completion = True
      followers.rev_bump = True

    # Add config for the dynamic child
    dynamic_child = builder_config_data.builder_configs.add()
    dynamic_child.id.name = 'dynamic-child'

    # Add the named child config only if not 'no-child' test
    if name not in ['no-child', 'bump-version', 'follow-on-builders']:
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
      'cq', api.post_check(post_process.DoesNotRun, 'set up orchestrator'),
      expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': test_builder
      })

  yield test(
      'staging-cq',
      api.post_check(post_process.DoesNotRun, 'set up orchestrator'),
      expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': f'staging-{test_builder}'
      }, bucket='staging')

  yield test(
      'cq-tagged', api.post_check(post_process.MustRun, 'set up orchestrator'),
      expected_properties={
          'manifest_branch': f'{test_base}-main',
          'child_verifier': test_builder
      }, branch=f'{test_base}-main')

  yield test(
      'failed-child',
      api.post_check(post_process.DoesNotRun, 'set up orchestrator'),
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
      'no-child', api.post_check(post_process.MustRun, 'set up orchestrator'),
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.bump version'), expected_properties={
                         'manifest_branch': f'{test_base}6.B',
                         'child_verifier': 'dynamic'
                     }, branch=f'{test_base}6.B')

  yield test(
      'bump-version', api.post_check(post_process.MustRun,
                                     'set up orchestrator'),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.bump version'), expected_properties={
                         'manifest_branch': f'{test_base}6.B',
                         'child_verifier': 'dynamic'
                     }, branch=f'{test_base}6.B', bucket='staging',
      input_properties={'$chromeos/orch_menu': {
          'bump_version': True
      }})

  yield test(
      'follow-on-builders',
      api.post_check(
          post_process.MustRun,
          'run follow on builders.run follow on builder chromeos/firmware/firmware-android-R148-16640.2.B-branch'
      ), api.post_process(post_process.DropExpectation), expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': test_builder
      })
