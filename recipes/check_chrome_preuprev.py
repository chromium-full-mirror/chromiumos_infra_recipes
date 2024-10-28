# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that checks Chrome uprev.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from collections import namedtuple
import json
import re
import traceback

from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.chromeos.pupr_local_uprev.api import UPREV_VERSION_LABEL

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/resultdb',
    'recipe_engine/time',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'gerrit',
    'test_util',
    'git_footers',
]

FETCH_DESCRIPTION_INTERVAL_SEC = 60
FETCH_DESCRIPTION_TIMEOUT_SEC = 600  # 10 minutes
WAIT_PREUPREV_TIMEOUT_SEC = 3600 * 6  # 6 hour
UPREV_CL_TOPIC = 'chromeos-base/lacros-ash-atomic'
INVOCATION_PREFIX = 'invocations/'

NO_CL_FOUND_SUMMARY = 'No CL found.'
NOT_AN_UPREV_CL_SUMMARY = 'Not Chrome uprev CL.'
NO_PRE_UPREV_TESTING_EXPECTED_SUMMARY = 'This Uprev CL does not expect any pre-uprev testing.'
PRE_UPREV_PASS_SUMMARY = 'Pre-uprev testing passed.'
NO_PRE_UPREV_FOUND_SUMMARY = (
    # Error notice
    f'No pre-uprev testing identified after {FETCH_DESCRIPTION_TIMEOUT_SEC} seconds.\n\n'
    # Possible action items
    'Please wait for next uprev or evaulate very carefully if you want to skip pre-uprev testing by chump the CL.'
)
NO_PASSING_PRE_UPREV_FOUND_SUMMARY = (
    # Error notice
    f'No passing pre-uprev testing after {WAIT_PREUPREV_TIMEOUT_SEC} seconds.\n\n'
    # Possible action items
    'Please wait for next uprev or evaulate very carefully if you want to skip pre-uprev testing by chump the CL.'
)
FAILED_PRE_UPREVS_SUMMARY_TEMPLATE = (
    # Error notice
    'Pre-uprev testing not passed, details:\n\n{builder.summary_markdown}\n\n'
    # Possible action items
    'Please check the test failures, fix the failures (land a fix or revert culprit on Chromium) '
    'and wait for next pre-uprev. You can override by chump the CL but it is discouraged.'
)

NO_CL_FOUND = RawResult(status=common_pb2.SUCCESS,
                        summary_markdown=NO_CL_FOUND_SUMMARY)
NOT_AN_UPREV_CL = RawResult(status=common_pb2.SUCCESS,
                            summary_markdown=NOT_AN_UPREV_CL_SUMMARY)
NO_PRE_UPREV_TESTING_EXPECTED = RawResult(
    status=common_pb2.SUCCESS,
    summary_markdown=NO_PRE_UPREV_TESTING_EXPECTED_SUMMARY)
PRE_UPREV_PASS = RawResult(status=common_pb2.SUCCESS,
                           summary_markdown=PRE_UPREV_PASS_SUMMARY)
NO_PRE_UPREV_FOUND = RawResult(status=common_pb2.FAILURE,
                               summary_markdown=NO_PRE_UPREV_FOUND_SUMMARY)
NO_PASSING_PRE_UPREV_FOUND = RawResult(
    status=common_pb2.FAILURE,
    summary_markdown=NO_PASSING_PRE_UPREV_FOUND_SUMMARY)


PRE_UPREV_STATUS_BBID_EXTRACTOR = re.compile(
    r'[A-Za-z]* https://ci.chromium.org/ui/b/(\d+)')

BUILD_FIELDS_TO_RETRIEVE = [
    'builder',
    'cancellation_markdown',
    'id',
    'input',
    'output',
    'status',
    'steps',
    'summary_markdown',
    'infra.resultdb',
]


