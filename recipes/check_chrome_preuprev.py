# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that checks Chrome uprev.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from typing import Optional, List, Tuple
import json
import re
import base64

from google.protobuf import timestamp_pb2, json_format, struct_pb2

from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
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
    'recipe_engine/futures',
    'recipe_engine/resultdb',
    'recipe_engine/time',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'easy',
    'gerrit',
    'test_util',
    'git_footers',
    'gitiles',
]

CHROMIUM_SRC_HOST = 'chromium.googlesource.com'
CHROMIUM_SRC_PROJECT = 'chromium/src'
CHROMIUM_VERSION_FILE = 'chrome/VERSION'

FETCH_BEST_CHROME_REVISION_TIMEOUT = 3600 * 3  # 3 hour
WAIT_ORCHESTRATOR_TIMEOUT_SEC = 3600 * 6  # 6 hour
FETCH_BEST_CHROME_REVISION_INTERVAL = 600
FETCH_BEST_CHROME_REVISION_TIMES = int(FETCH_BEST_CHROME_REVISION_TIMEOUT /
                                       FETCH_BEST_CHROME_REVISION_INTERVAL)
UPREV_CL_TOPICS = [
    'chromeos-base/lacros-ash-atomic',
    'chromeos-base/chromeos-chrome',
]
INVOCATION_PREFIX = 'invocations/'

NO_CL_FOUND_SUMMARY = 'No CL found.'
NOT_AN_UPREV_CL_SUMMARY = 'Not Chrome uprev CL.'
PRE_UPREV_PASS_SUMMARY = 'Pre-uprev testing passed. \n\nDetails: \n\n{}\n'
DO_NOT_CHUMP_THIS_CL = "ABSOLUTELY DO NOT CHUMP THIS CL\n\n"
ASK_QUESTIONS_SUMMARY = ("Questions to this builder goes to "
                         "g/chromeos-chrome-build, instead of CI oncall.\n\n")
FAILED_PRE_UPREVS_SUMMARY = (
    # Error notice
    'Pre-uprev testing not passed, details:\n\n{}\n\n'
    # Possible action items
    'Please check the test failures, fix the failures (land a fix or revert '
    'culprit on Chromium) and wait for next pre-uprev.\n\n'
    "To disable a failed tests at this builder, disable at "
    "[chromium/src/chromeos/tast_control_disabled_tests.txt]"
    "(https://source.chromium.org/chromium/chromium/src/+/main:"
    "chromeos/tast_control_disabled_tests.txt) instead.\n\n")
REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY = (
    # Error notice
    'Failed to find required pre-uprev builders\n'
    # Possible action items
    'Please retry later or wait for next uprev\n.')
CHROME_CI_NOT_GOOD = (
    # Error notice
    'Chrome best revision (canary releasable revision) '
    'is currently at r{}, want >=r{}.\n'
    'ChromeOS preuprev may have passed but on other platforms '
    'Chrome best revision is behind current version.\n'
    # Possible action items
    'This usually catches up in less than 2 hours, check '
    'https://ci.chromium.org/ui/p/chrome/builders/official.infra/chrome-best-revision-continuous, '
    'https://ci.chromium.org/p/chrome/g/chrome.release-ready/console'
    ' and try again. You can also just wait for next uprev.\n\n')
CHROME_CI_NOT_IDENTIFIED = (
    # Error notice
    'Cannot identify canary releasable Chrome revision, want >=r{}.\n'
    'Chrome release-ready builders may have been failing for many hours.\n'
    # Possible action items
    'Check '
    'https://ci.chromium.org/p/chrome/g/chrome.release-ready/console, '
    'https://ci.chromium.org/ui/p/chrome/builders/official.infra/chrome-best-revision-continuous'
    ' for latest status and retry later. You can also just wait for next uprev.\n\n'
    'You may also reach to go/chrome-trunk-gardening for any release-ready builder failures.\n\n'
)
CHROME_BRANCHED_DURING_UPREV = (
    # Error notice
    'Chrome created the beta branch candidate during uprev\n'
    'Submitting this CL may cause newer Chrome have smaller version number.\n'
    # Possible action items
    'Abandon this uprev CL and wait for the next one.\n\n')



