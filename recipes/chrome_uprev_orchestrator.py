# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to orchestrate necessary builders and pupr for Chrome uprev."""

import base64
from typing import List, Optional

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.chrome_uprev_orchestrator import InputProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

PROPERTIES = InputProperties

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'git',
]

CHROMIUM_SRC_GIT = 'https://chromium.googlesource.com/chromium/src.git/'
CHROMIUM_VERSION_FILE = 'chrome/VERSION'

CHROME_SIDE_BUILDERS = [
    'chromeos-betty-chrome-preuprev',
    'chromeos-brya-chrome-preuprev',
    'chromeos-jacuzzi-chrome-preuprev',
    'chromeos-volteer-chrome-preuprev',
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

PRE_UPREV_TEST_TIMEOUT = 6 * 60 * 60  # 6 hour


def ToBuilderIds(builders: List[build_pb2.Build]) -> List[int]:
  return list(map(lambda b: int(b.id), builders))

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
      mock_version.encode()).decode()

  version_file = api.m.gitiles.download_file(
      CHROMIUM_SRC_GIT,
      CHROMIUM_VERSION_FILE,
      branch='refs/tags/' + chrome_version,
      step_name='Try fetching the version with incrementing the branch number',
      step_test_data=lambda: api.m.json.test_api.output({
          'value': mock_result,
      }),
      # In case of unavaiable version, the server returns 404 and the return
      # value is None.
      accept_statuses=[200, 404],
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
  tot_version = api.m.gitiles.download_file(
      CHROMIUM_SRC_GIT,
      CHROMIUM_VERSION_FILE,
      branch='refs/heads/main',
      step_name='Fetch ToT version',
      step_test_data=lambda: api.m.json.test_api.output({
          'value': base64.b64encode(mock_version.encode()).decode(),
      }),
  )

  api.m.step.active_result.presentation.step_text = tot_version

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


def TriggerPUprBuild(api: RecipeApi, builder: str,
                     buildset: common_pb2.GitilesCommit,
                     chrome_version: str) -> None:
  """Triggers a PUpr build.

  Args:
    builder (str): Name of the builder to trigger, e.g. chrome-pupr-generator.
    buildset (GitilesCommit): Buildset of the build.
    chrome_version (str): Version of the Chrome browser.
  """
  triggers_properties = [{
      'gitiles': {
          'repo': f'https://{buildset.host}/{buildset.project}',
          'ref': f'refs/tags/{chrome_version}',
          'revision': buildset.id,
      }
  }]
  TriggerCrosBuild(
      api,
      bucket='pupr',
      builder=builder,
      properties={
          'chrome_version': chrome_version,
          # Emulate a GitilesTrigger for the expected inputs of CrOS's pupr.
          'triggers': triggers_properties,
      },
  )


def TriggerCrosBuild(api: RecipeApi, properties: dict, bucket: str,
                     builder: str) -> None:
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

  result = api.m.buildbucket.schedule([request])[0]
  if result:
    s = api.step('Scheduled PUpr build: %s' % builder, None)
    s.presentation.step_text = 'ci.chromium.org/b/%d' % result.id
    s.presentation.logs['triggers_properties'] = str(properties)


def TriggerChromeBuild(
    api: RecipeApi, builder: str,
    buildset: common_pb2.GitilesCommit) -> Optional[build_pb2.Build]:
  with api.step.nest(f'scheduling {builder}') as presentation:
    request = api.buildbucket.schedule_request(
        project='chrome',
        bucket='ci',
        builder=builder,
        gitiles_commit=buildset,
        fields=BUILD_FIELDS_TO_RETRIEVE,
    )
    try:
      return api.buildbucket.schedule([request])[0]
    except api.step.InfraFailure:  # pragma: nocover
      presentation.status = api.step.EXCEPTION
      return None


def TriggerChromeBuilds(
    api: RecipeApi, builders: List[str],
    buildset: common_pb2.GitilesCommit) -> List[build_pb2.Build]:
  with api.step.nest('trigger browser side builders') as presentation:
    builds = []
    for builder in builders:
      build = TriggerChromeBuild(api, builder, buildset)
      if build:
        builds.append(build)
      else:  # pragma: nocover
        presentation.status = api.step.EXCEPTION
        presentation.step_summary_text = 'Some builds failed to create.'
    return builds


def FetchCommitTags(api: RecipeApi,
                    buildset: common_pb2.GitilesCommit) -> Optional[str]:
  tags = api.git.ls_remote(
      [], repo_url=f'https://{buildset.host}/{buildset.project}', opts=['-t'])
  for t in tags:
    if t.hash == buildset.id:
      return t.ref.removeprefix('refs/tags/')
  return None  # pragma: nocover


def RunSteps(api: RecipeApi, _: InputProperties) -> result_pb2.RawResult:
  # * On a trunk
  #   -> triggers the atomic uprev (to the main branch)
  # * On a release branches:
  #   - at the root (the last segment in the version string is zero):
  #     -> triggers both the atomic uprev (to the main branch) and the chrome
  #        branch (to the release branch if any).
  #   - at the other points:
  #     -> triggers the chrome uprev (to the release branch) only.

  # The last number of 4 segments of the chrome version. This is called "build
  # number" or "patch number" (varies with document). This code uses
  # |patch_number|.
  with api.step.nest('extracting Chrome version') as step:
    chrome_version = FetchCommitTags(api,
                                     api.buildbucket.build.input.gitiles_commit)
    step.step_summary_text = f'Chrome version: {chrome_version}'
  try:
    patch_number = int(chrome_version.split('.')[3])
  except (IndexError, ValueError, AttributeError):  # pragma: nocover
    return result_pb2.RawResult(
        status=common_pb2.INFRA_FAILURE,
        summary_markdown=f'Invalid chrome version {chrome_version}')

  if IsVersionOnReleaseBranches(api, chrome_version):
    # On release branch, we do Chrome (non-atomic) uprev to the branch on CrOS
    # repo.
    TriggerPUprBuild(api, 'chrome-pupr-generator',
                     api.buildbucket.build.input.gitiles_commit, chrome_version)

    # If |patch_number| is zero, it's the root of branches and it's ok to
    # uprev.
    if patch_number == 0:
      # Even on a release branch, if it's at the root of the release branch, we
      # do Chrome (non-atomic) uprev to the ToT on CrOS repo.
      TriggerUprevBuilds(api, api.buildbucket.build.input.gitiles_commit,
                         chrome_version)
      summary_markdown = 'On trunk (at the root of release branch)'
    else:
      summary_markdown = 'On release branches'

    return result_pb2.RawResult(status=common_pb2.SUCCESS,
                                summary_markdown=summary_markdown)

  # On a non-release branch, we do Chrome (non-atomic) uprev to the ToT on CrOS
  # repo.
  TriggerUprevBuilds(api, api.buildbucket.build.input.gitiles_commit,
                     chrome_version)

  if patch_number == 0:
    summary_markdown = 'On trunk (at the root of non-release branch)'
  else:
    summary_markdown = 'On non-release branches'

  return result_pb2.RawResult(status=common_pb2.SUCCESS,
                              summary_markdown=summary_markdown)


def TriggerUprevBuilds(api: RecipeApi, buildset: common_pb2.GitilesCommit,
                       chrome_version: str) -> None:
  # Wait for 3 minutes to ensure critical pre-uprev builders are started.
  api.time.sleep(180)
  # Launch non-critical pre-uprev builders for new orchestrator flow.
  preuprevs = TriggerChromeBuilds(api, CHROME_SIDE_BUILDERS, buildset)
  TriggerPUprBuild(api, 'lacros-ash-atomic-pupr-generator', buildset,
                   chrome_version)
  TriggerCrosBuild(api, {}, 'infra', 'collect-preuprev-test-results')
  # Wait for new pre-uprev builders to complete.
  api.buildbucket.collect_builds(
      ToBuilderIds(preuprevs), fields=BUILD_FIELDS_TO_RETRIEVE,
      timeout=PRE_UPREV_TEST_TIMEOUT)


def GenTests(api: RecipeTestApi):

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
            ),
        ),
    )

    return api.buildbucket.build(build) + api.step_data(
        'extracting Chrome version.git ls-remote',
        api.raw_io.stream_output_text(f'{commit}\trefs/tags/{chrome_version}',
                                      stream='stdout'))

  yield api.test(
      'version_at_root_on_release_branches',
      trigger(chrome_version='97.0.1290.0'),
      api.post_process(post_process.MustRun,
                       'Scheduled PUpr build: chrome-pupr-generator'),
      api.post_process(
          post_process.MustRun,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator'),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'version_on_release_branches',
      trigger(chrome_version='97.0.1290.1'),
      api.post_process(post_process.MustRun,
                       'Scheduled PUpr build: chrome-pupr-generator'),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'version_on_non_release_branch',
      trigger(chrome_version='98.0.1234.1'),
      api.post_process(
          post_process.MustRun,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator'),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'version_on_trunk',
      trigger(chrome_version='98.0.1234.0'),
      api.post_process(
          post_process.MustRun,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator'),
      api.post_process(
          post_process.LogContains,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator',
          'triggers_properties', ['refs/tags/98.0.1234.0']),
      api.post_process(post_process.MustRun,
                       'Scheduled PUpr build: collect-preuprev-test-results'),
  )
