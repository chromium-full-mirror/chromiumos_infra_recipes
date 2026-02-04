# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures."""

from typing import Generator

from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import Trinary
from recipe_engine.post_process import PropertyEquals
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'bot_cost',
    'cros_infra_config',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'orch_menu',
    'src_state',
    'test_util',
]


def RunSteps(api: RecipeApi) -> result_pb2.RawResult:
  with api.bot_cost.build_cost_context():
    api.cros_source.configure_builder()
    branch = api.src_state.gitiles_commit.ref
    branch = api.git.extract_branch(branch, branch)
    api.easy.set_properties_step(manifest_branch=branch)

    # Turn the branch name into the cq builder name.
    builder = '{}{}'.format(
        'staging-' if api.cros_infra_config.is_staging else '',
        branch.replace('.B', '-cq'))
    api.easy.set_properties_step(child_verifier=builder)
    child_config = api.cros_infra_config.get_builder_config(
        builder, missing_ok=True)
    if child_config:
      api.orch_menu.schedule_wait_build(builder, await_completion=True,
                                        check_failures=True,
                                        step_name='launch child')
    else:
      with api.step.nest('launch child') as pres:
        pres.step_text = 'Builder {} is not configured'.format(builder)

    return api.orch_menu.create_recipe_result()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  test_base = 'firmware-board-5555'
  test_branch = '{}.B'.format(test_base)
  test_builder = '{}-cq'.format(test_base)

  def test(name, *args, **kwargs):
    status = kwargs.pop('status', 'SUCCESS')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('critical', Trinary.YES)
    kwargs.setdefault('revision', None)
    kwargs.setdefault('builder', 'firmware-cq-orchestrator')
    branch = kwargs.pop('branch', test_branch)
    orch = api.test_util.test_orchestrator(**kwargs)
    changes = orch.message.input.gerrit_changes

    values = {x.change: {'branch': branch} for x in changes}
    args += (orch.build,
             api.gerrit.set_gerrit_fetch_changes_response(
                 'configure builder', changes, values))
    return api.test(name, *args, status=status)

  yield test('cq', api.post_check(PropertyEquals, 'manifest_branch',
                                  test_branch),
             api.post_check(PropertyEquals, 'child_verifier', test_builder))

  yield test(
      'staging-cq',
      api.post_check(PropertyEquals, 'manifest_branch', test_branch),
      api.post_check(PropertyEquals, 'child_verifier',
                     'staging-{}'.format(test_builder)),
      builder='staging-firmware-cq-orchestrator', bucket='staging')

  yield test(
      'cq-tagged',
      api.post_check(PropertyEquals, 'manifest_branch',
                     '{}'.format(test_branch)),
      api.post_check(PropertyEquals, 'child_verifier', test_builder),
      branch='{}-main'.format(test_branch))

  yield test(
      'failed-child',
      api.buildbucket.simulated_collect_output([
          api.test_util.test_build(builder=test_builder, status='FAILURE',
                                   critical='YES').message
      ], step_name='launch child.collect'),
      status='FAILURE',
  )

  yield test('no-child', branch='firmware-board-5556.B')