NO_CL_FOUND = RawResult(status=common_pb2.INFRA_FAILURE,
                        summary_markdown=NO_CL_FOUND_SUMMARY)
NOT_AN_UPREV_CL = RawResult(status=common_pb2.SUCCESS,
                            summary_markdown=NOT_AN_UPREV_CL_SUMMARY)



PRE_UPREV_STATUS_BBID_EXTRACTOR = re.compile(
    r'[A-Za-z]* https://ci.chromium.org/ui/b/(\d+)')

ORCHESTRATOR_BUILD_FIELDS_TO_RETRIEVE = [
    'id',
    'status',
    'summary_markdown',
    'infra.resultdb.invocation',
]

CHROME_BEST_REVISION_FIELDS_TO_RETRIEVE = [
    'builder',
    'id',
    'output.properties',
    'status',
]

def BestChromeRevision(api: RecipeApi) -> Optional[int]:
  now = int(api.time.time())
  end_time = timestamp_pb2.Timestamp(seconds=now)
  start_time = timestamp_pb2.Timestamp(seconds=now - 3600 * 8)
  builds = api.buildbucket.search(
      builds_service_pb2.BuildPredicate(
          builder={
              'project': 'chrome',
              'bucket': 'official.infra',
              'builder': 'chrome-best-revision-continuous',
          },
          create_time=common_pb2.TimeRange(
              start_time=start_time,
              end_time=end_time,
          ),
      ), fields=CHROME_BEST_REVISION_FIELDS_TO_RETRIEVE)
  best_revision = None
  for build in builds:
    output = json_format.MessageToDict(build.output, struct_pb2.Struct)
    revision = output.get('properties', {}).get('best_revision_info',
                                                {}).get('commit_pos')
    if revision:
      best_revision = max(best_revision,
                          int(revision)) if best_revision else int(revision)
  return best_revision


def CheckPreUprevsFromOrchestrator(api: RecipeApi, chrome_commit: str):
  with api.step.nest('Find chrome-uprev-orchestrator') as step:
    orchestrator = api.buildbucket.search(
        builds_service_pb2.BuildPredicate(
            builder={
                'project': 'chromeos',
                'bucket': 'infra',
                'builder': 'chrome-uprev-orchestrator',
            }, tags=api.buildbucket.tags(
                buildset=f'commit/gitiles/chromium.googlesource.com/chromium/src/+/{chrome_commit}'
            )), fields=ORCHESTRATOR_BUILD_FIELDS_TO_RETRIEVE)[0]
    api.resultdb.include_invocations([
        orchestrator.infra.resultdb.invocation.removeprefix(INVOCATION_PREFIX)
    ])
  with api.step.nest('Wait chrome-uprev-orchestrator') as step:
    orchestrator = api.buildbucket.collect_builds(
        [orchestrator.id], fields=ORCHESTRATOR_BUILD_FIELDS_TO_RETRIEVE,
        timeout=WAIT_ORCHESTRATOR_TIMEOUT_SEC)[orchestrator.id]
    step.step_summary_text = (
        f'[Orchestrator](http://go/bbid/{orchestrator.id}/overview)\n\n' +
        orchestrator.summary_markdown)
  try:  # Ensure any errors on this step does not block uprev.
    with api.step.nest('Checking preuprev builder details') as step:
      if orchestrator.status != common_pb2.SUCCESS:
        step.step_summary_text = (
            "Retrying chrome-uprev-cq does NOT retry these tests\n\n"
            "CTP retries flaky tests and chrome-uprev-orchestrator retries INFRA_FAILURE once\n\n"
            "Please wait for next uprev\n\n")
      preuprevs = api.buildbucket.search(
          builds_service_pb2.BuildPredicate(
              builder={
                  'project': 'chrome',
                  'bucket': 'ci',
              }, child_of=orchestrator.id))
      for preuprev in preuprevs[::-1]:
        with api.step.nest(preuprev.builder.builder) as build:
          if preuprev.status == common_pb2.FAILURE:
            build.status = api.step.FAILURE
          elif preuprev.status != common_pb2.SUCCESS:
            build.status = api.step.EXCEPTION
          build.step_summary_text = (f"[go/bbid/{preuprev.id}]"
                                     f"(http://go/bbid/{preuprev.id})\n\n")
          if preuprev.status != common_pb2.SUCCESS:
            build.step_summary_text += preuprev.summary_markdown
  except Exception as e:  # pragma: nocover # pylint: disable=broad-except
    with api.step.nest('Something failed checking preuprev details') as step:
      step.status = common_pb2.EXCEPTION
      step.step_summary_text = str(e)

  return orchestrator


