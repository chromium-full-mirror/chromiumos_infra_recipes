# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that checks Chrome uprev.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from typing import List, Optional, Tuple
import datetime
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
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
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
    'recipe_engine/url',
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
RETRIABLE_TEST_SUITES = {
    'chrome_all_tast_tests LKGM',
}
MAX_RETRIABLE_TESTS = 20
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
    'output.properties',
    'infra.resultdb.invocation',
]

PREUPREV_CHILD_BUILD_FIELDS_TO_RETRIEVE = [
    'id',
    'builder',
    'status',
    'summary_markdown',
    'output.properties',
    'infra.resultdb.invocation',
]

CTP_BUILD_FIELDS_TO_RETRIEVE = [
    'id',
    'builder',
    'status',
    'summary_markdown',
    'input.properties',
    'infra.resultdb.invocation',
    'create_time',
]

CHROME_BEST_REVISION_FIELDS_TO_RETRIEVE = [
    'builder',
    'id',
    'output.properties',
    'status',
]


def ShouldCheckChromeBestRevision(api: RecipeApi,
                                  milestone: int) -> tuple[bool, bool]:
  """Check if we should run WaitChromeBestRevision and allow 12h failure bypass.

  Returns:
    (should_check, allow_12h_failure)
    - diff_days > 3: (False, False) -> No check.
        Rationale: On every ChromeOS branch, each uprev moves Chrome forward
        along its corresponding Chrome branching tree. Even without this CL,
        within-milestone build number consistency is not strictly enforced
        since Chrome may turn green during a subsequent uprev CQ retry attempt
        when the target build number has already bumped. We only force-fail
        when the milestone has bumped regardless of best revision status,
        ensuring a larger Portage version number corresponds to newer Chrome
        commits on the Chrome tree at cross-milestone timing so real
        dev/beta/stable release uprevs do not downgrade commits.
    - 1 < diff_days <= 3: (True, True) -> Check, allow 12h failure bypass.
        Rationale: Chrome automated milestone branch cut only looks at good
        revisions from the past 8 hours. If all continuous builds in the past
        12 hours are red, automatic milestone bump will fail, requiring human
        release managers to manually bump the milestone after fixing things. A
        manual milestone bump will occur at a newer commit, so real
        dev/beta/stable releases will not be downgraded even if we allow
        submission when nothing is green in the past 12 hours.
    - diff_days <= 1: (True, False) -> Check, strictly ensure
        best_revision >= target.
        Rationale: Within 1 day before branch cut, on branch day, or past branch
        cut (e.g. yesterday, diff_days <= 1), cross-milestone branch cut is
        imminent or completed. We strictly enforce best_revision >= target to
        guarantee a larger Portage version number always points to newer Chrome
        commits.
  """
  try:
    url = f'https://chromiumdash.appspot.com/fetch_milestone_schedule?mstone={milestone}'
    now_ts = int(api.time.time())
    res = api.url.get_json(
        url,
        step_name='fetch Chrome milestone schedule',
    )
    output = res.output or {}
    branch_date_str = None
    if isinstance(output, dict):
      mstones = output.get('mstones', [])
      if isinstance(mstones, list):
        for item in mstones:
          if isinstance(item, dict) and item.get('mstone') == milestone:
            branch_date_str = item.get('branch_point') or item.get(
                'branch_date')
            break
      if not branch_date_str:
        branch_date_str = output.get('branch_point') or output.get(
            'branch_date')

    if not branch_date_str:
      # If schedule cannot be determined, fall back safely to strict check.
      return True, False

    branch_dt = datetime.datetime.fromisoformat(
        branch_date_str.replace('Z', '+00:00'))
    if branch_dt.tzinfo is None:
      branch_dt = branch_dt.replace(tzinfo=datetime.timezone.utc)
    branch_ts = branch_dt.timestamp()

    diff_days = (branch_ts - now_ts) / 86400.0

    # Rule 1: > 3 days before branch date -> No check.
    # On every ChromeOS branch, each uprev moves Chrome forward along its
    # corresponding Chrome branching tree. Even without this CL,
    # within-milestone build number consistency is not strictly enforced since
    # Chrome may turn green during a subsequent uprev CQ retry attempt when
    # the target build number has already bumped. We only ensure a larger
    # Portage version number corresponds to newer Chrome commits on the Chrome
    # tree at cross-milestone timing, so real dev/beta/stable release uprevs do
    # not downgrade commits.
    if diff_days > 3:
      return False, False

    # Rule 2: > 1 day before branch date (1 < diff_days <= 3) -> Check, allow
    # 12h failure bypass.
    # Chrome automated milestone branch cut only looks at good revisions from
    # the past 8 hours. If all continuous builds in the past 12 hours are red,
    # automatic milestone bump will fail. Human release managers must manually
    # bump the milestone after fixing things, which means the real branch bump
    # will occur at a newer commit. Thus real dev/beta/stable releases will not
    # be downgraded even if we allow submission when nothing is green in past
    # 12h.
    if diff_days > 1:
      return True, True

    # Rule 3: <= 1 day before branch date -> Check, strictly ensure
    # best_revision >= target.
    # Within 1 day before branch cut, on branch day, or past branch cut (e.g.
    # yesterday, diff_days <= 1), milestone branch cut is imminent or
    # completed. We strictly enforce best_revision >= target to guarantee a
    # larger Portage version number always points to newer Chrome commits.
    return True, False
  except Exception:  # pragma: no cover # pylint: disable=broad-exception-caught
    return True, False


