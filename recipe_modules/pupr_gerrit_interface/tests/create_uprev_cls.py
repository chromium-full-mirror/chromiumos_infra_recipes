# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that create_uprev_cls() runs the expected process."""

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine import result
from PB.recipe_modules.chromeos.pupr_gerrit_interface.tests.tests import \
  CreateUprevClsProperties
from PB.recipes.chromeos.generator import ABANDON
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import CR_REJECT
from PB.recipes.chromeos.generator import DRY_RUN
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api


DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'gerrit',
    'pupr_gerrit_interface',
    'src_state',
]

PROPERTIES = CreateUprevClsProperties


def RunSteps(api: recipe_api.RecipeApi, properties: CreateUprevClsProperties):
  branch_policy = BranchPolicy(
      pattern='.*',
      repl='',
      reviewers=[Reviewer(email='a@example.com')],
      no_existing_cls_policy=properties.send_to_cq_policy,
      existing_cls_policy=properties.send_to_cq_policy,
      cr_policy=properties.cr_policy,
      max_concurrent_cq_runs=properties.max_concurrent_cq_runs,
  )
  if properties.projects == 0:
    projects = [
        ProjectInfo(name='chrome-project', path='[START_DIR]/chrome/src',
                    remote='cros', branch=api.src_state.workspace_path,
                    rrev=api.src_state.workspace_path)
    ]
  else:
    projects = [
        ProjectInfo(name=f'galaxy{i}', path=f'project{i}', remote='cros',
                    branch=api.src_state.workspace_path,
                    rrev=api.src_state.workspace_path)
        for i in range(1, properties.projects + 1)
    ]

  summary = api.pupr_gerrit_interface.create_uprev_cls(
      projects, list(properties.open_changes), branch_policy, 'a topic')
  return result.RawResult(status=common.SUCCESS, summary_markdown=summary)


OPEN_CHANGES_LIST = [
    common.GerritChange(host='host-review.googlesource.com', change=1,
                        project='project', patchset=1)
]
FETCH_RESPONSE_RUNNING = {
    1: {
        '_number': 1,
        'project': 'project',
        'patch_set': 1,
        'branch': 'main',
        'created': '2023-01-09 13:11:20.000000000',
        'labels': {
            'Commit-Queue': {
                'all': [{
                    'value': 1
                }]
            }
        },
        'messages': [],
    }
}


def GenTests(api: recipe_test_api.RecipeTestApi):

  def check_label(cl_num: int, label: str, vote: int):
    """Check that the test case gave a certain label vote on the given CL.

    Args:
      cl_num: The Gerrit CL number to check.
      label: The name of the label, such as Commit-Queue.
      vote: The number that should be voted for that label.
    """
    return api.post_check(post_process.LogContains,
                          f'update CL labels.set labels on CL {cl_num}',
                          'labels', [f'"{label}": {vote}'])

  def check_no_label(cl_num: int, label: str):
    """Check that the test case did not vote on the given label for the CL.

    Args:
      cl_num: The Gerrit CL number to check.
      label: The name of the label, such as Commit-Queue.
    """
    return api.post_check(post_process.LogDoesNotContain,
                          f'update CL labels.set labels on CL {cl_num}',
                          'labels', [f'"{label}"'])

  yield api.test(
      'submit', api.properties(send_to_cq_policy=SUBMIT, projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      check_label(123, 'Bot-Commit', 1), check_no_label(123, 'Commit-Queue'),
      api.post_check(post_process.StepSuccess, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'dry-run', api.properties(send_to_cq_policy=DRY_RUN, projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      check_label(123, 'Bot-Commit', 1), check_label(123, 'Commit-Queue', 1),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'dry-run-staging', api.properties(send_to_cq_policy=DRY_RUN, projects=1),
      api.buildbucket.generic_build(project='chromeos', bucket='staging',
                                    builder='staging-my-cool-pupr-generator'),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      check_no_label(123, 'Bot-Commit'), check_label(123, 'Commit-Queue', 1),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'dry-run-cr-reject',
      api.properties(send_to_cq_policy=DRY_RUN, cr_policy=CR_REJECT,
                     projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      check_label(123, 'Bot-Commit', 1), check_label(123, 'Commit-Queue', 1),
      check_label(123, 'Code-Review', -2),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'full-run',
      api.properties(send_to_cq_policy=FULL_RUN, projects=2, existing_cls=True),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project2',
          'https://host-review.googlesource.com/c/project/+/456'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      check_label(123, 'Bot-Commit', 1), check_label(123, 'Commit-Queue', 2),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 456'),
      check_label(456, 'Bot-Commit', 1), check_label(456, 'Commit-Queue', 2),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'abandon', api.properties(send_to_cq_policy=ABANDON, projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.DoesNotRun,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_check(post_process.MustRun, 'update CL labels.abandon CL 123'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'summary',
      api.properties(send_to_cq_policy=FULL_RUN, projects=2, existing_cls=True),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://chromium-review.googlesource.com/c/project/+/123'),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project2',
          'https://chrome-internal-review.googlesource.com/c/project/+/456'),
      api.path.exists(api.src_state.workspace_path),
      api.post_process(
          post_process.SummaryMarkdown,
          'created [chromium:123](https://crrev.com/c/123) '
          '[chrome-internal:456](https://crrev.com/i/456)'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'non-repo-project', api.properties(send_to_cq_policy=DRY_RUN, projects=0),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for [START_DIR]/chrome/src',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      api.post_process(post_process.DropExpectation))

  open_changes_list = [
      common.GerritChange(host='host-review.googlesource.com', change=1,
                          project='project', patchset=1)
  ]
  fetch_response_running = {
      1: {
          '_number': 1,
          'project': 'project',
          'patch_set': 1,
          'branch': 'main',
          'created': '2023-01-09 13:11:20.000000000',
          'labels': {
              'Commit-Queue': {
                  'all': [{
                      'value': 1
                  }]
              }
          },
          'messages': [],
      }
  }

  yield api.test(
      'limit-exceeded',
      api.properties(
          CreateUprevClsProperties(send_to_cq_policy=DRY_RUN, projects=1,
                                   max_concurrent_cq_runs=1,
                                   open_changes=open_changes_list)),
      api.gerrit.set_gerrit_fetch_changes_response('check concurrent CQ runs',
                                                   open_changes_list,
                                                   fetch_response_running),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      check_label(123, 'Commit-Queue', 0),
      api.post_check(post_process.LogContains,
                     'update CL labels.add comment on CL 123', 'comment text',
                     ['limit of 1 has been reached']),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'limit-not-exceeded',
      api.properties(
          CreateUprevClsProperties(send_to_cq_policy=DRY_RUN, projects=1,
                                   max_concurrent_cq_runs=2,
                                   open_changes=open_changes_list)),
      api.gerrit.set_gerrit_fetch_changes_response('check concurrent CQ runs',
                                                   open_changes_list,
                                                   fetch_response_running),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      check_label(123, 'Commit-Queue', 1),
      api.post_check(post_process.LogContains,
                     'update CL labels.add comment on CL 123', 'comment text',
                     ['Send-to-cq policy for this case is DRY_RUN']),
      api.post_check(post_process.LogDoesNotContain,
                     'update CL labels.add comment on CL 123', 'comment text',
                     ['limit of 2 has been reached']),
      api.post_process(post_process.DropExpectation))
