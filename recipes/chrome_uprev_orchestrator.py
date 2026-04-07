# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to orchestrate necessary builders and pupr for Chrome uprev."""

import base64
import hashlib
import re
from typing import List, Optional, Tuple

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.chrome_uprev_orchestrator import InputProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

PROPERTIES = InputProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/futures',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/time',
    'git',
    'gitiles',
]

CHROMIUM_SRC_HOST = 'chromium.googlesource.com'
CHROMIUM_SRC_PROJECT = 'chromium/src'
CHROMIUM_VERSION_FILE = 'chrome/VERSION'

CHROME_SIDE_BUILDERS = [
    'chromeos-betty-chrome-preuprev',
    'chromeos-brya-chrome-preuprev',
    'chromeos-jacuzzi-chrome-preuprev',
    'chromeos-volteer-chrome-preuprev',
    'chromeos-reven-chrome-preuprev',
    'linux-chromeos-chrome-preuprev',
]

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

PUPR_TIMEOUT = 30 * 60  # 30 minutes
PRE_UPREV_TEST_TIMEOUT = 6 * 60 * 60  # 6 hour


def ToBuilderIds(builders: List[build_pb2.Build]) -> List[int]:
  return list(map(lambda b: int(b.id), builders))


def ToBuildersLinkMd(builders: List[build_pb2.Build]) -> str:
  text = ''
  for builder in builders:
    status = common_pb2.Status.Name(builder.status)
    text += (f'- {builder.builder.builder}: ' +
             f'[{status}](https://ci.chromium.org/ui/b/{builder.id})\n')
  return text


def ChromeVersion(buildset: common_pb2.GitilesCommit) -> Optional[str]:
  if buildset.ref.startswith('refs/tags/'):
    return buildset.ref.removeprefix('refs/tags/')
  if buildset.ref == 'refs/heads/main':
    return None
  raise ValueError(f'Unsupported ref: {buildset.ref}')  # pragma: nocover


def IsVersionAvailable(api: RecipeApi, chrome_version: str) -> bool:
  """Returns True if the given version exists.

  Args:
    chrome_version (str): A Chrome version string, such as '98.0.1234.0'.

  Returns:
    True if the version exists, otherwise, False.
  """
  branch_number = int(chrome_version.split('.')[2])

  mock_version = '\n'.join(['MAJOR=98', 'MINOR=0', 'BUILD=1234', 'PATCH=0'])
  mock_result = None if branch_number > 1290 else base64.b64encode(
      mock_version.encode())

  version_file = api.gitiles.get_file(
      CHROMIUM_SRC_HOST,
      CHROMIUM_SRC_PROJECT,
      CHROMIUM_VERSION_FILE,
      ref='refs/tags/' + chrome_version,
      retries=3,
      public=False,
      step_name='Try fetching the version with incrementing the branch number',
      test_output_data=mock_result,
  )

  return version_file is not None


def IsVersionOnReleaseBranches(api: RecipeApi, chrome_version: str) -> bool:
  """Returns True if the given version is from release branches.

  Let's say the chrome version changes as follows:
    101.0.1111.0 -> 101.0.1112.0 -> 101.0.1113.0 -> 102.0.1114.0
  In this case, the release branch is 1113, since 1114 branch has next
  milestone number (102). This method returns true if the given version is
  "101.0.1113.0", false otherwise.

  Args:
    chrome_version (str): A Chrome version string, such as '98.0.1234.0'.

  Returns:
    True if the version is from release branches, otherwise, False.
  """
  mock_version = '\n'.join(['MAJOR=98', 'MINOR=0', 'BUILD=1234', 'PATCH=0'])
  mock_result = base64.b64encode(mock_version.encode())

  tot_version = api.gitiles.get_file(
      CHROMIUM_SRC_HOST,
      CHROMIUM_SRC_PROJECT,
      CHROMIUM_VERSION_FILE,
      ref='refs/heads/main',
      retries=3,
      public=False,
      step_name='Fetch ToT version',
      test_output_data=mock_result,
  ).decode()

  assert tot_version.startswith('MAJOR=')
  tot_milestone = int(tot_version.split('\n')[0].split('=')[1])
  chrome_version_numbers = chrome_version.split('.')
  milestone = int(chrome_version_numbers[0])

  # If the ToT milestone is same, it's not a release branch. In this case, no
  # release branch exists yet on this milestone.
  if milestone == tot_milestone:
    return False

  # The following code is for the previous version before the release branch.
  # In this case, the milestone number is different, because it has been
  # changed at the point of release branch.

  # The logic checks whether the next-numbered branch exists on the same
  # milestone or not. If it exists, it's not a release branch.
  # This works well because the release branch must be the last branch on the
  # same milestone. Let's say 1113 branch is the M101 release branch,
  # 101.0.1113.0 exists on the release branch and 101.0.1114.0 doesn't exist,
  # but 102.0.1114.0 does.
  branch_number = int(chrome_version_numbers[2])
  version_with_incrementing_branch_num = \
      '.'.join([str(milestone), '0', str(branch_number + 1), '0'])
  return not IsVersionAvailable(api, version_with_incrementing_branch_num)