def BestChromeRevision(api: RecipeApi, lookback_hours: int) -> int | None:
  now = int(api.time.time())
  end_time = timestamp_pb2.Timestamp(seconds=now)
  start_time = timestamp_pb2.Timestamp(seconds=now - 3600 * lookback_hours)
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
      rev_int = int(revision)
      if best_revision is None or rev_int > best_revision:
        best_revision = rev_int
  return best_revision


def CheckPreUprevsFromOrchestrator(
    api: RecipeApi,
    chrome_commit: str) -> tuple[build_pb2.Build | None, list[build_pb2.Build]]:
  """Search for and collect chrome-uprev-orchestrator build and its child preuprev builds.

  Args:
    api: Recipe API object.
    chrome_commit: The Chromium commit hash.

  Returns:
    A tuple of (orchestrator_build, child_preuprev_builds). Returns (None, [])
    if no orchestrator build is found for the given commit.
  """
  with api.step.nest('Find chrome-uprev-orchestrator') as step:
    orchestrator_builds = api.buildbucket.search(
        builds_service_pb2.BuildPredicate(
            builder={
                'project': 'chromeos',
                'bucket': 'infra',
                'builder': 'chrome-uprev-orchestrator',
            }, tags=api.buildbucket.tags(
                buildset=f'commit/gitiles/chromium.googlesource.com/chromium/src/+/{chrome_commit}'
            )), fields=ORCHESTRATOR_BUILD_FIELDS_TO_RETRIEVE, limit=1)
    if not orchestrator_builds:  # pragma: no cover
      step.status = api.step.FAILURE
      step.step_summary_text = f'No chrome-uprev-orchestrator build found for commit {chrome_commit}'
      return None, []
    orchestrator = orchestrator_builds[0]
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
  preuprevs = []
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
              }, child_of=orchestrator.id),
          fields=PREUPREV_CHILD_BUILD_FIELDS_TO_RETRIEVE,
      )
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
      step.status = api.step.EXCEPTION
      step.step_summary_text = str(e)

  return orchestrator, preuprevs


def IsPreuprevRetriable(preuprev: build_pb2.Build) -> bool:
  """Check whether a preuprev build failure is retriable.

  Only builds with FAILURE status are considered for retry. Builds with
  INFRA_FAILURE or CANCELED status are not retriable because ResultDB test
  results are incomplete or unreliable for infra failures and canceled runs.
  """
  if preuprev.status != common_pb2.FAILURE:
    return False

  output_dict = json_format.MessageToDict(
      preuprev.output,
      struct_pb2.Struct) if preuprev.HasField('output') else {}
  test_status = output_dict.get('properties', {}).get('test_status', {})
  if not test_status:
    return False

  # 1. All non-retriable test suites must pass
  if any(v != 'Success'
         for k, v in test_status.items()
         if k not in RETRIABLE_TEST_SUITES):
    return False

  # 2. At least one retriable test suite must have failed
  has_retriable_failure = any(v == 'Failure'
                              for k, v in test_status.items()
                              if k in RETRIABLE_TEST_SUITES)
  return has_retriable_failure