def WaitChromeBestRevision(api: RecipeApi,
                           target_chrome_revision: int) -> Optional[int]:
  with api.step.nest('Wait chrome-best-revision-continuous') as step:
    got_best_revision = None
    for i in range(FETCH_BEST_CHROME_REVISION_TIMES):
      got_best_revision = BestChromeRevision(api)
      if got_best_revision and got_best_revision >= target_chrome_revision:
        step.step_summary_text = f'Best revision reached {got_best_revision}'
        return got_best_revision
      if i < FETCH_BEST_CHROME_REVISION_TIMES - 1:
        api.time.sleep(FETCH_BEST_CHROME_REVISION_INTERVAL)

    if got_best_revision:
      step.step_summary_text = CHROME_CI_NOT_GOOD.format(
          got_best_revision, target_chrome_revision)
    else:
      step.step_summary_text = CHROME_CI_NOT_IDENTIFIED.format(
          target_chrome_revision)
    step.status = api.step.FAILURE
    return got_best_revision


def RunSteps(api: RecipeApi):
  cl = api.buildbucket.build.input.gerrit_changes
  if not cl:
    return NO_CL_FOUND
  cl = cl[0]
  patch_sets = api.gerrit.fetch_patch_sets([cl], include_files=True)
  if patch_sets[0].topic not in UPREV_CL_TOPICS or patch_sets[
      0].branch != 'main':
    return NOT_AN_UPREV_CL

  api.scheduler.emit_trigger(
      api.scheduler.BuildbucketTrigger(
          # Do not pass buildset as part of trigger.
          inherit_tags=False),
      project='chromeos',
      jobs=['gardener-data-collector'],
      step_name='trigger gardener-data-collector')

  target_chrome_revision = None
  target_chrome_milestone = None
  with api.step.nest('extract target Chrome revision') as step:
    for f in patch_sets[0].file_infos:
      m = re.match(
          r'.*/chromeos-chrome-(?P<milestone>[0-9]+)\..*_pre(?P<revision>[0-9]+).*\.ebuild$',
          f)
      if m:
        target_chrome_milestone = int(m.group('milestone'))
        target_chrome_revision = int(m.group('revision'))
        step.step_summary_text = (
            f'Target Chrome M{target_chrome_milestone} at r{target_chrome_revision}\n'
        )
  with api.step.nest('decode pupr version') as decode_step:
    pupr_version = api.git_footers.from_gerrit_change(cl,
                                                      UPREV_VERSION_LABEL)[0]
    decode_step.step_summary_text = pupr_version
    chrome_commit = json.loads(pupr_version)[0]['revision']

  errors = []
  error_do_no_chump = False
  check_chrome_preuprev_thread = api.futures.spawn_immediate(
      CheckPreUprevsFromOrchestrator, api, chrome_commit)
  wait_chrome_best_revision_thread = api.futures.spawn_immediate(
      WaitChromeBestRevision, api,
      target_chrome_revision) if target_chrome_revision else None

  orchestrator = check_chrome_preuprev_thread.result()
  best_revision = wait_chrome_best_revision_thread.result(
  ) if wait_chrome_best_revision_thread else None

  if orchestrator.status != common_pb2.SUCCESS:
    errors.append(
        FAILED_PRE_UPREVS_SUMMARY.format(
            f'[Orchestrator](http://go/bbid/{orchestrator.id}/overview)\n\n' +
            orchestrator.summary_markdown))

  if target_chrome_revision:
    if best_revision is None:
      error_do_no_chump = True
      errors.append(CHROME_CI_NOT_IDENTIFIED.format(target_chrome_revision))
    elif best_revision < target_chrome_revision:
      error_do_no_chump = True
      errors.append(
          CHROME_CI_NOT_GOOD.format(best_revision, target_chrome_revision))
    else:
      mock_version = '\n'.join(
          ['MAJOR=130', 'MINOR=0', 'BUILD=6699', 'PATCH=0'])
      mock_result = base64.b64encode(mock_version.encode())
      tot_version = api.gitiles.get_file(
          CHROMIUM_SRC_HOST,
          CHROMIUM_SRC_PROJECT,
          CHROMIUM_VERSION_FILE,
          ref='refs/heads/main',
          public=False,
          step_name='Fetch ToT version',
          test_output_data=mock_result,
      ).decode()

      assert tot_version.startswith('MAJOR=')
      tot_milestone = int(tot_version.split('\n')[0].split('=')[1])
      if tot_milestone != target_chrome_milestone:
        error_do_no_chump = True
        errors.append(CHROME_BRANCHED_DURING_UPREV)

  if errors:
    return RawResult(
        status=common_pb2.FAILURE,
        summary_markdown=((DO_NOT_CHUMP_THIS_CL if error_do_no_chump else '') +
                          '%d errors checking Chrome uprev criteria:\n\n\n\n' %
                          (len(errors)) + '\n\n\n\n'.join(errors)) +
        ASK_QUESTIONS_SUMMARY)

  return RawResult(
      status=common_pb2.SUCCESS, summary_markdown=PRE_UPREV_PASS_SUMMARY.format(
          orchestrator.summary_markdown))