def TriggerCrosBuild(api: RecipeApi, properties: dict, bucket: str,
                     builder: str) -> build_pb2.Build:
  """Triggers a build on CrOS infra.

  Args:
    properties (dict): Dict to pass to the builder.
    bucket (str): Name of the bucket of the builder, e.g. pupr.
    builder (str): Name of the builder to trigger, e.g. chrome-pupr-generator.
  """
  request = api.m.buildbucket.schedule_request(
      project='chromeos',
      bucket=bucket,
      builder=builder,
      properties=properties,
  )
  return api.m.buildbucket.schedule([request])[0]


def RunChromeBuild(api: RecipeApi, builder: str,
                   buildset: common_pb2.GitilesCommit,
                   timeout: int) -> Optional[build_pb2.Build]:
  with api.step.nest('run chrome builder'):
    request = api.buildbucket.schedule_request(
        project='chrome',
        bucket='ci',
        builder=builder,
        gitiles_commit=buildset,
    )
    builds = api.buildbucket.schedule([request], step_name='schedule')
    return api.buildbucket.collect_builds(
        ToBuilderIds(builds), fields=BUILD_FIELDS_TO_RETRIEVE,
        step_name='collect', timeout=timeout)[builds[0].id]


def RunSteps(api: RecipeApi, _: InputProperties) -> result_pb2.RawResult:
  # * On refs/heads/main
  #   -> run preuprev testing
  #   -> triggers the chrome-main uprev (to the main branch)
  # * On a release branches:
  #   -> skip preuprev testing
  #   -> triggers the chrome uprev (to the release branch) only
  # * On a non-release branches:
  #   -> do nothing

  buildset = api.buildbucket.build.input.gitiles_commit
  with api.step.nest('extracting Chrome version') as step:
    chrome_version = ChromeVersion(buildset)
    step.step_summary_text = f'Chrome version: {chrome_version}'

  puprs = []
  run_preuprevs = False
  summary_markdown = 'No uprevs'

  if chrome_version is None:
    message = api.gitiles.get_commit_metadata(
        CHROMIUM_SRC_HOST, CHROMIUM_SRC_PROJECT, buildset.id, public=False,
        test_data={
            'message': ('Roll Chrome Android ARM32 PGO Profile\n\n'
                        'Change-Id: I7e2a0277a1cff4551f4ee17edab0b56d0a20486e\n'
                        'Cr-Commit-Position: refs/heads/main@{#1397757}\n'),
        })['message']
    position = int(
        re.search(
            r'^Cr-Commit-Position: refs/heads/main@{#(\d+)}',
            message,
            flags=re.M,
        ).group(1))
    api.buildbucket.set_output_gitiles_commit(
        common_pb2.GitilesCommit(host=buildset.host, project=buildset.project,
                                 id=buildset.id, ref=buildset.ref,
                                 position=position))
    puprs.append('chrome-main')
    summary_markdown = 'Testing on main'
    run_preuprevs = True
  elif IsVersionOnReleaseBranches(api, chrome_version):
    # On release branch, we do Chrome (non-atomic) uprev to the branch on CrOS
    # repo.
    puprs.append('chrome')
    summary_markdown = 'On release branches'
  else:
    summary_markdown = 'No uprev on non-release branch release (daily canary)'

  builds = DoUprev(api, buildset, puprs, run_preuprevs)

  return Result(builds, summary_markdown)