def GetBuildCreateTime(ctp: build_pb2.Build) -> tuple[int, int]:
  """Extract creation time tuple (seconds, nanos) for build ordering."""
  if ctp.HasField('create_time'):
    return (ctp.create_time.seconds, ctp.create_time.nanos)
  return (0, 0)  # pragma: no cover


def ExtractCtpTestSuite(ctp: build_pb2.Build) -> str | None:
  """Extract exact test suite name from CTP build resultdb_settings input property."""
  if not ctp.HasField('input') or not ctp.input.HasField(
      'properties'):  # pragma: no cover
    return None

  props_dict = json_format.MessageToDict(ctp.input.properties,
                                         struct_pb2.Struct)
  ctpv2 = props_dict.get('ctpv2_request', {})
  requests = ctpv2.get('requests', [])
  for req in requests:
    suite_req = req.get('suiteRequest', {})
    test_suite = suite_req.get('testSuite', {})
    args = test_suite.get('executionMetadata', {}).get('args', [])
    for arg in args:
      if arg.get('flag') == 'resultdb_settings':
        val = arg.get('value')
        if val:
          try:
            decoded = base64.b64decode(val).decode('utf-8')
            settings = json.loads(decoded)
            suite = settings.get('base_variant', {}).get('test_suite')
            if suite:
              return suite
          except Exception:  # pragma: nocover # pylint: disable=broad-exception-caught
            pass
  return None  # pragma: no cover


def CheckPreuprevsRetriable(
    api: RecipeApi,
    orchestrator: build_pb2.Build,
    preuprevs: list[build_pb2.Build],
) -> tuple[bool, dict[str, dict[str, build_pb2.Build]]]:
  """Determine if failed preuprev builders can be retried via targeted CTP test retries.

  Args:
    api: Recipe API object.
    orchestrator: The failed orchestrator Buildbucket build object.
    preuprevs: List of child preuprev Buildbucket build objects.

  Returns:
    A tuple of (retriable, failed_ctp_builds):
      - retriable (bool): True if all failing preuprev builders are retriable
        and have valid latest CTP builds to retry.
      - failed_ctp_builds (dict): Nested dictionary mapping
        builder_name -> {suite_name: latest_ctp_build} for failed suites.
  """
  with api.step.nest('Check preuprev retriability') as step:
    if orchestrator.status != common_pb2.FAILURE or not preuprevs:  # pragma: no cover
      return False, {}

    all_retriable = True
    has_any_preuprev_failure = False
    failed_ctp_builds = {}
    for preuprev in preuprevs[::-1]:
      with api.step.nest(preuprev.builder.builder) as preuprev_step:
        if preuprev.status == common_pb2.SUCCESS:
          preuprev_step.step_summary_text = 'SUCCESS'
          continue

        has_any_preuprev_failure = True
        if not IsPreuprevRetriable(preuprev):
          preuprev_step.status = api.step.FAILURE
          preuprev_step.step_summary_text = 'Not retriable'
          all_retriable = False
          continue

        ctp_builds = api.buildbucket.search(
            builds_service_pb2.BuildPredicate(
                builder={
                    'project': 'chromeos',
                    'bucket': 'testplatform',
                    'builder': 'cros_test_platform',
                },
                child_of=preuprev.id,
            ),
            fields=CTP_BUILD_FIELDS_TO_RETRIEVE,
            limit=1000,
        )
        output_dict = json_format.MessageToDict(
            preuprev.output,
            struct_pb2.Struct) if preuprev.HasField('output') else {}
        test_status = output_dict.get('properties', {}).get('test_status', {})
        failed_suites = [k for k, v in test_status.items() if v == 'Failure']
        builder_ctps = {}
        for suite_name in failed_suites:
          suite_ctp_builds = [
              ctp for ctp in ctp_builds
              if ExtractCtpTestSuite(ctp) == suite_name
          ]
          if not suite_ctp_builds:
            preuprev_step.status = api.step.FAILURE
            preuprev_step.step_summary_text = (
                f'Missing CTP build for suite {suite_name}')
            all_retriable = False
            break

          latest_ctp = max(suite_ctp_builds, key=GetBuildCreateTime)
          if latest_ctp.status not in (common_pb2.SUCCESS,
                                       common_pb2.FAILURE):  # pragma: no cover
            preuprev_step.status = api.step.FAILURE
            preuprev_step.step_summary_text = (
                f'CTP build for suite {suite_name} has status '
                f'{common_pb2.Status.Name(latest_ctp.status)}')
            all_retriable = False
            break

          builder_ctps[suite_name] = latest_ctp

        if builder_ctps and all_retriable:
          failed_ctp_builds[preuprev.builder.builder] = builder_ctps

    retriable = all_retriable and has_any_preuprev_failure and len(
        failed_ctp_builds) > 0
    step.step_summary_text = f'retriable={retriable}'
    return retriable, failed_ctp_builds if retriable else {}


