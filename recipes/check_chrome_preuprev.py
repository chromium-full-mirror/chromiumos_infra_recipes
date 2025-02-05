# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that checks Chrome uprev.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from collections import namedtuple
from typing import List, Optional, Tuple
import json
import re
import hashlib

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
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'easy',
    'gerrit',
    'test_util',
    'git_footers',
]

FETCH_BEST_CHROME_REVISION_INTERVAL = 600
FETCH_BEST_CHROME_REVISION_TIMES = 30
WAIT_PREUPREV_TIMEOUT_SEC = 3600 * 6  # 6 hour
UPREV_CL_TOPICS = ['chromeos-base/lacros-ash-atomic', 'staging/chrome-main']
INVOCATION_PREFIX = 'invocations/'

NO_CL_FOUND_SUMMARY = 'No CL found.'
NOT_AN_UPREV_CL_SUMMARY = 'Not Chrome uprev CL.'
PRE_UPREV_PASS_SUMMARY = 'Pre-uprev testing passed. \n\nDetails: \n\n{}\n'
DO_NOT_CHUMP_THIS_CL = "ABSOLUTELY DO NOT CHUMP THIS CL\n\n"
OVERALL_FAILURE_MESSAGE = (
    "To disable a failed tests at this builder, disable at "
    "[chromium/src/chromeos/tast_control.gni]"
    "(https://source.chromium.org/chromium/chromium/src/+/main:"
    "chromeos/tast_control.gni) instead.\n\n"
    "Questions to this builder goes to g/chromeos-velocity or "
    "g/chromeos-chrome-build, instead of CI oncall.\n\n")
FAILED_PRE_UPREVS_SUMMARY = (
    # Error notice
    'Pre-uprev testing not passed, details:\n\n{}\n\n'
    # Possible action items
    'Please check the test failures, fix the failures (land a fix or revert '
    'culprit on Chromium) and wait for next pre-uprev.')
REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY = (
    # Error notice
    'Failed to find required pre-uprev builders\n'
    # Possible action items
    'Please retry later or wait for next uprev\n.')
CHROME_CI_NOT_GOOD = (
    # Error notice
    'Chrome best revision is currently at {}, want >={}\n'
    'All ChromeOS preuprev has passed but on other platforms '
    'Chrome best revision is behind current version.\n'
    # Possible action items
    'This usually catches up in less than 2 hours, check '
    'https://ci.chromium.org/ui/p/chrome/builders/official.infra/chrome-best-revision-continuous'
    ' and try again. You can also just wait for next uprev.')


NO_CL_FOUND = RawResult(status=common_pb2.INFRA_FAILURE,
                        summary_markdown=NO_CL_FOUND_SUMMARY)
NOT_AN_UPREV_CL = RawResult(status=common_pb2.SUCCESS,
                            summary_markdown=NOT_AN_UPREV_CL_SUMMARY)



PRE_UPREV_STATUS_BBID_EXTRACTOR = re.compile(
    r'[A-Za-z]* https://ci.chromium.org/ui/b/(\d+)')