def GetClPreUprevTesting(api: RecipeTestApi, cl: common_pb2.GerritChange):
  # We're not able to use api.git_footers.from_gerrit_change because the
  # initial placeholder is part of the commit message added by pupr, which
  # cannot be put as footer. so parse line-by-line.
  label = 'Pre-Uprev Testing: '
  desc = api.gerrit.get_change_description(cl)
  for line in desc.splitlines():
    if not line.startswith(label):
      continue
    line = line[len(label):].strip()
    return line
  return None


def PreUprevTestPassed(desc: str):
  return desc.startswith('PASSED')


def GetPreUprevId(api, desc: str):
  m = PRE_UPREV_STATUS_BBID_EXTRACTOR.match(desc)
  if m:
    with api.step.nest('Extract pre-uprev bbid') as step:
      step.step_summary_text = m.group(1)
      return int(m.group(1))
  return None


WantedBuildConfig = namedtuple('WantedBuildConfig', ['oneof'])

WANTED_BUILDERS = {
    'betty':
        WantedBuildConfig(oneof=['chromeos-betty-chrome-preuprev']),
    'brya':
        WantedBuildConfig(oneof=[
            'chromeos-brya-chrome-preuprev',
            'chromeos-brya-chrome-preuprev-skylab'
        ]),
    'jacuzzi':
        WantedBuildConfig(oneof=['chromeos-jacuzzi-chrome-preuprev']),
    'linux':
        WantedBuildConfig(oneof=['linux-chromeos-chrome-preuprev']),
    'volteer':
        WantedBuildConfig(oneof=['chromeos-volteer-chrome-preuprev']),
}


def PreUprevBuilders(api: RecipeApi, builds: [build_pb2.Build]):
  with api.step.nest('filtering for useful builders'):  # pragma: nocover
    # TODO(fqj): different test cases to be added once the search experiments
    # prove working.
    fulfilled_builders = {}

    for k, conf in WANTED_BUILDERS.items():
      options = conf.oneof
      for b in builds:
        if b.builder.builder in options:
          fulfilled_builders[k] = b
          with api.step.nest(f'Found {b.builder.builder}') as step:
            step.step_summary_text = f'[bbid/{b.id}](go/bbid/{b.id})'
          break

    missing = False
    for k, conf in WANTED_BUILDERS.items():
      if k not in fulfilled_builders:
        missing = True
        with api.step.nest(f'Missing {k}') as step:
          step.status = api.step.FAILURE
          step.step_summary_text = f'Want one of {conf.oneof}'
    if missing:
      return None

    return fulfilled_builders.values()