def DoUprev(api: RecipeApi, buildset: common_pb2.GitilesCommit,
            puprs: List[str], run_preuprevs: bool) -> List[build_pb2.Build]:
  preuprevs = []
  if run_preuprevs:
    preuprevs = [
        api.futures.spawn(RunPreUprev, api, b, buildset)
        for b in CHROME_SIDE_BUILDERS
    ]

  pupr_builds = []
  with api.step.nest('trigger puprs'):
    for pupr in sorted(list(set(puprs))):
      pupr_builds.append(
          TriggerCrosBuild(
              api,
              bucket='staging' if pupr.startswith('staging-') else 'pupr',
              builder=f'{pupr}-pupr-generator',
              properties={
                  # Emulate a GitilesTrigger for the expected inputs of CrOS's pupr.
                  'triggers': [{
                      'gitiles': {
                          'repo': f'https://{buildset.host}/{buildset.project}',
                          'ref': buildset.ref,
                          'revision': buildset.id,
                      }
                  }],
              },
          ))

  return [x.result() for x in preuprevs]


def RunPreUprev(api: RecipeApi, builder: str,
                buildset: common_pb2.GitilesCommit) -> build_pb2.Build:
  with api.step.nest(f'Run preuprev {builder}') as step:
    build = RunChromeBuild(api, builder, buildset, PRE_UPREV_TEST_TIMEOUT)
    if build.status in [common_pb2.INFRA_FAILURE, common_pb2.CANCELED]:
      # Sleep 10 minutes before retry any infra-related issues.
      api.time.sleep(600)
      build = RunChromeBuild(api, builder, buildset, PRE_UPREV_TEST_TIMEOUT)
    if build.status != common_pb2.SUCCESS:
      step.status = api.step.FAILURE
      step.step_summary_text = build.summary_markdown
    return build


def FilterBuildsStatus(
    builders: List[build_pb2.Build], status: common_pb2.Status
) -> Tuple[List[build_pb2.Build], List[build_pb2.Build]]:
  true_builders, false_builders = [], []
  for builder in builders:
    if builder.status == status:
      true_builders.append(builder)
    else:
      false_builders.append(builder)
  return true_builders, false_builders


def Result(builds: List[build_pb2.Build],
           summary_markdown_prefix: str) -> result_pb2.RawResult:
  _, failed_builds = FilterBuildsStatus(builds, common_pb2.SUCCESS)
  summary_builds = ('\n\n' + ToBuildersLinkMd(builds)) if builds else ''
  if failed_builds:
    return result_pb2.RawResult(
        status=common_pb2.FAILURE,
        summary_markdown=f'{summary_markdown_prefix}{summary_builds}')
  return result_pb2.RawResult(
      status=common_pb2.SUCCESS,
      summary_markdown=f'{summary_markdown_prefix}{summary_builds}')