PREUPREV_BUILD_FIELDS_TO_RETRIEVE = [
    'builder',
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


def PreUprevBuilders(
    api: RecipeApi,
    builds: List[build_pb2.Build]) -> Optional[List[build_pb2.Build]]:
  with api.step.nest('filtering for useful builders'):
    fulfilled_builders = {}

    for k, conf in WANTED_BUILDERS.items():
      options = conf.oneof
      for b in builds:
        if b.builder.builder in options:
          if k not in fulfilled_builders:
            fulfilled_builders[k] = b
          # Prefer a successful build.
          elif b.status == common_pb2.SUCCESS:
            fulfilled_builders[k] = b
            break
          # Prefer a running build than unsuccessfully ended builds.
          elif fulfilled_builders[k].status in [
              common_pb2.FAILURE, common_pb2.INFRA_FAILURE, common_pb2.CANCELED
          ] and b.status in [common_pb2.STARTED, common_pb2.SCHEDULED]:
            fulfilled_builders[k] = b

    missing = False
    for k, conf in WANTED_BUILDERS.items():
      if k in fulfilled_builders:
        b = fulfilled_builders[k]
        with api.step.nest(f'Use {b.builder.builder} as {k}') as step:
          step.step_summary_text = (
              f'[bbid/{b.id}](https://ci.chromium.org/ui/b/{b.id})')
      else:
        missing = True
        with api.step.nest(f'Missing {k}') as step:
          step.status = api.step.FAILURE
          step.step_summary_text = f'Want one of {conf.oneof}'
    if missing:
      return None

    return fulfilled_builders.values()


def ToBuilderIds(builders: List[build_pb2.Build]) -> List[int]:
  return list(map(lambda b: int(b.id), builders))


def QuoteMd(s: Optional[str]) -> str:
  if not s:  # pragma: nocover
    return ''
  result = ''
  for l in s.splitlines():
    result += '> '
    result += l
    result += '\n'
  return result


def ToBuildersLinkMd(builders: List[build_pb2.Build],
                     include_details=False) -> str:
  text = ''
  for builder in builders:
    status = common_pb2.Status.Name(builder.status)
    text += (f'- {builder.builder.builder}: ' +
             f'[{status}](https://ci.chromium.org/ui/b/{builder.id})\n')
    if include_details:
      text += QuoteMd(builder.summary_markdown)
  return text


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


def CheckPreUprevs(
    api: RecipeApi, build_ids: List[int]
) -> Tuple[List[build_pb2.Build], List[build_pb2.Build]]:
  with api.step.nest('Check pre-uprev results'):
    builds = api.buildbucket.collect_builds(
        build_ids, fields=PREUPREV_BUILD_FIELDS_TO_RETRIEVE,
        timeout=WAIT_PREUPREV_TIMEOUT_SEC)
    builders = list(builds.values())

    successful_builds, failed_builds = [], []
    for builder in builders:
      with api.step.nest(f'{builder.builder.builder}',
                         status='last') as task_step:
        if builder.status == common_pb2.SUCCESS:
          successful_builds.append(builder)
          task_step.status = api.step.SUCCESS
        else:
          failed_builds.append(builder)
          task_step.status = (
              api.step.FAILURE
              if builder.status == common_pb2.FAILURE else api.step.EXCEPTION)
        task_step.step_summary_text = ToBuildersLinkMd([builder],
                                                       include_details=True)

    return builders, failed_builds


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

    step.step_summary_text = (f'Best revision at {got_best_revision} '
                              f'but want {target_chrome_revision}')
    step.status = api.step.FAILURE
    return got_best_revision


def RunSteps(api: RecipeApi):
  cl = api.buildbucket.build.input.gerrit_changes
  if not cl:
    return NO_CL_FOUND
  cl = cl[0]
  patch_sets = api.gerrit.fetch_patch_sets([cl], include_files=True)
  if patch_sets[0].topic not in UPREV_CL_TOPICS:
    return NOT_AN_UPREV_CL

  target_chrome_revision = None
  with api.step.nest('Extract target Chrome revision') as step:
    for f in patch_sets[0].file_infos:
      m = re.match(r'.*/chromeos-chrome-.*_pre([0-9]+).*\.ebuild$', f)
      if m:
        target_chrome_revision = int(m.group(1))
  with api.step.nest('Search Chrome builders matching buildset') as step:
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
        fields=PREUPREV_BUILD_FIELDS_TO_RETRIEVE,
    )
    preuprevs = PreUprevBuilders(api, builds)
    if preuprevs is None:
      return RawResult(
          status=common_pb2.FAILURE,
          summary_markdown=REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY)

  with api.step.nest('including pre-uprev builder results') as step:
    invocations = [
        i.infra.resultdb.invocation
        for i in preuprevs
        if i.infra.resultdb.invocation
    ]
    step.step_summary_text = '\n'.join(invocations)
    for inv in invocations:
      assert inv.startswith(INVOCATION_PREFIX), (
          f'Unexpected invocation: {inv}')
    api.resultdb.include_invocations(
        [inv[len(INVOCATION_PREFIX):] for inv in invocations],
        'include invocations from pre-uprev builders')

  errors = []
  error_do_no_chump = False
  check_chrome_preuprev_thread = api.futures.spawn_immediate(
      CheckPreUprevs, api, ToBuilderIds(preuprevs))
  wait_chrome_best_revision_thread = api.futures.spawn_immediate(
      WaitChromeBestRevision, api,
      target_chrome_revision) if target_chrome_revision else None

  builds, failed_builds = check_chrome_preuprev_thread.result()
  best_revision = wait_chrome_best_revision_thread.result(
  ) if wait_chrome_best_revision_thread else None

  if len(failed_builds) > 0:
    errors.append(
        FAILED_PRE_UPREVS_SUMMARY.format(
            ToBuildersLinkMd(builds, include_details=True)))

  if target_chrome_revision:
    if best_revision is None or best_revision < target_chrome_revision:
      error_do_no_chump = True
      errors.append(
          CHROME_CI_NOT_GOOD.format(best_revision, target_chrome_revision))

  if errors:
    return RawResult(
        status=common_pb2.FAILURE,
        summary_markdown=((DO_NOT_CHUMP_THIS_CL if error_do_no_chump else '') +
                          OVERALL_FAILURE_MESSAGE +
                          '%d errors checking Chrome uprev criteria:\n\n\n\n' %
                          (len(errors)) + '\n\n\n\n'.join(errors)))

  return RawResult(
      status=common_pb2.SUCCESS,
      summary_markdown=PRE_UPREV_PASS_SUMMARY.format(ToBuildersLinkMd(builds)))



