# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to enforce go/kernel-upstream-tracking-process"""

import re
from typing import Dict

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = {
    'step': 'recipe_engine/step',
    'tricium': 'recipe_engine/tricium',
    'depot_gerrit': 'depot_tools/gerrit',
    'gerrit': 'gerrit',
    'src_state': 'src_state',
    'test_util': 'test_util',
}


TECH_DEBT_MSG_TAG = 'This patch is not fully upstream. Please open a tracking bug here: go/cros-kernel-technical-debt-bug and add a label UPSTREAM-TASK=b:XXXX referencing it and add cros-kernel-upstream-debt-review@google.com as reviewer. A member of the review committee will review the CL. Thank you.'
TAG_MISSING_MSG = 'The subject of this patch does not include a valid tag. Please check: https://chromium.googlesource.com/chromiumos/docs/+/HEAD/kernel_development.md. If you\'d like to silence this warning for a work-in-progress change, prefix your subject with "WIP:" or "DO-NOT-SUBMIT:"'
BAD_TAG_MSG = 'Bad subject tag for patch touching ChromeOS specific files. Please check: https://chromium.googlesource.com/chromiumos/docs/+/HEAD/kernel_development.md'
TECH_DEBT_DUP_BUG_MSG = 'UPSTREAM-TASK bugs cannot be the same as those present in the BUG tag.'

TECH_DEBT_PROJECTS = {'chromiumos/third_party/kernel'}

TECH_DEBT_TAGS = ('FROMLIST:', 'BACKPORT: FROMLIST:', 'CHROMIUM:')
UPSTREAM_TAGS = ('FROMLIST:', 'UPSTREAM:', 'FROMGIT:', 'BACKPORT:')
OTHER_TAGS = (
    'CHROMIUM:',
    'WIP:',
    'TEST:',
    'TEST-ONLY:',
    'Revert',
    'Reland',
    'FIXUP:',
    'DO-NOT-SUBMIT',
)
CHROMEOS_FILES = (
    'chromeos/',
    'OWNERS',
    'PRESUBMIT.cfg',
    'unblocked_terms.txt',
    '.cop/',
)


def _chromeos_change(file_infos):
  for f in file_infos:
    if f.startswith(CHROMEOS_FILES):
      return True
  return False


def _chromeos_only_change(file_infos):
  for f in file_infos:
    if not f.startswith(CHROMEOS_FILES):
      return False
  return True


def RunSteps(api: RecipeApi):
  gerrit_changes = api.src_state.gerrit_changes

  with api.step.nest('validate inputs') as presentation:
    # If there are no gerrit_changes, we're done.
    if len(gerrit_changes) == 0:
      presentation.step_text = 'No changes given: Build is POINTLESS.'
      return
    # If there is more than one gerrit_change, this recipe was invoked
    # incorrectly, as the Tricium service only passes singletons.
    if len(gerrit_changes) != 1:
      presentation.status = api.step.FAILURE
      presentation.step_text = 'More than one change given.'
      return

  with api.step.nest('known project') as presentation:
    if gerrit_changes[0].project not in TECH_DEBT_PROJECTS:
      presentation.step_text = 'Unknown project'
      return

  with api.step.nest('fetch patch set') as presentation:
    patch_set = api.m.gerrit.fetch_patch_set_from_change(
        gerrit_changes[0], include_commit_info=True, include_files=True)

  with api.step.nest('check branch') as presentation:
    branch = patch_set.branch
    if not branch.startswith(('chromeos-', 'chameleon-')):
      presentation.step_text = 'Branch not reviewed'
      return

  with api.step.nest('missing tag') as presentation:
    subject = patch_set.subject
    if not subject.startswith(UPSTREAM_TAGS + OTHER_TAGS):
      api.tricium.add_comment('Tag Checker', TAG_MISSING_MSG, '/COMMIT_MSG')
      api.tricium.write_comments()
      return

  with api.step.nest('invalid tag') as presentation:
    if subject.startswith(UPSTREAM_TAGS) and _chromeos_change(
        patch_set.file_infos):
      api.tricium.add_comment('Tag Checker', BAD_TAG_MSG, '/COMMIT_MSG')
      api.tricium.write_comments()
      return

  with api.step.nest('check if tech debt') as presentation:
    if not subject.startswith(TECH_DEBT_TAGS):
      presentation.step_text = 'Patch set does not show a technical debt.'
      return
    if _chromeos_only_change(patch_set.file_infos):
      presentation.step_text = 'Chrome-only patch, no technical debt.'
      return

  with api.step.nest('check tag') as presentation:
    message = patch_set.commit_info.get('message')
    buganizer = r'b:[0-9]{7,}'
    tag_line = r'\nUPSTREAM-TASK=%s([, ]+%s)*[ \t]*\n' % (buganizer, buganizer)
    if not re.search(tag_line, message):
      api.tricium.add_comment('Technical debt', TECH_DEBT_MSG_TAG,
                              '/COMMIT_MSG')
      presentation.step_text = 'Tag missing, add comment. CL not ready for proper review.'
      api.tricium.write_comments()
      return
    presentation.step_text = 'Tag already added.'

  with api.step.nest('check duplicated bugid') as presentation:
    commit_message = patch_set.commit_info.get('message')
    bug_id = r'b:[0-9]{7,}'
    bugs_ids = rf'({bug_id}(?:[, ]+{bug_id})*)'

    bug_tag = rf'\nBUG={bugs_ids}+'
    upstream_task_tag = rf'\nUPSTREAM-TASK={bugs_ids}+'

    bug_line = re.findall(bug_tag, commit_message)
    upstream_task_line = re.findall(upstream_task_tag, commit_message)

    bugs = set()
    for b in bug_line:
      bugs |= set(re.findall(bug_id, b))

    upstream_tasks = set()
    for b in upstream_task_line:
      upstream_tasks |= set(re.findall(bug_id, b))

    if set(bugs) & set(upstream_tasks):
      presentation.status = api.step.FAILURE
      api.tricium.add_comment('Technical debt', TECH_DEBT_DUP_BUG_MSG,
                              '/COMMIT_MSG')
      presentation.step_text = 'Tag missing, add comment. CL not ready for proper review.'
      api.tricium.write_comments()
      return