def GenTests(api: RecipeTestApi):

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
    assert False  # pragma: nocover

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

  def trigger(chrome_version: str):
    host = 'chromium.googlesource.com'
    project = 'chromium/src'
    commit = '8302b1a80de0995f146605740417cdf78e381157'

    build = build_pb2.Build(
        id=1231231231,
        number=1,
        tags=None,
        builder=builder_common_pb2.BuilderID(
            project='chromeos',
            bucket='infra',
            builder='chrome-uprev-orchestrator',
        ),
        created_by='user:user@google.com',
        create_time=timestamp_pb2.Timestamp(seconds=1331312211),
        input=build_pb2.Build.Input(
            gitiles_commit=common_pb2.GitilesCommit(
                host=host,
                project=project,
                id=commit,
                ref=f'refs/tags/{chrome_version}'
                if chrome_version else 'refs/heads/main',
            ),
        ),
    )

    return api.buildbucket.build(build)

  def preuprevs(api: RecipeTestApi, **kwargs):
    ret = []
    build_results = {k: common_pb2.SUCCESS for k in CHROME_SIDE_BUILDERS}
    for k, v in kwargs.items():
      name = _name(k)
      build_results[name] = v

    for k, v in build_results.items():
      if not isinstance(v, list):
        v = [v]
      for idx, vv in enumerate(v):
        idx = f' ({idx+1})' if idx > 0 else ''
        ret.append(
            api.buildbucket.simulated_schedule_output(
                builds_service_pb2.BatchResponse(responses=[{
                    'schedule_build': build(k, common_pb2.SCHEDULED)
                }]),
                step_name=f'Run preuprev {k}.run chrome builder{idx}.schedule'))
        ret.append(
            api.buildbucket.simulated_collect_output(
                [build(k, vv)],
                step_name=f'Run preuprev {k}.run chrome builder{idx}.collect'))

    r = ret[0]
    for i in ret[1:]:
      r += i
    return r

  yield api.test(
      'version_on_release_branches',
      trigger(chrome_version='97.0.1290.1'),
      api.post_process(post_process.LogContains,
                       'trigger puprs.buildbucket.schedule', 'request', [
                           '"builder": "chrome-pupr-generator"',
                       ]),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'version_on_non_release_branch',
      trigger(chrome_version='98.0.1234.1'),
      api.post_process(post_process.DoesNotRun,
                       'Run preuprev chromeos-betty-chrome-preuprev'),
      api.post_process(post_process.DoesNotRun,
                       'Run preuprev chromeos-brya-chrome-preuprev'),
      api.post_process(post_process.DoesNotRun,
                       'Run preuprev chromeos-jacuzzi-chrome-preuprev'),
      api.post_process(post_process.DoesNotRun,
                       'Run preuprev chromeos-volteer-chrome-preuprev'),
      api.post_process(post_process.DoesNotRun,
                       'Run preuprev chromeos-reven-chrome-preuprev'),
      api.post_process(post_process.DoesNotRun,
                       'Run preuprev linux-chromeos-chrome-preuprev'),
      api.post_process(post_process.DoesNotRun,
                       'trigger puprs.buildbucket.schedule'),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'main',
      trigger(chrome_version=None),
      preuprevs(api, chromeos_betty_chrome_preuprev=common_pb2.SUCCESS,
                chromeos_brya_chrome_preuprev=common_pb2.SUCCESS),
      api.post_process(
          post_process.LogContains, 'trigger puprs.buildbucket.schedule',
          'request', [
              '"builder": "chrome-main-pupr-generator"',
              '"ref": "refs/heads/main"',
              '"revision": "8302b1a80de0995f146605740417cdf78e381157"',
          ]),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'main_failed_preuprevs',
      trigger(chrome_version=None),
      preuprevs(api, chromeos_betty_chrome_preuprev=common_pb2.SUCCESS,
                chromeos_brya_chrome_preuprev=common_pb2.FAILURE),
      api.post_process(
          post_process.LogContains, 'trigger puprs.buildbucket.schedule',
          'request', [
              '"builder": "chrome-main-pupr-generator"',
              '"ref": "refs/heads/main"',
              '"revision": "8302b1a80de0995f146605740417cdf78e381157"',
          ]),
      status='FAILURE',
  )

  yield api.test(
      'main_failed_preuprevs_retried',
      trigger(chrome_version=None),
      preuprevs(
          api, chromeos_betty_chrome_preuprev=common_pb2.FAILURE,
          chromeos_brya_chrome_preuprev=[
              common_pb2.INFRA_FAILURE, common_pb2.SUCCESS
          ]),
      api.post_process(
          post_process.LogContains, 'trigger puprs.buildbucket.schedule',
          'request', [
              '"builder": "chrome-main-pupr-generator"',
              '"ref": "refs/heads/main"',
              '"revision": "8302b1a80de0995f146605740417cdf78e381157"',
          ]),
      status='FAILURE',
  )