# Type alias for (test_id, ((variant_key, variant_value), ...))
TestVariantKey = tuple[str, tuple[tuple[str, str], ...]]


def _GetFailingTestVariantKeys(
    all_test_results: list[test_result_pb2.TestResult],
) -> set[TestVariantKey]:
  """Extract test variant keys (test_id, variant_def) that failed with no expected pass.

  Variant isolation ensures that a test passing on one board/model variant
  does not mask a failure of the same test on a different board/model variant.
  """
  unexpected_keys = set()
  expected_keys = set()
  for tr in all_test_results:
    variant_def = tuple(sorted(getattr(tr.variant, 'def').items()))
    key = (tr.test_id, variant_def)
    if tr.expected:
      expected_keys.add(key)
    else:
      unexpected_keys.add(key)
  return unexpected_keys - expected_keys


def GetFailedTastTestNames(api: RecipeApi, ctp: build_pb2.Build) -> list[str]:
  """Retrieve failed Tast test names for a CTP build from ResultDB."""
  if not (ctp.infra and ctp.infra.HasField('resultdb') and
          ctp.infra.resultdb.invocation):  # pragma: no cover
    return []

  inv_id = ctp.infra.resultdb.invocation.removeprefix('invocations/')

  res = api.resultdb.query(
      [inv_id],
      variants_with_unexpected_results=True,
      limit=0,
  )

  all_test_results = [
      tr for inv_data in res.values() for tr in inv_data.test_results
  ]
  failing_keys = _GetFailingTestVariantKeys(all_test_results)
  failing_test_ids = {test_id for test_id, _var in failing_keys}

  failed_names = []
  for test_id in failing_test_ids:
    test_name = test_id.split('/')[-1] if '/' in test_id else test_id
    if test_name and test_name not in failed_names:
      failed_names.append(test_name)
  return failed_names


def RetryFailedPreuprevTests(
    api: RecipeApi,
    failed_ctp_builds: dict[str, dict[str, build_pb2.Build]]) -> bool:
  """Schedule targeted CTP retries for failed Tast tests and verify results.

  Args:
    api: Recipe API object.
    failed_ctp_builds: Dict mapping builder_name -> {suite_name: ctp_build}.

  Returns:
    True if all retried CTP builds complete successfully and ResultDB shows
    no remaining failing test cases; False otherwise.
  """
  with api.step.nest('Retrying failed CTP tests') as retry_step:
    # 1. Prepare targeted CTP schedule requests for each failed suite.
    requests = []
    for _builder_name, suite_map in failed_ctp_builds.items():
      for _suite_name, ctp in suite_map.items():
        props = json_format.MessageToDict(
            ctp.input.properties,
            struct_pb2.Struct) if ctp.input.HasField('properties') else {}

        failed_test_names = GetFailedTastTestNames(api, ctp)
        if len(failed_test_names) > MAX_RETRIABLE_TESTS:
          retry_step.status = api.step.FAILURE
          retry_step.step_summary_text = (
              f'Too many failed tests for {ctp.builder.builder} '
              f'({len(failed_test_names)} > {MAX_RETRIABLE_TESTS}); skipping retry.'
          )
          return False

        if failed_test_names and 'ctpv2_request' in props:
          requests_list = props.get('ctpv2_request', {}).get('requests', [])
          for req in requests_list:
            suite_req = req.get('suiteRequest', {})
            test_suite = suite_req.get('testSuite', {})
            if 'testCaseTagCriteria' in test_suite or 'name' in test_suite:
              tag_criteria = test_suite.setdefault('testCaseTagCriteria', {})
              tag_criteria['testNames'] = failed_test_names
              tag_criteria.pop('tags', None)
              tag_criteria.pop('tagExcludes', None)
              tag_criteria.pop('testNameExcludes', None)

        req = api.buildbucket.schedule_request(
            builder=ctp.builder.builder,
            project=ctp.builder.project,
            bucket=ctp.builder.bucket,
            properties=props,
        )
        requests.append(req)

    # 2. Schedule retry builds.
    retried_builds = api.buildbucket.schedule(requests)

    # 3. Collect and verify retry build statuses.
    collected_retries = api.buildbucket.collect_builds(
        [b.id for b in retried_builds],
        fields=ORCHESTRATOR_BUILD_FIELDS_TO_RETRIEVE,
        timeout=WAIT_ORCHESTRATOR_TIMEOUT_SEC,
    )
    all_passed = all(
        b.status == common_pb2.SUCCESS for b in collected_retries.values())
    if not all_passed:
      retry_step.status = api.step.FAILURE
      retry_step.step_summary_text = 'Some retried CTP tests failed.'
      return False

    # 4. Perform final verification querying ResultDB for remaining failing test variants.
    inv_id = api.resultdb.current_invocation.removeprefix('invocations/')

    res = api.resultdb.query(
        [inv_id],
        variants_with_unexpected_results=True,
        limit=0,
        step_name='verify_no_failing_test_results',
    )
    all_test_results = [
        tr for inv_data in res.values() for tr in inv_data.test_results
    ]
    failing_keys = _GetFailingTestVariantKeys(all_test_results)

    if failing_keys:
      retry_step.status = api.step.FAILURE
      retry_step.step_summary_text = (
          'ResultDB still has unexpected failing test results after retry.')
      return False

    retry_step.step_summary_text = 'All retried CTP tests passed.'
    return True