def GenTests(api: RecipeTestApi):

  def test_builder(**kwargs) -> TestData:
    """Generate a test build."""
    kwargs.setdefault('builder', 'infra-presubmit')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  def gen_patch_sets(message: str, filename: str,
                     branch: str = 'chromeos-5.4') -> Dict[int, Dict]:
    return {
        1: {
            'subject': message.splitlines()[0],
            'branch': branch,
            'revision_info': {
                'commit': {
                    'message': message,
                },
                '_number': 1,
                'files': {
                    filename: {
                        'lines_inserted': 1,
                        'size': 42,
                        'size_delta': 3
                    },
                },
            },
        },
    }

  yield api.test('basic', api.post_process(post_process.DropExpectation))

  yield api.test('no-changes-given', test_builder(revision=None, cq=False),
                 api.post_check(post_process.StepSuccess, 'validate inputs'),
                 api.post_check(post_process.DoesNotRun, 'known project'),
                 api.post_process(post_process.DropExpectation))

  two_changes = [
      GerritChange(change=1, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=1),
      GerritChange(change=2, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=2),
  ]
  yield api.test('too-many-changes', test_builder(gerrit_changes=two_changes),
                 api.post_check(post_process.StepFailure, 'validate inputs'),
                 api.post_process(post_process.DropExpectation))

  changes = [
      GerritChange(change=1, project='chromiumos/infra/recipes',
                   host='chromium-review.googlesource.com', patchset=1),
  ]
  yield api.test('unknown project', test_builder(gerrit_changes=changes),
                 api.post_check(post_process.StepSuccess, 'known project'),
                 api.post_check(post_process.DoesNotRun, 'check branch'),
                 api.post_process(post_process.DropExpectation))

  changes = [
      GerritChange(change=1, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=1),
  ]

  yield api.test(
      'unchecked branch', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('UPSTREAM: Land Kcam', 'Makefile', branch='kcam')),
      api.post_check(post_process.StepSuccess, 'check branch'),
      api.post_check(post_process.DoesNotRun, 'missing tag'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'unknown tag', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('BIGPARTY: Land Kcam', 'Makefile')),
      api.post_check(post_process.StepSuccess, 'missing tag'),
      api.post_check(post_process.DoesNotRun, 'invalid tag'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'invalid tag', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('UPSTREAM: Land Kcam', '.cop/build.yaml')),
      api.post_check(post_process.StepSuccess, 'invalid tag'),
      api.post_check(post_process.DoesNotRun, 'check if tech debt'),
      api.post_process(post_process.DropExpectation))

  for idx, subject in enumerate(('FROMGIT: drm_repo', 'UPSTREAM: Land Kcam',
                                 'BACKPORT: FROMGIT: Fix all gpu crashes',
                                 'BACKPORT: Linus fix to the big lock')):
    yield api.test(
        'upstream %d' % idx, test_builder(gerrit_changes=changes),
        api.gerrit.set_gerrit_fetch_changes_response(
            'fetch patch set', changes, gen_patch_sets(subject, 'Makefile')),
        api.post_check(post_process.StepSuccess, 'check if tech debt'),
        api.post_check(post_process.DoesNotRun, 'check tag'),
        api.post_process(post_process.DropExpectation))

  yield api.test(
      'chromium', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: add config', 'chromeos/configs/hi')),
      api.post_check(post_process.StepSuccess, 'check if tech debt'),
      api.post_check(post_process.DoesNotRun, 'check tag'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'downstream', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: IPU6 non Kcam', 'Makefile')),
      api.post_check(post_process.StepSuccess, 'check tag'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'downstream_with_tag_alias_already_added',
      test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: IPU6 non Kcam\n\nUPSTREAM-TASK=b:1234567\n',
                         'Makefile')),
      api.post_check(post_process.StepSuccess, 'check tag'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'downstream_with_multitag_alias_already_added',
      test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets(
              'CHROMIUM: IPU6 non Kcam\n\nUPSTREAM-TASK=b:1234567, b:7777777\n',
              'Makefile')), api.post_check(post_process.StepSuccess,
                                           'check tag'),
      api.post_check(post_process.DoesNotRun, 'write comments'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'different_bug_id', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets(
              'CHROMIUM: IPU6 non Kcam\n\nDescription\nBUG=b:1234567\nUPSTREAM-TASK=b:1234568\n',
              'Makefile')),
      api.post_check(post_process.StepSuccess, 'check duplicated bugid'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'duplicated_bug_id', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets(
              'CHROMIUM: IPU6 non Kcam\n\nDescription\nBUG=b:1234567\nUPSTREAM-TASK=b:1234567\n',
              'Makefile')),
      api.post_check(post_process.StepFailure, 'check duplicated bugid'),
      api.post_process(post_process.DropExpectation))