def RunSteps(api: RecipeApi):
  cl = api.buildbucket.build.input.gerrit_changes
  if not cl:
    return NO_CL_FOUND
  cl = cl[0]
  cl.patchset = 0
  patch_sets = api.gerrit.fetch_patch_sets([cl])
  if patch_sets[0].topic != UPREV_CL_TOPIC:
    return NOT_AN_UPREV_CL
  with api.step.nest('Search Chrome builders matching buildset') as step:
    try:
      pupr_version = api.git_footers.from_gerrit_change(cl,
                                                        UPREV_VERSION_LABEL)[0]
      with api.step.nest('decoding pupr version') as decode_step:
        decode_step.step_summary_text = pupr_version
        chrome_commit = json.loads(pupr_version)[0]['revision']
      builds = api.buildbucket.search(
          builds_service_pb2.BuildPredicate(
              builder={
                  'project': 'chrome',
                  'bucket': 'ci',
              }, tags=api.buildbucket.tags(
                  buildset=f'commit/gitiles/chromium.googlesource.com/chromium/src/+/{chrome_commit}'
              )),
          fields=BUILD_FIELDS_TO_RETRIEVE,
      )
      preuprevs = PreUprevBuilders(api, builds)
      if preuprevs is None:
        # We should return failure here because some necessary builders are
        # missing.  But we don't do it now because we still want to use
        # older/stable logic to determine if chrome-uprev-cq should pass or
        # not.
        pass
    except Exception:  # pragma: nocover # pylint: disable=broad-except
      # Log all details of exception but do not interrupt remaining logic of
      # chrome-uprev-cq.
      e = traceback.format_exc()
      step.step_text = f'Failed: {e}'
      step.status = api.step.FAILURE
  with api.step.nest('Fetch pre-uprev testing result'):
    bbid = None
    for _ in range(0, FETCH_DESCRIPTION_TIMEOUT_SEC,
                   FETCH_DESCRIPTION_INTERVAL_SEC):
      detail = GetClPreUprevTesting(api, cl)
      if not detail:
        return NO_PRE_UPREV_TESTING_EXPECTED
      if detail == 'Not Tested':
        api.time.sleep(FETCH_DESCRIPTION_INTERVAL_SEC, with_step=True)
        continue
      if PreUprevTestPassed(detail):
        return PRE_UPREV_PASS
      bbid = GetPreUprevId(api, detail)
      if bbid:
        break
    if not bbid:
      return NO_PRE_UPREV_FOUND
    builds = api.buildbucket.collect_builds([bbid],
                                            fields=BUILD_FIELDS_TO_RETRIEVE,
                                            timeout=WAIT_PREUPREV_TIMEOUT_SEC)
    builders = list(builds.values())
    with api.step.nest('including pre-uprev builder results') as step:
      invocations = [
          i.infra.resultdb.invocation
          for i in builders
          if i.infra.resultdb.invocation
      ]
      step.step_summary_text = '\n'.join(invocations)
      for inv in invocations:
        assert inv.startswith(INVOCATION_PREFIX)
      api.resultdb.include_invocations(
          [inv[len(INVOCATION_PREFIX):] for inv in invocations],
          'include invocations from pre-uprev builders')
    if PreUprevTestPassed(GetClPreUprevTesting(api, cl)):
      return PRE_UPREV_PASS
    if builders:
      return RawResult(
          status=common_pb2.FAILURE,
          summary_markdown=FAILED_PRE_UPREVS_SUMMARY_TEMPLATE.format(
              builder=builders[0]),
      )
    return NO_PASSING_PRE_UPREV_FOUND


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

    build += api.context.luci_context(
        resultdb=sections_pb2.ResultDB(
            current_invocation=sections_pb2.ResultDBInvocation(
                name='invocations/inv-9999',
                update_token='token',
            ),
            hostname='rdbhost',
        ))

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

      if idx == 0:
        build += api.gerrit.set_gerrit_fetch_changes_response(
            f'Search Chrome builders matching buildset.get CL {CHANGE_NUMBER} description',
            [
                common_pb2.GerritChange(host=GERRIT_HOST, project=PROJECT,
                                        change=CHANGE_NUMBER, patchset=PATCHSET)
            ], {CHANGE_NUMBER: change})
        build += api.step_data(
            'Search Chrome builders matching buildset.read git footers',
            stdout=api.raw_io.output(
                '[{"ref": "refs/tags/132.0.6790.0", "repository": "/chromium/src", "revision": "40230e6cf598d11deb34d4a5e4656a72152d395e"}]'
            ))

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
      'success-immediate',
      try_build([
          # First 2 fetches are not tested (patchset unchagned).
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           2),
          # The next fetch returns a new patchset with PASSED result.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: PASSED https://ci.chromium.org/ui/b/998876\n',
           1)
      ]),
      api.post_check(post_process.SummaryMarkdown,
                     PRE_UPREV_PASS.summary_markdown),
      api.post_process(post_process.DoesNotRun,
                       'Fetch pre-uprev testing result.buildbucket.collect'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'success-wait',
      try_build([
          # First 2 fetches are not tested (patchset unchagned).
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           2),
          # The next fetches is test running.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: See https://ci.chromium.org/ui/b/998876\n',
           1),
          # Collect build finishes.
          # The next fetch returns a new patchset with PASSED result.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: PASSED https://ci.chromium.org/ui/b/998876\n',
           1)
      ]),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(
              id=998876,
              status=common_pb2.SUCCESS,
              summary_markdown='CL: xxx \n\n- chromeos-betty-chrome: SUCCESS\n- chromeos-brya-chrome: SUCCESS\n',
              infra=build_pb2.BuildInfra(
                  resultdb=build_pb2.BuildInfra.ResultDB(
                      invocation='invocations/build-998876-rdb'),
              ),
          ),
      ], step_name='Fetch pre-uprev testing result.buildbucket.collect'),
      api.post_check(post_process.SummaryMarkdown,
                     PRE_UPREV_PASS.summary_markdown),
      api.post_process(post_process.MustRun,
                       'Fetch pre-uprev testing result.buildbucket.collect'),
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
                     NO_PRE_UPREV_FOUND.summary_markdown),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'unexpected',
      try_build([
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           1),
          # Infinite fetches returns unexpected message.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Broken\n',
           int(FETCH_DESCRIPTION_TIMEOUT_SEC / FETCH_DESCRIPTION_INTERVAL_SEC) -
           1),
      ]),
      api.post_check(post_process.SummaryMarkdown,
                     NO_PRE_UPREV_FOUND.summary_markdown),
      api.post_process(post_process.DropExpectation),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'pre-uprev-failed',
      try_build([
          # First 2 fetches are not tested (patchset unchagned).
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           2),
          # The next fetches is test running.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: See https://ci.chromium.org/ui/b/998876\n',
           1),
          # Collect build finishes.
          # The pre-uprev status is not updated to commit message. probably
          # because the build didn't finish normally or did not pass.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: See https://ci.chromium.org/ui/b/998876\n',
           1)
      ]),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(
              id=998876,
              status=common_pb2.FAILURE,
              summary_markdown='CL: xxx \n\n- chromeos-betty-chrome: FAILED\n> chrome_all_tast_tests_failed\n- chromeos-brya-chrome: SUCCESS\n',
              infra=build_pb2.BuildInfra(
                  resultdb=build_pb2.BuildInfra.ResultDB(
                      invocation='invocations/build-998876-rdb'),
              ),
          ),
      ], step_name='Fetch pre-uprev testing result.buildbucket.collect'),
      api.post_process(post_process.MustRun,
                       'Fetch pre-uprev testing result.buildbucket.collect'),
      api.post_check(
          post_process.SummaryMarkdown,
          ('Pre-uprev testing not passed, details:\n\n'
           'CL: xxx \n\n- chromeos-betty-chrome: FAILED\n> chrome_all_tast_tests_failed\n- chromeos-brya-chrome: SUCCESS\n\n\n'
           'Please check the test failures, fix the failures (land a fix or revert culprit on Chromium) '
           'and wait for next pre-uprev. You can override by chump the CL but it is discouraged.'
          ),
      ),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'collect-empty-results',
      try_build([
          # First 2 fetches are not tested (patchset unchagned).
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: Not Tested\n',
           2),
          # The next fetches is test running.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: See https://ci.chromium.org/ui/b/998876\n',
           1),
          # Collect build finishes.
          # The pre-uprev status is not updated to commit message. probably
          # because the build didn't finish normally or did not pass.
          ('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n\nPre-Uprev Testing: See https://ci.chromium.org/ui/b/998876\n',
           1)
      ]),
      api.buildbucket.simulated_collect_output(
          [], step_name='Fetch pre-uprev testing result.buildbucket.collect'),
      api.post_process(post_process.MustRun,
                       'Fetch pre-uprev testing result.buildbucket.collect'),
      api.post_check(post_process.SummaryMarkdown,
                     NO_PASSING_PRE_UPREV_FOUND_SUMMARY),
      cq=True,
      status='FAILURE',
  )