def WaitChromeBestRevision(api: RecipeApi, target_chrome_revision: int,
                           allow_12h_failure: bool = False) -> Optional[int]:
  with api.step.nest('Wait chrome-best-revision-continuous') as step:
    got_best_revision = None

    for i in range(FETCH_BEST_CHROME_REVISION_TIMES):
      got_best_revision = BestChromeRevision(api, lookback_hours=12)
      if got_best_revision and got_best_revision >= target_chrome_revision:
        step.step_summary_text = f'Best revision reached {got_best_revision}'
        return got_best_revision
      if i < FETCH_BEST_CHROME_REVISION_TIMES - 1:
        api.time.sleep(FETCH_BEST_CHROME_REVISION_INTERVAL)

    # If no green build is found across the 12-hour lookback window
    # (got_best_revision is None) and allow_12h_failure is True
    # (1 < diff_days <= 3 days before branch cut):
    # Chrome's automated milestone branch cut process only inspects the past
    # 8 hours for green builds. If all continuous builds in the past 12 hours
    # are red/failing, automated branch cut will fail, requiring human release
    # managers to manually fix issues and perform a manual milestone bump.
    # Therefore, it is safe to allow submission of ChromeOS pre-uprevs during
    # continuous >12h failure.
    if got_best_revision is None and allow_12h_failure:
      step.step_summary_text = (
          'Skipped check: Chrome CI continuous failure > 12h near branch cut window'
      )
      return target_chrome_revision

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
  should_check_best_revision, allow_12h_failure = (
      ShouldCheckChromeBestRevision(api, target_chrome_milestone)
      if target_chrome_milestone else (False, False))
  wait_chrome_best_revision_thread = api.futures.spawn_immediate(
      WaitChromeBestRevision, api, target_chrome_revision,
      allow_12h_failure) if (target_chrome_revision and
                             should_check_best_revision) else None

  orchestrator, preuprevs = check_chrome_preuprev_thread.result()

  test_retries_passed = False
  if orchestrator.status != common_pb2.SUCCESS:
    retriable, failed_ctp_builds = CheckPreuprevsRetriable(
        api, orchestrator, preuprevs)
    if retriable:
      test_retries_passed = RetryFailedPreuprevTests(api, failed_ctp_builds)

  if orchestrator.status != common_pb2.SUCCESS and not test_retries_passed:
    errors.append(
        FAILED_PRE_UPREVS_SUMMARY.format(
            f'[Orchestrator](http://go/bbid/{orchestrator.id}/overview)\n\n' +
            orchestrator.summary_markdown))

  if target_chrome_milestone:
    mock_version = '\n'.join(['MAJOR=130', 'MINOR=0', 'BUILD=6699', 'PATCH=0'])
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

  if target_chrome_revision and should_check_best_revision:
    best_revision = wait_chrome_best_revision_thread.result(
    ) if wait_chrome_best_revision_thread else None
    if best_revision is None:
      error_do_no_chump = True
      errors.append(CHROME_CI_NOT_IDENTIFIED.format(target_chrome_revision))
    elif best_revision < target_chrome_revision:
      error_do_no_chump = True
      errors.append(
          CHROME_CI_NOT_GOOD.format(best_revision, target_chrome_revision))

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
                   preuprevs: List[Tuple[str,
                                         common_pb2.Status]], test_status=None):

    def _build(status, summary, builder, build_id=1231231919,
               build_test_status=None):
      output = build_pb2.Build.Output()
      if build_test_status is not None:
        output.properties['test_status'] = build_test_status
      return build_pb2.Build(
          builder=builder, id=build_id, status=status, summary_markdown=summary,
          output=output, infra=build_pb2.BuildInfra(
              resultdb=build_pb2.BuildInfra.ResultDB(
                  invocation=f'invocations/build-{build_id}-rdb')))

    orchestrator_builder_id = builder_common_pb2.BuilderID(
        project='chromeos', bucket='infra', builder='chrome-uprev-orchestrator')
    return api.buildbucket.simulated_search_results(
        [_build(common_pb2.SCHEDULED, "", orchestrator_builder_id)],
        step_name='Find chrome-uprev-orchestrator.buildbucket.search'
    ) + api.buildbucket.simulated_collect_output(
        [_build(status, summary, orchestrator_builder_id)],
        step_name='Wait chrome-uprev-orchestrator.buildbucket.collect'
    ) + api.buildbucket.simulated_search_results(
        [
            _build(
                preuprev_status,
                f'{name} result {common_pb2.Status.Name(preuprev_status)}',
                # 8000 + idx is an arbitrary base offset to assign unique dummy build IDs to simulated child preuprev builds.
                builder_common_pb2.BuilderID(project='chrome', bucket='ci',
                                             builder=name),
                build_id=8000 + idx,
                build_test_status=test_status)
            for idx, (name, preuprev_status) in enumerate(preuprevs[::-1])
        ],
        step_name='Checking preuprev builder details.buildbucket.search')

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
      api.url.json('fetch Chrome milestone schedule', {
          'mstones': [{
              'mstone': 130,
              'branch_point': '2012-05-14T00:00:00',
          }],
      }),
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
      api.url.json('fetch Chrome milestone schedule', {
          'mstones': [{
              'mstone': 130,
              'branch_point': '2012-05-14T00:00:00',
          }],
      }),
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
      api.post_check(post_process.MustRun, 'Fetch ToT version'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'main-branch-uprev-prerelease-chrome-not-identified',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      api.url.json('fetch Chrome milestone schedule', {
          'mstones': [{
              'mstone': 130,
              'branch_point': '2012-05-14T00:00:00',
          }],
      }),
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
      api.post_check(post_process.MustRun, 'Fetch ToT version'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'schedule-fetch-failed',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      api.url.json('fetch Chrome milestone schedule', {}),
      chrome_best_revision(api, [1100000, 1122332]),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'outside-branch-cut-window',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      api.url.json('fetch Chrome milestone schedule', {
          'mstones': [{
              'mstone': 130,
              'branch_point': '2026-09-01T00:00:00',
          }],
      }),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'branch-window-allow-12h-failure',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      orchestrator(api, common_pb2.SUCCESS, 'All pre-uprev tests passed.',
                   [('chromeos-betty-chrome-preuprev', common_pb2.SUCCESS),
                    ('chromeos-jacuzzi-chrome-preuprev', common_pb2.SUCCESS)]),
      api.url.json('fetch Chrome milestone schedule', {
          'mstones': [{
              'mstone': 130,
              'branch_point': '2012-05-16T04:00:00',
          }],
      }),
      chrome_best_revision(api, [None] * FETCH_BEST_CHROME_REVISION_TIMES),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_check(post_process.MustRun, 'Fetch ToT version'),
      cq=True,
      status='SUCCESS',
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

  def make_ctp_build(build_id, status, suite_name='chrome_all_tast_tests LKGM'):
    settings_json = json.dumps({'base_variant': {'test_suite': suite_name}})
    encoded_settings = base64.b64encode(
        settings_json.encode('utf-8')).decode('utf-8')
    props = struct_pb2.Struct()
    props['ctpv2_request'] = {
        'requests': [{
            'suiteRequest': {
                'testSuite': {
                    'name': suite_name,
                    'testCaseTagCriteria': {
                        'tags': ['group:mainline']
                    },
                    'executionMetadata': {
                        'args': [{
                            'flag': 'resultdb_settings',
                            'value': encoded_settings,
                        }]
                    }
                }
            }
        }]
    }
    out_props = struct_pb2.Struct()
    out_props['compressed_json_responses'] = 'dummy'
    b = build_pb2.Build(
        id=build_id,
        builder=builder_common_pb2.BuilderID(project='chromeos',
                                             bucket='testplatform',
                                             builder='cros_test_platform'),
        status=status,
        input=build_pb2.Build.Input(properties=props),
        output=build_pb2.Build.Output(properties=out_props),
        infra=build_pb2.BuildInfra(
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation=f'invocations/build-{build_id}-rdb')),
    )
    b.create_time.seconds = 100
    return b

  ctp_failed = make_ctp_build(999111, common_pb2.FAILURE)
  ctp_scheduled = make_ctp_build(999222, common_pb2.SCHEDULED)
  ctp_passed = make_ctp_build(999222, common_pb2.SUCCESS)
  ctp_failed_retry = make_ctp_build(999222, common_pb2.FAILURE)

  yield api.test(
      'pre-uprev-failed-ctp-retried-success',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Some pre-uprev builder failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'chrome_all_tast_tests LKGM': 'Failure'}),
      api.buildbucket.simulated_search_results([
          ctp_failed
      ], step_name='Check preuprev retriability.chromeos-jacuzzi-chrome-preuprev.buildbucket.search'
                                              ),
      api.resultdb.query(
          {
              'build-999111-rdb':
                  api.resultdb.Invocation(test_results=[
                      test_result_pb2.TestResult(
                          test_id='ninja://chromeos:chrome_all_tast_tests/tast.apps.Sharesheet',
                          expected=False,
                      ),
                      test_result_pb2.TestResult(
                          test_id='ninja://chromeos:chrome_all_tast_tests/tast.apps.OtherPass',
                          expected=True,
                      ),
                  ])
          },
          step_name='Retrying failed CTP tests.rdb query',
      ),
      api.buildbucket.simulated_schedule_output(
          builds_service_pb2.BatchResponse(responses=[{
              'schedule_build': ctp_scheduled
          }]), step_name='Retrying failed CTP tests.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          [ctp_passed],
          step_name='Retrying failed CTP tests.buildbucket.collect'),
      api.resultdb.query(
          {'123456': api.resultdb.Invocation(test_results=[])},
          step_name='Retrying failed CTP tests.verify_no_failing_test_results',
      ),
      api.post_check(post_process.MustRun, 'Retrying failed CTP tests'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'pre-uprev-failed-ctp-retried-ctp-red',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Some pre-uprev builder failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'chrome_all_tast_tests LKGM': 'Failure'}),
      api.buildbucket.simulated_search_results([
          ctp_failed
      ], step_name='Check preuprev retriability.chromeos-jacuzzi-chrome-preuprev.buildbucket.search'
                                              ),
      api.resultdb.query(
          {
              'build-999111-rdb':
                  api.resultdb.Invocation(test_results=[
                      test_result_pb2.TestResult(
                          test_id='ninja://chromeos:chrome_all_tast_tests/tast.apps.Sharesheet',
                          expected=False,
                      )
                  ])
          },
          step_name='Retrying failed CTP tests.rdb query',
      ),
      api.buildbucket.simulated_schedule_output(
          builds_service_pb2.BatchResponse(responses=[{
              'schedule_build': ctp_scheduled
          }]), step_name='Retrying failed CTP tests.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          [ctp_failed_retry],
          step_name='Retrying failed CTP tests.buildbucket.collect'),
      api.post_check(post_process.MustRun, 'Retrying failed CTP tests'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'pre-uprev-failed-ctp-retried-rdb-still-has-failing-tests',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Some pre-uprev builder failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'chrome_all_tast_tests LKGM': 'Failure'}),
      api.buildbucket.simulated_search_results([
          ctp_failed
      ], step_name='Check preuprev retriability.chromeos-jacuzzi-chrome-preuprev.buildbucket.search'
                                              ),
      api.resultdb.query(
          {
              'build-999111-rdb':
                  api.resultdb.Invocation(test_results=[
                      test_result_pb2.TestResult(
                          test_id='ninja://chromeos:chrome_all_tast_tests/tast.apps.Sharesheet',
                          expected=False,
                      )
                  ])
          },
          step_name='Retrying failed CTP tests.rdb query',
      ),
      api.buildbucket.simulated_schedule_output(
          builds_service_pb2.BatchResponse(responses=[{
              'schedule_build': ctp_scheduled
          }]), step_name='Retrying failed CTP tests.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          [ctp_passed],
          step_name='Retrying failed CTP tests.buildbucket.collect'),
      api.resultdb.query(
          {
              '123456':
                  api.resultdb.Invocation(test_results=[
                      test_result_pb2.TestResult(
                          test_id='ninja://chromeos:chrome_all_tast_tests/tast.apps.Sharesheet',
                          expected=False,
                      )
                  ])
          },
          step_name='Retrying failed CTP tests.verify_no_failing_test_results',
      ),
      api.post_check(post_process.MustRun, 'Retrying failed CTP tests'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'pre-uprev-failed-non-test-failure',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Compile failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'base_unittests LKGM': 'Failure'}),
      api.post_check(post_process.DoesNotRun, 'Retrying failed CTP tests'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'pre-uprev-failed-test-failure-even-ctp-green',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Post-CTP step failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'chrome_all_tast_tests LKGM': 'Failure'}),
      api.buildbucket.simulated_search_results([
          ctp_passed
      ], step_name='Check preuprev retriability.chromeos-jacuzzi-chrome-preuprev.buildbucket.search'
                                              ),
      api.resultdb.query(
          {
              'build-999222-rdb':
                  api.resultdb.Invocation(test_results=[
                      test_result_pb2.TestResult(
                          test_id='ninja://chromeos:chrome_all_tast_tests/tast.apps.Sharesheet',
                          expected=False,
                      )
                  ])
          },
          step_name='Retrying failed CTP tests.rdb query',
      ),
      api.buildbucket.simulated_schedule_output(
          builds_service_pb2.BatchResponse(responses=[{
              'schedule_build': ctp_scheduled
          }]), step_name='Retrying failed CTP tests.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          [ctp_passed],
          step_name='Retrying failed CTP tests.buildbucket.collect'),
      api.resultdb.query(
          {'123456': api.resultdb.Invocation(test_results=[])},
          step_name='Retrying failed CTP tests.verify_no_failing_test_results',
      ),
      api.post_check(post_process.MustRun, 'Retrying failed CTP tests'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'pre-uprev-failed-missing-ctp-build',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Some pre-uprev builder failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'chrome_all_tast_tests LKGM': 'Failure'}),
      api.buildbucket.simulated_search_results(
          [],
          step_name='Check preuprev retriability.chromeos-jacuzzi-chrome-preuprev.buildbucket.search'
      ),
      api.post_check(post_process.DoesNotRun, 'Retrying failed CTP tests'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'pre-uprev-failed-too-many-failed-tests',
      try_build_with_cl('130.0.6699.0'),
      orchestrator(api, common_pb2.FAILURE, 'Some pre-uprev builder failed.',
                   [('chromeos-jacuzzi-chrome-preuprev', common_pb2.FAILURE)],
                   test_status={'chrome_all_tast_tests LKGM': 'Failure'}),
      api.buildbucket.simulated_search_results([
          ctp_failed
      ], step_name='Check preuprev retriability.chromeos-jacuzzi-chrome-preuprev.buildbucket.search'
                                              ),
      api.resultdb.query(
          {
              'build-999111-rdb':
                  api.resultdb.Invocation(test_results=[
                      test_result_pb2.TestResult(
                          test_id=f'ninja://chromeos:chrome_all_tast_tests/tast.test.{i}',
                          expected=False,
                      ) for i in range(25)
                  ])
          },
          step_name='Retrying failed CTP tests.rdb query',
      ),
      api.post_check(post_process.MustRun, 'Retrying failed CTP tests'),
      cq=True,
      status='FAILURE',
  )
