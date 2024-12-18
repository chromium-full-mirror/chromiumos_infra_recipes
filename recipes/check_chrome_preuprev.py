# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that checks Chrome uprev.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from collections import namedtuple
from typing import List, Optional
import json
import re
import hashlib

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
    'recipe_engine/resultdb',
    'recipe_engine/time',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'easy',
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
PRE_UPREV_PASS_SUMMARY = 'Pre-uprev testing passed. \n\nDetails: \n\n{}\n'
FAILED_PRE_UPREVS_SUMMARY = (
    # Error notice
    'Pre-uprev testing not passed, details:\n\n{}\n\n'
    # Possible action items
    'Please check the test failures, fix the failures (land a fix or revert '
    'culprit on Chromium) and wait for next pre-uprev. You can override by '
    'chump the CL but it is strongly discouraged.')
REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY = (
    # Error notice
    'Failed to find required pre-uprev builders\n'
    # Possible action items
    'Please retry later or wait for next uprev\n.')

NO_CL_FOUND = RawResult(status=common_pb2.INFRA_FAILURE,
                        summary_markdown=NO_CL_FOUND_SUMMARY)
NOT_AN_UPREV_CL = RawResult(status=common_pb2.SUCCESS,
                            summary_markdown=NOT_AN_UPREV_CL_SUMMARY)



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


def RunSteps(api: RecipeApi):
  cl = api.buildbucket.build.input.gerrit_changes
  if not cl:
    return NO_CL_FOUND
  cl = cl[0]
  patch_sets = api.gerrit.fetch_patch_sets([cl])
  if patch_sets[0].topic != UPREV_CL_TOPIC:
    return NOT_AN_UPREV_CL
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
        fields=BUILD_FIELDS_TO_RETRIEVE,
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

  with api.step.nest('Check pre-uprev results') as step:
    builds = api.buildbucket.collect_builds(
        ToBuilderIds(preuprevs), fields=BUILD_FIELDS_TO_RETRIEVE,
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
          task_step.step_summary_text = builder.summary_markdown

    api.easy.set_properties_step(
        'set failed test builder ids as output properties',
        failed_builds=[builder.id for builder in failed_builds])

    if len(failed_builds) > 0:
      return RawResult(
          status=common_pb2.FAILURE,
          summary_markdown=FAILED_PRE_UPREVS_SUMMARY.format(
              ToBuildersLinkMd(builders, include_details=True)))
    return RawResult(
        status=common_pb2.SUCCESS,
        summary_markdown=PRE_UPREV_PASS_SUMMARY.format(
            ToBuildersLinkMd(builders)))



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

  def try_build_with_cl(message, topic=UPREV_CL_TOPIC):
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
    }
    build += api.gerrit.set_gerrit_fetch_changes_response(
        '', [
            common_pb2.GerritChange(host=GERRIT_HOST, project=PROJECT,
                                    change=CHANGE_NUMBER, patchset=PATCHSET)
        ], {CHANGE_NUMBER: change})

    if not message or not topic:
      return build

    change = {
        '_number': CHANGE_NUMBER,
        'topic': topic,
        'change_id': str(CHANGE_NUMBER),
        'status': 'NEW',
        'revision_info': {
            '_number': PATCHSET,
            'commit': {
                'message': message,
            }
        }
    }
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

    return build

  yield api.test(
      'success',
      try_build_with_cl('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
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
      api.post_check(post_process.PropertyEquals, 'failed_builds', []),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'prefer-sucessful-build',
      try_build_with_cl('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search',
          chromeos_brya_chrome_preuprev_skylab=common_pb2.SUCCESS),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      api.post_check(
          post_process.MustRun,
          'Search Chrome builders matching buildset.filtering for useful builders.Use chromeos-brya-chrome-preuprev-skylab as brya'
      ),
      api.post_process(post_process.DropExpectation),
      cq=True,
      status='SUCCESS',
  )

  yield api.test(
      'prefer-running-build',
      try_build_with_cl('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search',
          chromeos_brya_chrome_preuprev=common_pb2.FAILURE,
          chromeos_brya_chrome_preuprev_skylab=common_pb2.STARTED),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect'),
      api.post_check(
          post_process.MustRun,
          'Search Chrome builders matching buildset.filtering for useful builders.Use chromeos-brya-chrome-preuprev-skylab as brya'
      ),
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
      try_build_with_cl('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
      api.post_check(post_process.SummaryMarkdown,
                     REQUIRED_PRE_UPREV_BUILDERS_MISSING_SUMMARY),
      cq=True,
      status='FAILURE',
  )

  yield api.test(
      'missing-pre-uprevs-partial',
      try_build_with_cl('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
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
      try_build_with_cl('chromeos-chrome: Automatic uprev to 130.0.6699.0.\n'),
      pre_uprev_started(
          api, 'Search Chrome builders matching buildset.buildbucket.search'),
      pre_uprev_completed(api, 'Check pre-uprev results.buildbucket.collect',
                          chromeos_betty_chrome_preuprev=common_pb2.FAILURE),
      api.post_check(
          post_process.SummaryMarkdown,
          ('Pre-uprev testing not passed, details:\n\n'
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
           'and wait for next pre-uprev. You can override by chump the CL but it is strongly discouraged.'
          ),
      ),
      api.post_check(post_process.PropertyEquals, 'failed_builds', [102114593]),
      cq=True,
      status='FAILURE',
  )