def GenTests(api: RecipeTestApi):

  GERRIT_HOST = 'chromium.googlesource.com'
  PROJECT = 'chromiumos/overlays/chromiumos-overlay'
  CHANGE_NUMBER = 123456
  PATCHSET = 7

  def orchestrator(api: RecipeTestApi, status, summary: str,
                   preuprevs: List[Tuple[str, common_pb2.Status]]):

    def _build(status, summary, builder):
      return build_pb2.Build(
          builder=builder, id=1231231919, status=status,
          summary_markdown=summary, infra=build_pb2.BuildInfra(
              resultdb=build_pb2.BuildInfra.ResultDB(
                  invocation='invocations/build-1231231919-rdb')))

    orchestrator_builder_id = builder_common_pb2.BuilderID(
        project='chromeos', bucket='infra', builder='chrome-uprev-orchestrator')
    return api.buildbucket.simulated_search_results(
        [_build(common_pb2.SCHEDULED, "", orchestrator_builder_id)],
        step_name='Find chrome-uprev-orchestrator.buildbucket.search'
    ) + api.buildbucket.simulated_collect_output(
        [_build(status, summary, orchestrator_builder_id)],
        step_name='Wait chrome-uprev-orchestrator.buildbucket.collect'
    ) + api.buildbucket.simulated_search_results([
        _build(
            status, f'{name} result {common_pb2.Status.Name(status)}',
            builder_common_pb2.BuilderID(project='chrome', bucket='ci',
                                         builder=name))
        for name, status in preuprevs[::-1]
    ], step_name='Checking preuprev builder details.buildbucket.search')

  def chrome_best_revision(api, positions):

    def _build(idx, position):
      output = build_pb2.Build.Output()
      if position:
        output.properties['best_revision_info'] = {
            'commit_pos': position,
        }
      return build_pb2.Build(
          id=13219283712312 + idx,
          builder=builder_common_pb2.BuilderID(
              project='chrome', bucket='official.infra',
              builder='chrome-best-revision-continuous'),
          status=common_pb2.SUCCESS,
          output=output,
      )

    build = api.buildbucket.simulated_search_results([
        _build(0, positions[0]),
    ], step_name='Wait chrome-best-revision-continuous.buildbucket.search')

    for idx in range(1, len(positions)):
      build += api.buildbucket.simulated_search_results([
          _build(idx, positions[idx]),
      ], step_name=f'Wait chrome-best-revision-continuous.buildbucket.search ({idx+1})'
                                                       )

    return build

  def try_build_with_cl(chrome_version, topic=UPREV_CL_TOPICS[0]):
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
        'topic': topic if topic else '',
        'branch': 'main',
        'change_id': str(CHANGE_NUMBER),
        'status': 'NEW',
        'revision_info': {
            '_number': PATCHSET,
            'commit': {
                'message':
                    f'chromeos-chrome: Automatic uprev to {chrome_version}.\n',
            },
            'files': {
                f'chromeos-base/chromeos-chrome/chromeos-chrome-{chrome_version}_rc-r1.ebuild':
                    {},
            },
        },
    }
    build += api.gerrit.set_gerrit_fetch_changes_response(
        '', [
            common_pb2.GerritChange(host=GERRIT_HOST, project=PROJECT,
                                    change=CHANGE_NUMBER, patchset=PATCHSET)
        ], {CHANGE_NUMBER: change})

    if not topic:
      return build

    build += api.step_data(
        'decode pupr version.read git footers', stdout=api.raw_io.output(
            '[{"ref": "refs/tags/132.0.6790.0", "repository": "/chromium/src", "revision": "40230e6cf598d11deb34d4a5e4656a72152d395e"}]'
        ))

    return build

  yield api.test(
      'success',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.SUCCESS, "All pre-uprev tests passed.",
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      api.post_check(post_process.SummaryMarkdown, (
          'Pre-uprev testing passed. \n\nDetails: \n\nAll pre-uprev tests passed.\n'
      )),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'main-branch-uprev-prerelease',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      chrome_best_revision(api, [1100000, 1122332]),
      api.post_check(post_process.SummaryMarkdown, (
          'Pre-uprev testing passed. \n\nDetails: \n\nAll pre-uprev tests passed.\n'
      )),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_check(post_process.MustRun, 'Fetch ToT version'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'main-branch-uprev-prerelease-chrome-not-good',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      chrome_best_revision(api, [None] + [1100000] *
                           (FETCH_BEST_CHROME_REVISION_TIMES - 1)),
      api.post_check(post_process.SummaryMarkdown, (
          'ABSOLUTELY DO NOT CHUMP THIS CL\n\n'
          '1 errors checking Chrome uprev criteria:\n\n\n\n'
          'Chrome best revision (canary releasable revision) is '
          'currently at r1100000, want >=r1122332.\n'
          'ChromeOS preuprev may have passed but on other platforms '
          'Chrome best revision is behind current version.\n'
          'This usually catches up in less than 2 hours, check '
          'https://ci.chromium.org/ui/p/chrome/builders/official.infra/chrome-best-revision-continuous, '
          'https://ci.chromium.org/p/chrome/g/chrome.release-ready/console'
          ' and try again. You can also just wait for next uprev.\n\n'
          "Questions to this builder goes to "
          "g/chromeos-chrome-build, instead of CI oncall.\n\n")),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_check(post_process.DoesNotRun, 'Fetch ToT version'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'main-branch-uprev-prerelease-chrome-not-identified',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      chrome_best_revision(api, [None] * FETCH_BEST_CHROME_REVISION_TIMES),
      api.post_check(post_process.SummaryMarkdown, (
          'ABSOLUTELY DO NOT CHUMP THIS CL\n\n'
          '1 errors checking Chrome uprev criteria:\n\n\n\n'
          'Cannot identify canary releasable Chrome revision, want >=r1122332.\n'
          'Chrome release-ready builders may have been failing for many hours.\n'
          'Check '
          'https://ci.chromium.org/p/chrome/g/chrome.release-ready/console, '
          'https://ci.chromium.org/ui/p/chrome/builders/official.infra/chrome-best-revision-continuous'
          ' for latest status and retry later. You can also just wait for next uprev.\n\n'
          'You may also reach to go/chrome-trunk-gardening for any release-ready builder failures.\n\n'
          "Questions to this builder goes to "
          "g/chromeos-chrome-build, instead of CI oncall.\n\n")),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_check(post_process.DoesNotRun, 'Fetch ToT version'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'main-branch-uprev-prerelease-chrome-branched',
      try_build_with_cl('129.0.6698.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      chrome_best_revision(api, [1100000, 1122332]),
      api.post_check(post_process.SummaryMarkdown, (
          'ABSOLUTELY DO NOT CHUMP THIS CL\n\n'
          '1 errors checking Chrome uprev criteria:\n\n\n\n'
          'Chrome created the beta branch candidate during uprev\n'
          'Submitting this CL may cause newer Chrome have smaller version number.\n'
          'Abandon this uprev CL and wait for the next one.\n\n'
          "Questions to this builder goes to "
          "g/chromeos-chrome-build, instead of CI oncall.\n\n")),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_check(post_process.MustRun, 'Fetch ToT version'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'not-cq-build', api.buildbucket.ci_build(builder='chrome-uprev-snapshot'),
      api.post_check(post_process.DoesNotRun,
                     'Search Chrome builders matching buildset'),
      api.post_check(post_process.DoesNotRun, 'Check pre-uprev results'),
      api.post_check(post_process.SummaryMarkdown,
                     NO_CL_FOUND.summary_markdown), cq=True,
      status='INFRA_FAILURE')

  yield api.test(
      'cq-build-no-cl',
      api.buildbucket.try_build(builder='chrome-uprev-cq', gerrit_changes=[]),
      api.post_check(post_process.DoesNotRun,
                     'Search Chrome builders matching buildset'),
      api.post_check(post_process.DoesNotRun, 'Check pre-uprev results'),
      api.post_check(post_process.SummaryMarkdown,
                     NO_CL_FOUND.summary_markdown), cq=True,
      status='INFRA_FAILURE')

  yield api.test(
      'not-chrome-uprev-cl',
      try_build_with_cl('chromeos-chrome: update ebulid.\n', topic=None),
      api.post_check(post_process.DoesNotRun,
                     'Search Chrome builders matching buildset'),
      api.post_check(post_process.DoesNotRun, 'Check pre-uprev results'),
      api.post_check(post_process.SummaryMarkdown,
                     NOT_AN_UPREV_CL.summary_markdown),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'pre-uprev-failed',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(
          api, common_pb2.FAILURE, 'Some pre-uprev builder failed.',
          [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
           ('chromeos-jacuzzi-chrome-preuprev', common_pb2.INFRA_FAILURE),
           ('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)]),
      api.post_check(
          post_process.SummaryMarkdown,
          ('1 errors checking Chrome uprev criteria:\n\n\n\n'
           'Pre-uprev testing not passed, details:\n\n'
           '[Orchestrator](http://go/bbid/1231231919/overview)\n\nSome pre-uprev builder failed.\n\n'
           'Please check the test failures, fix the failures (land a fix or revert culprit on Chromium) '
           'and wait for next pre-uprev.\n\n'
           "To disable a failed tests at this builder, disable at "
           "[chromium/src/chromeos/tast_control_disabled_tests.txt]"
           "(https://source.chromium.org/chromium/chromium/src/+/main:"
           "chromeos/tast_control_disabled_tests.txt) instead.\n\n"
           "Questions to this builder goes to "
           "g/chromeos-chrome-build, instead of CI oncall.\n\n"),
      ),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='FAILURE',
  )