def GenTests(api: RecipeTestApi):

  GERRIT_HOST = 'chromium.googlesource.com'
  PROJECT = 'chromiumos/overlays/chromiumos-overlay'
  CHANGE_NUMBER = 123456
  PATCHSET = 7

  _name_id_mapping = {}

  def _name(name):
    return name.replace('_', '-')

  def _name_to_id(name):
    name = _name(name)
    if name in _name_id_mapping:
      return _name_id_mapping[name]
    newid = int(hashlib.sha1(name.encode('utf-8')).hexdigest(), 16) % (10**9)
    if newid not in _name_id_mapping.values():
      _name_id_mapping[name] = newid
      return newid
    raise Exception('hash collision')  # pragma: nocover

  def build(name, status):
    return build_pb2.Build(
        id=_name_to_id(name),
        builder=builder_common_pb2.BuilderID(project='chrome', bucket='ci',
                                             builder=_name(name)),
        status=status,
        summary_markdown=f'Test {common_pb2.Status.Name(status)}',
        infra=build_pb2.BuildInfra(
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation='invocations/build-{}-rdb'.format(_name_to_id(
                    name))),
        ),
    )

  def simulate_search_pre_uprev_builders(api, step, **kwargs):
    return api.buildbucket.simulated_search_results(
        [build(k, v) for k, v in kwargs.items() if v is not None],
        step_name=step)

  def pre_uprev_started(
      api,
      step,
      chromeos_betty_chrome_preuprev=common_pb2.STARTED,
      chromeos_brya_chrome_preuprev=common_pb2.STARTED,
      chromeos_brya_chrome_preuprev_skylab=None,
      chromeos_jacuzzi_chrome_preuprev=common_pb2.STARTED,
      chromeos_volteer_chrome_preuprev=common_pb2.STARTED,
      linux_chromeos_chrome_preuprev=common_pb2.STARTED,
  ):
    # pylint: disable=unused-argument
    # locals() will include GenTests.locals() aka other functions defined under
    # GenTests. We exclude them to only include parameters of this function.
    # We also exclude None builders.
    v = {k: v for k, v in locals().items() if not callable(v) and v is not None}
    return simulate_search_pre_uprev_builders(**v)

  def simulate_collect_pre_uprev_builders(api, step, **kwargs):
    return api.buildbucket.simulated_collect_output(
        [build(k, v) for k, v in kwargs.items()], step_name=step)

  def pre_uprev_completed(api, step,
                          chromeos_betty_chrome_preuprev=common_pb2.SUCCESS,
                          chromeos_brya_chrome_preuprev=common_pb2.SUCCESS,
                          chromeos_jacuzzi_chrome_preuprev=common_pb2.SUCCESS,
                          chromeos_volteer_chrome_preuprev=common_pb2.SUCCESS,
                          linux_chromeos_chrome_preuprev=common_pb2.SUCCESS):
    # pylint: disable=unused-argument
    # locals() will include GenTests.locals() aka other functions defined under
    # GenTests. We exclude them to only include parameters of this function.
    v = {k: v for k, v in locals().items() if not callable(v)}
    return simulate_collect_pre_uprev_builders(**v)

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
        'Search Chrome builders matching buildset.read git footers',
        stdout=api.raw_io.output(
            '[{"ref": "refs/tags/132.0.6790.0", "repository": "/chromium/src", "revision": "40230e6cf598d11deb34d4a5e4656a72152d395e"}]'
        ))

    return build

  yield api.test(
      'success',
      try_build_with_cl('130.0.6699.0'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search'),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      api.post_check(post_process.SummaryMarkdown, (
          'Pre-uprev testing passed. \n\nDetails: \n\n'
          '- chromeos-betty-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/102114593)\n'
          '- chromeos-brya-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/284564751)\n'
          '- chromeos-jacuzzi-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/281483114)\n'
          '- chromeos-volteer-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/425179835)\n'
          '- linux-chromeos-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/992625145)\n\n'
      )),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'main-branch-uprev-prerelease',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search'),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      chrome_best_revision(api, [1100000, 1122332]),
      api.post_check(post_process.SummaryMarkdown, (
          'Pre-uprev testing passed. \n\nDetails: \n\n'
          '- chromeos-betty-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/102114593)\n'
          '- chromeos-brya-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/284564751)\n'
          '- chromeos-jacuzzi-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/281483114)\n'
          '- chromeos-volteer-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/425179835)\n'
          '- linux-chromeos-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/992625145)\n\n'
      )),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'main-branch-uprev-prerelease-chrome-not-good',
      try_build_with_cl('130.0.6699.0_pre1122332'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search'),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      chrome_best_revision(api, [None] + [1100000] *
                           (FETCH_BEST_CHROME_REVISION_TIMES - 1)),
      api.post_check(post_process.SummaryMarkdown, (
          'ABSOLUTELY DO NOT CHUMP THIS CL\n\n'
          "To disable a failed tests at this builder, disable at "
          "[chromium/src/chromeos/tast_control.gni]"
          "(https://source.chromium.org/chromium/chromium/src/+/main:"
          "chromeos/tast_control.gni) instead.\n\n"
          "Questions to this builder goes to g/chromeos-velocity or "
          "g/chromeos-chrome-build, instead of CI oncall.\n\n"
          '1 errors checking Chrome uprev criteria:\n\n\n\n'
          'Chrome best revision is currently at 1100000, want >=1122332\n'
          'All ChromeOS preuprev has passed but on other platforms '
          'Chrome best revision is behind current version.\n'
          'This usually catches up in less than 2 hours, check '
          'https://ci.chromium.org/ui/p/chrome/builders/official.infra/chrome-best-revision-continuous'
          ' and try again. You can also just wait for next uprev.')),
      api.post_check(post_process.MustRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'prefer-sucessful-build',
      try_build_with_cl('130.0.6699.0'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search',
          chromeos_brya_chrome_preuprev_skylab=common_pb2.SUCCESS),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      api.post_check(
          post_process.MustRun,
          'Search Chrome builders matching buildset.filtering for useful builders.Use chromeos-brya-chrome-preuprev-skylab as brya'
      ),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_process(post_process.DropExpectation),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'prefer-running-build',
      try_build_with_cl('130.0.6699.0'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search',
          chromeos_brya_chrome_preuprev=common_pb2.FAILURE,
          chromeos_brya_chrome_preuprev_skylab=common_pb2.STARTED),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      api.post_check(
          post_process.MustRun,
          'Search Chrome builders matching buildset.filtering for useful builders.Use chromeos-brya-chrome-preuprev-skylab as brya'
      ),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      api.post_process(post_process.DropExpectation),
      cq=True,
      status='SUCCESS',
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
      'missing-pre-uprevs',
      try_build_with_cl('130.0.6699.0'),
      api.post_check(post_process.SummaryMarkdown,
                     REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'missing-pre-uprevs-partial',
      try_build_with_cl('130.0.6699.0'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search',
          chromeos_betty_chrome_preuprev=None),
      api.post_check(post_process.SummaryMarkdown,
                     REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'pre-uprev-failed',
      try_build_with_cl('130.0.6699.0'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search'),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect',
                          chromeos_betty_chrome_preuprev=common_pb2.FAILURE),
      api.post_check(
          post_process.SummaryMarkdown,
          ("To disable a failed tests at this builder, disable at "
           "[chromium/src/chromeos/tast_control.gni]"
           "(https://source.chromium.org/chromium/chromium/src/+/main:"
           "chromeos/tast_control.gni) instead.\n\n"
           "Questions to this builder goes to g/chromeos-velocity or "
           "g/chromeos-chrome-build, instead of CI oncall.\n\n"
           '1 errors checking Chrome uprev criteria:\n\n\n\n'
           'Pre-uprev testing not passed, details:\n\n'
           '- chromeos-betty-chrome-preuprev: [FAILURE](https://ci.chromium.org/ui/b/102114593)\n'
           '> Test FAILURE\n'
           '- chromeos-brya-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/284564751)\n'
           '> Test SUCCESS\n'
           '- chromeos-jacuzzi-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/281483114)\n'
           '> Test SUCCESS\n'
           '- chromeos-volteer-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/425179835)\n'
           '> Test SUCCESS\n'
           '- linux-chromeos-chrome-preuprev: [SUCCESS](https://ci.chromium.org/ui/b/992625145)\n'
           '> Test SUCCESS\n\n\n'
           'Please check the test failures, fix the failures (land a fix or revert culprit on Chromium) '
           'and wait for next pre-uprev.'),
      ),
      api.post_check(post_process.DoesNotRun,
                     'Wait chrome-best-revision-continuous'),
      cq=True,
      status='FAILURE',
  )
