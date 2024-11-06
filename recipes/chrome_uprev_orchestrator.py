# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to orchestrate necessary builders and pupr for Chrome uprev."""

import base64

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
    'recipe_engine/step',
]

CHROMIUM_SRC_GIT = 'https://chromium.googlesource.com/chromium/src.git/'
CHROMIUM_VERSION_FILE = 'chrome/VERSION'


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


def TriggerPUprBuild(api: RecipeApi, properties: InputProperties,
                     builder: str) -> None:
  """Triggers a PUpr build.

  Args:
    builder (str): Name of the builder to trigger, e.g. chrome-pupr-generator.
    properties (InputProperties): properties of the current orchestrator.
  """
  if not properties.triggers:  # pragma: nocover
    raise ValueError('triggers are empty')
  properties_trigger = properties.triggers[0].gitiles
  triggers_properties = [{
      'gitiles': {
          'repo': properties_trigger.repo,
          'ref': properties_trigger.ref,
          'revision': properties_trigger.revision,
      }
  }]
  TriggerCrosBuild(
      api,
      bucket='pupr',
      builder=builder,
      properties={
          'chrome_version': properties.chrome_version,
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


def RunSteps(api: RecipeApi,
             properties: InputProperties) -> result_pb2.RawResult:
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
  try:
    patch_number = int(properties.chrome_version.split('.')[3])
  except (IndexError, ValueError):  # pragma: nocover
    return result_pb2.RawResult(
        status=common_pb2.INFRA_FAILURE,
        summary_markdown=f'Invalid chrome version {properties.chrome_version}')

  if IsVersionOnReleaseBranches(api, properties.chrome_version):
    # On release branch, we do Chrome (non-atomic) uprev to the branch on CrOS
    # repo.
    TriggerPUprBuild(api, properties, 'chrome-pupr-generator')

    # If |patch_number| is zero, it's the root of branches and it's ok to
    # uprev.
    if patch_number == 0:
      # Even on a release branch, if it's at the root of the release branch, we
      # do Chrome (non-atomic) uprev to the ToT on CrOS repo.
      TriggerUprevBuilds(api, properties)
      summary_markdown = 'On trunk (at the root of release branch)'
    else:
      summary_markdown = 'On release branches'

    return result_pb2.RawResult(status=common_pb2.SUCCESS,
                                summary_markdown=summary_markdown)

  # On a non-release branch, we do Chrome (non-atomic) uprev to the ToT on CrOS
  # repo.
  TriggerUprevBuilds(api, properties)

  if patch_number == 0:
    summary_markdown = 'On trunk (at the root of non-release branch)'
  else:
    summary_markdown = 'On non-release branches'

  return result_pb2.RawResult(status=common_pb2.SUCCESS,
                              summary_markdown=summary_markdown)


def TriggerUprevBuilds(api: RecipeApi, properties: InputProperties) -> None:
  TriggerPUprBuild(api, properties, 'lacros-ash-atomic-pupr-generator')
  TriggerCrosBuild(api, {}, 'infra', 'collect-preuprev-test-results')


def GenTests(api: RecipeTestApi):

  def GetTrigger(chrome_version: str) -> dict:
    return [{
        'gitiles': {
            'ref': 'refs/tags/%s' % chrome_version,
            'repo': 'https://chromium.googlesource.com/chromium/src',
            'revision': '8302b1a80de0995f146605740417cdf78e381157',
        }
    }]

  yield api.test(
      'version_at_root_on_release_branches',
      api.properties(chrome_version='97.0.1290.0',
                     triggers=GetTrigger('97.0.1290.0')),
      api.post_process(post_process.MustRun,
                       'Scheduled PUpr build: chrome-pupr-generator'),
      api.post_process(
          post_process.MustRun,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'version_on_release_branches',
      api.properties(chrome_version='97.0.1290.1',
                     triggers=GetTrigger('97.0.1290.1')),
      api.post_process(post_process.MustRun,
                       'Scheduled PUpr build: chrome-pupr-generator'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'version_on_non_release_branch',
      api.properties(chrome_version='98.0.1234.1',
                     triggers=GetTrigger('98.0.1234.1')),
      api.post_process(
          post_process.MustRun,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'version_on_trunk',
      api.properties(chrome_version='98.0.1234.0',
                     triggers=GetTrigger('98.0.1234.0')),
      api.post_process(
          post_process.MustRun,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator'),
      api.post_process(
          post_process.LogContains,
          'Scheduled PUpr build: lacros-ash-atomic-pupr-generator',
          'triggers_properties', ['refs/tags/98.0.1234.0']),
      api.post_process(post_process.MustRun,
                       'Scheduled PUpr build: collect-preuprev-test-results'),
      api.post_process(post_process.DropExpectation),
  )
