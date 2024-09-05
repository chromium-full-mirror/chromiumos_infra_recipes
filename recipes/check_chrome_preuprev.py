# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that checks Chrome uprev.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/time',
    'recipe_engine/step',
    'gerrit',
    'test_util',
]

FETCH_DESCRIPTION_INTERVAL_SEC = 300
FETCH_DESCRIPTION_TIMEOUT_SEC = 1800
UPREV_CL_TOPIC = 'chromeos-base/lacros-ash-atomic'

NO_CL_FOUND = RawResult(status=common_pb2.SUCCESS,
                        summary_markdown='No CL found.')
NOT_AN_UPREV_CL = RawResult(status=common_pb2.SUCCESS,
                            summary_markdown='Not Chrome uprev CL.')
NO_PRE_UPREV_TESTING_EXPECTED = RawResult(
    status=common_pb2.SUCCESS,
    summary_markdown='This Uprev CL does not expect any pre-uprev testing.')
PRE_UPREV_PASS = RawResult(status=common_pb2.SUCCESS,
                           summary_markdown='Pre-uprev testing passed.')
NO_PASSING_PRE_UPREV = RawResult(
    status=common_pb2.FAILURE,
    summary_markdown=f'No passing pre-uprev testing after {FETCH_DESCRIPTION_TIMEOUT_SEC} seconds'
)


def RunSteps(api: RecipeApi):
  cl = api.buildbucket.build.input.gerrit_changes
  if not cl:
    return NO_CL_FOUND
  cl = cl[0]
  patch_sets = api.gerrit.fetch_patch_sets([cl])
  if patch_sets[0].topic != UPREV_CL_TOPIC:
    return NOT_AN_UPREV_CL
  with api.step.nest('Fetch pre-uprev testing result'):
    for _ in range(0, FETCH_DESCRIPTION_TIMEOUT_SEC,
                   FETCH_DESCRIPTION_INTERVAL_SEC):
      desc = api.gerrit.get_change_description(cl)
      if not 'Pre-Uprev Testing: ' in desc:
        return NO_PRE_UPREV_TESTING_EXPECTED
      if 'Pre-Uprev Testing: Not Tested' in desc:
        api.time.sleep(FETCH_DESCRIPTION_INTERVAL_SEC, with_step=True)
        continue
      # Pre-Uprev Passing
      if 'Pre-Uprev Testing: PASSED' in desc:
        return PRE_UPREV_PASS
  return NO_PASSING_PRE_UPREV


def GenTests(api: RecipeTestApi):

  GERRIT_HOST = 'chromium.googlesource.com'
  PROJECT = 'chromiumos/overlays/chromiumos-overlay'
  CHANGE_NUMBER = 123456
  PATCHSET = 7

  def try_build(messages, topic=UPREV_CL_TOPIC):
    build = api.buildbucket.try_build(
        builder='chrome-uprev-cq', gerrit_changes=[
            common_pb2.GerritChange(
                host=GERRIT_HOST,
                project=PROJECT,
                change=CHANGE_NUMBER,
                patchset=PATCHSET,
            )
        ])

    change = {
        '_number': CHANGE_NUMBER,
        'topic': topic,
        'change_id': str(CHANGE_NUMBER),
        'status': 'NEW',
    }
    build += api.gerrit.set_gerrit_fetch_changes_response(
        '', [
            common_pb2.GerritChange(host=GERRIT_HOST, project=PROJECT,
                                    change=CHANGE_NUMBER, patchset=PATCHSET)
        ], {CHANGE_NUMBER: change})

    cnt = 1
    for idx, message in enumerate(messages):
      change = {
          '_number': CHANGE_NUMBER,
          'topic': topic,
          'change_id': str(CHANGE_NUMBER),
          'status': 'NEW',
          'revision_info': {
              '_number': PATCHSET + idx,
              'commit': {
                  'message': message[0],
              }
          }
      }
      for _ in range(message[1]):
        step_name = 'Fetch pre-uprev testing result.'
        if cnt == 1:
          step_name += f'get CL {CHANGE_NUMBER} description'
        else:
          step_name += f'get CL {CHANGE_NUMBER} description ({cnt})'
        build += api.gerrit.set_gerrit_fetch_changes_response(
            step_name, [
                common_pb2.GerritChange(host=GERRIT_HOST, project=PROJECT,
                                        change=CHANGE_NUMBER, patchset=PATCHSET)
            ], {CHANGE_NUMBER: change})
        cnt += 1
    return build

  def try_build_once(message, **kwargs):
    return try_build([(message, 1)], **kwargs)

  yield api.test(
      'success',
      try_build([
          # First 2 fetches are not tested (patchset unchagned).
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           2),
          # The next fetch returns a new patchset with PASSED result.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: PASSED go/bbid/123456\n',
           1)
      ]),
      api.post_check(post_process.SummaryMarkdown,
                     PRE_UPREV_PASS.summary_markdown),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'not-cq-build', api.buildbucket.ci_build(builder='chrome-uprev-snapshot'),
      api.post_check(post_process.DoesNotRun, 'Fetch pre-uprev testing result'),
      api.post_check(post_process.SummaryMarkdown,
                     NO_CL_FOUND.summary_markdown), cq=True, status='SUCCESS')

  yield api.test(
      'cq-build-no-cl',
      api.buildbucket.try_build(builder='chrome-uprev-cq', gerrit_changes=[]),
      api.post_check(post_process.DoesNotRun, 'Fetch pre-uprev testing result'),
      api.post_check(post_process.SummaryMarkdown,
                     NO_CL_FOUND.summary_markdown), cq=True, status='SUCCESS')

  yield api.test(
      'not-chrome-uprev-cl',
      try_build([], topic=''),
      api.post_check(post_process.DoesNotRun, 'Fetch pre-uprev testing result'),
      api.post_check(post_process.SummaryMarkdown,
                     NOT_AN_UPREV_CL.summary_markdown),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'not-expecting-preuprev',
      try_build_once('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
      api.post_check(post_process.SummaryMarkdown,
                     NO_PRE_UPREV_TESTING_EXPECTED.summary_markdown),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'no-preuprev-results',
      try_build([
          # Infinite fetches returns Not Tested message
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           int(FETCH_DESCRIPTION_TIMEOUT_SEC / FETCH_DESCRIPTION_INTERVAL_SEC)),
      ]),
      api.post_check(post_process.SummaryMarkdown,
                     NO_PASSING_PRE_UPREV.summary_markdown),
      cq=True,
      status='FAILURE',
  )
