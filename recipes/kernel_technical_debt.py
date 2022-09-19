# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to enforce go/kernel-upstream-tracking-process"""

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process
import re

DEPS = {
    'step': 'recipe_engine/step',
    'tricium': 'recipe_engine/tricium',
    'depot_gerrit': 'depot_tools/gerrit',
    'gerrit': 'gerrit',
    'src_state': 'src_state',
    'test_util': 'test_util',
}

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

TECH_DEBT_ALIAS = 'cros-kernel-upstream-debt-review@google.com'
TECH_DEBT_MSG = 'This patch is not fully upstream. Please open a tracking bug here: go/cros-kernel-technical-debt-bug and add a label UPSTREAM-TASK=b:XXXX referencing it. A member of the review committee will review the CL. Thank you'
TECH_DEBT_PROJECTS = {'chromiumos/third_party/kernel'}


def RunSteps(api):
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

  with api.step.nest('check if tech debt') as presentation:
    subject = patch_set.subject
    if subject.startswith(
        ('UPSTREAM:', 'FROMGIT:', 'WIP:', 'TEST:', 'TEST-ONLY:', 'BACKPORT:',
         'Revert')) and not subject.startswith('BACKPORT: FROMLIST'):
      presentation.step_text = 'Patch set does not show a technical debt.'
      return
    for f in patch_set.file_infos:
      if not f.startswith(
          ('chromeos/', 'OWNERS', 'PRESUBMIT.cfg', 'unblocked_terms.txt')):
        break
    else:
      presentation.step_text = 'Chrome-only patch, no technical debt.'
      return

  with api.step.nest('check tag') as presentation:
    message = patch_set.commit_info.get('message')
    if not re.search(r'\nUPSTREAM-TASK=b:\d+[ \t]*\n', message):
      api.tricium.add_comment('Technical debt', TECH_DEBT_MSG, '/COMMIT_MSG')
      api.tricium.write_comments()
      presentation.step_text = 'Tag missing, add comment. CL not ready for proper review.'

  with api.step.nest('get reviewers') as presentation:
    reviewers = api.depot_gerrit.call_raw_api(
        'https://' + patch_set.host,
        '/changes/%s/reviewers/' % patch_set.change_id, method='GET',
        accept_statuses=[200], name='raw_get_reviewers')
    for reviewer in reviewers:
      if 'email' in reviewer and reviewer['email'] == TECH_DEBT_ALIAS:
        presentation.step_text = 'Tech debt alias found as reviewer.'
        return
    presentation.step_text = 'Tech debt alias not found as reviewer.'

  with api.step.nest('add reviewer') as presentation:
    body = {'reviewer': TECH_DEBT_ALIAS}
    api.depot_gerrit.call_raw_api(
        'https://' + patch_set.host,
        '/changes/%s/reviewers/' % patch_set.change_id, method='POST',
        body=body, accept_statuses=[200], name='raw_add_reviewer')
    presentation.step_text = 'Add tech debt alias as reviewer.'


def GenTests(api):

  def test_builder(**kwargs):
    '''Generate a test build.'''
    kwargs.setdefault('builder', 'infra-presubmit')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  def gen_patch_sets(message, filename):
    return {
        1: {
            'subject': message.splitlines()[0],
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

  yield api.test('basic', api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))

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
                 api.post_check(post_process.DoesNotRun, 'check tag'),
                 api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))

  changes = [
      GerritChange(change=1, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=1),
  ]
  yield api.test(
      'upstream', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('UPSTREAM: Land Kcam', 'Makefile')),
      api.post_check(post_process.StepSuccess, 'check if tech debt'),
      api.post_check(post_process.DoesNotRun, 'check tag'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'chromium', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: add config', 'chromeos/configs/hi')),
      api.post_check(post_process.StepSuccess, 'check if tech debt'),
      api.post_check(post_process.DoesNotRun, 'check tag'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'downstream', test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: IPU6 non Kcam', 'Makefile')) +
      api.step_data('get reviewers.gerrit raw_get_reviewers',
                    api.depot_gerrit.m.json.output([])),
      api.post_check(post_process.StepSuccess, 'add reviewer'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'downstream_with_tag_alias_already_added',
      test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: IPU6 non Kcam\n\nUPSTREAM-TASK=b:123456\n',
                         'Makefile')) +
      api.step_data(
          'get reviewers.gerrit raw_get_reviewers',
          api.depot_gerrit.m.json.output([{
              'email': 'cros-kernel-upstream-debt-review@google.com'
          }])), api.post_check(post_process.StepSuccess, 'get reviewers'),
      api.post_check(post_process.DoesNotRun, 'add reviewer'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'downstream_with_tag_alias_not_added',
      test_builder(gerrit_changes=changes),
      api.gerrit.set_gerrit_fetch_changes_response(
          'fetch patch set', changes,
          gen_patch_sets('CHROMIUM: IPU6 non Kcam\n\nUPSTREAM-TASK=b:123456\n',
                         'Makefile')) +
      api.step_data('get reviewers.gerrit raw_get_reviewers',
                    api.depot_gerrit.m.json.output([])),
      api.post_check(post_process.StepSuccess, 'add reviewer'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
