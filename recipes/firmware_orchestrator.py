# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures."""

import base64
import collections
import datetime
import json
import re
from typing import Any, Dict, Generator, List, Mapping, Optional, Tuple

from google.protobuf import json_format

from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.firmware_orchestrator import FirmwareOrchestratorProperties
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts
from RECIPE_MODULES.chromeos.cros_version.version import Version
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

# Minimum branch build version where firmware orchestrator is supported.
_MIN_FIRMWARE_ORCHESTRATOR_BUILD = 15217

# Matches milestone firmware branches such as firmware-R158-16868.3.B.
_MILESTONE_BRANCH_RE = re.compile(r'^firmware-R\d+-\d+(?:\.\d+)*\.B$')

# Matches board-level firmware archives in child build output properties.
_BOARD_FIRMWARE_TARBALL_RE = re.compile(
    r'^(?P<board>[^/]+)/firmware_from_source\.tar\.bz2$')

DEPS = [
    'bot_cost',
    'build_reporting',
    'cros_artifacts',
    'cros_infra_config',
    'cros_source',
    'cros_version',
    'depot_tools/gsutil',
    'easy',
    'gerrit',
    'git',
    'orch_menu',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'src_state',
    'test_util',
]

PROPERTIES = FirmwareOrchestratorProperties


def _source_sort_key(source: Tuple[str, str, str]) -> Tuple[int, str]:
  """Orders non-EC tarballs before EC tarballs so EC binaries take precedence.

  Args:
    source: Tuple of (child_builder_name, gs_bucket, gs_object_path).

  Returns:
    Sort key placing non-EC builders before EC/Zephyr builders.
  """
  builder_name = source[0]
  is_ec = '-ec-' in builder_name or '-zephyr-' in builder_name
  return (1 if is_ec else 0, builder_name)


def _merge_and_publish_firmware(
    api: RecipeApi,
    start_time: datetime.datetime,
) -> None:
  """Merges milestone child firmware_from_source tarballs and publishes to DLM.

  Combines per-board <board>/firmware_from_source.tar.bz2 archives produced by
  completed milestone child builders, uploads each merged archive under
  <board>/<branch>/<platform_version>/<board>/firmware_from_source.tar.bz2,
  and publishes a FIRMWARE_IMAGE_ARCHIVE BuildReport to Pub/Sub for DLM.

  Args:
    api: Recipe API instance.
    start_time: UTC timestamp when the orchestrator build started.
  """
  branch = api.git.extract_branch(api.orch_menu.gitiles_commit.ref,
                                  api.orch_menu.gitiles_commit.ref)
  if (api.cv.active or not _MILESTONE_BRANCH_RE.match(branch) or
      api.orch_menu.builds_status.fatal_failures):
    return

  sources_by_board: Dict[str, List[Tuple[str, str, str]]] = (
      collections.defaultdict(list))
  bcs_version: Optional[Version] = None
  for build in api.orch_menu.builds_status.testable_builds:
    props = json_format.MessageToDict(build.output.properties)
    if not bcs_version and props.get('chromeos_version'):
      bcs_version = Version.from_string(props['chromeos_version'])
    artifacts = props.get('artifacts') or {}
    gs_bucket = artifacts.get('gs_bucket')
    gs_path = artifacts.get('gs_path')
    tarballs = (artifacts.get('files_by_artifact') or
                {}).get('FIRMWARE_TARBALL') or []
    if gs_bucket and gs_path:
      for rel_path in tarballs:
        match = _BOARD_FIRMWARE_TARBALL_RE.match(rel_path)
        if match:
          sources_by_board[match.group('board')].append(
              (build.builder.builder, gs_bucket, f'{gs_path}/{rel_path}'))

  with api.step.nest('publish merged firmware') as pres:
    if not sources_by_board or not bcs_version:
      pres.step_text = 'No board firmware tarballs to publish'
      return

    publish_bucket = ('staging-chromeos-image-archive'
                      if api.cros_infra_config.is_staging else
                      'firmware-image-archive')
    api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_FIRMWARE, None)
    root_dir = api.path.mkdtemp(prefix='publish_fw_')

    for board in sorted(sources_by_board):
      ordered_sources = sorted(sources_by_board[board], key=_source_sort_key)
      with api.step.nest(board) as board_step:
        board_work_dir = root_dir / board
        stage_dir = board_work_dir / 'stage'
        rel_tarball = f'{board}/firmware_from_source.tar.bz2'
        merged_tar = stage_dir / rel_tarball
        api.file.ensure_directory('create stage dir', stage_dir / board)

        if len(ordered_sources) == 1:
          child_builder, src_bucket, src_obj = ordered_sources[0]
          api.gsutil.download(
              src_bucket,
              src_obj,
              merged_tar,
              name=f'download {child_builder}',
              timeout=15 * 60,
          )
        else:
          extract_dir = board_work_dir / 'extract'
          api.file.ensure_directory('create extract dir', extract_dir)
          for idx, (child_builder, src_bucket,
                    src_obj) in enumerate(ordered_sources):
            local_tar = board_work_dir / f'{idx}.tar.bz2'
            api.gsutil.download(
                src_bucket,
                src_obj,
                local_tar,
                name=f'download {child_builder}',
                timeout=15 * 60,
            )
            api.step(
                f'extract {child_builder}',
                ['tar', '-xjf', local_tar, '-C', extract_dir],
            )
          entries = sorted(
              api.path.basename(p) for p in api.file.listdir(
                  'list merged files',
                  extract_dir,
                  test_data=['ec', f'image-{board}.bin'],
              ))
          api.step(
              'create merged tarball',
              ['tar', '-cjf', merged_tar, '-C', extract_dir, *entries],
          )

        gs_path = f'{board}/{branch}/{bcs_version.platform_version}'
        api.gsutil.upload(
            merged_tar,
            publish_bucket,
            f'{gs_path}/{rel_tarball}',
            name='upload merged tarball',
            timeout=15 * 60,
        )
        board_step.links['gs publish dir'] = (
            'https://console.cloud.google.com/storage/browser/'
            f'{publish_bucket}/{gs_path}/{board}')

        api.build_reporting.reset_build_report(board)
        build_report = api.build_reporting.merged_build_report
        step_info = build_report.steps.info[api.build_reporting.step_as_str(
            BuildReport.StepDetails.STEP_OVERALL)]
        step_info.order = 1
        step_info.status = BuildReport.StepDetails.STATUS_SUCCESS
        step_info.runtime.begin.FromDatetime(start_time)
        step_info.runtime.end.FromDatetime(api.time.utcnow())
        build_report.status.value = BuildReport.BuildStatus.SUCCESS
        build_config = build_report.config
        build_config.branch.name = branch
        api.build_reporting.add_version_msg(
            build_config,
            BuildReport.BuildConfig.VERSION_KIND_MILESTONE,
            str(bcs_version.milestone),
        )
        api.build_reporting.add_version_msg(
            build_config,
            BuildReport.BuildConfig.VERSION_KIND_PLATFORM,
            bcs_version.platform_version,
        )
        api.build_reporting.publish_build_artifacts(
            UploadedArtifacts(publish_bucket, gs_path,
                              {'FIRMWARE_TARBALL': [rel_tarball]}),
            stage_dir,
        )
        api.file.rmtree('clean up board dir', board_work_dir)


def RunSteps(
    api: RecipeApi,
    _properties: FirmwareOrchestratorProperties) -> result_pb2.RawResult:
  with api.bot_cost.build_cost_context():
    start_time = api.time.utcnow()
    is_staging = api.cros_infra_config.is_staging

    commit = api.src_state.gitiles_commit
    if api.orch_menu.gitiles_commit:
      commit = api.orch_menu.gitiles_commit
    branch = api.git.extract_branch(commit.ref, commit.ref)

    named_builder = '{}{}'.format('staging-' if is_staging else '',
                                  branch.replace('.B', '-cq'))
    named_child_config = api.cros_infra_config.get_builder_config(
        named_builder, missing_ok=True)
    api.easy.set_properties_step(manifest_branch=branch)
    config = None
    if named_child_config and api.buildbucket.build.builder.builder != named_builder:
      config = api.cros_source.configure_builder()
      api.easy.set_properties_step(child_verifier=named_builder)
      api.orch_menu.schedule_wait_build(named_builder, await_completion=True,
                                        check_failures=True,
                                        step_name='launch child')
      # This is used to run android firmware builders after the rest with a distinct version number.
      api.orch_menu.run_follow_on_builders(config=config)

      return api.orch_menu.create_recipe_result()

    with api.step.nest('launch child') as pres:
      pres.step_text = 'Builder {} is not configured, attempting to launch dynamic children'.format(
          named_builder)
      if api.orch_menu.bump_version:
        branch_match = re.match(
            r'firmware-(?:.*-)?(\d+)(?:\.[0-9]+)*\.B(?:-.+)?$', branch)
        if branch_match and int(
            branch_match.group(1)) < _MIN_FIRMWARE_ORCHESTRATOR_BUILD:
          raise StepFailure(
              f'Firmware orchestrator is only supported on branches >= '
              f'{_MIN_FIRMWARE_ORCHESTRATOR_BUILD} (firmware-nissa and newer); '
              f'current branch is {branch}.')
    with api.orch_menu.setup_orchestrator() as config:
      if config:
        api.easy.set_properties_step(child_verifier='dynamic')
        api.orch_menu.plan_and_run_children()
        _merge_and_publish_firmware(api, start_time)

      # This is used to run android firmware builders after the rest with a distinct version number.
      api.orch_menu.run_follow_on_builders(config=config)

      return api.orch_menu.create_recipe_result()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  test_base = 'firmware-board-5555'
  test_branch = f'{test_base}.B'
  test_builder = f'{test_base}-cq'

  def test(name: str, *args: Any, **kwargs: Any) -> TestData:
    default_builder = ('staging-firmware-cq-orchestrator'
                       if kwargs.get('bucket') == 'staging' else
                       'firmware-cq-orchestrator')
    kwargs.setdefault('builder', default_builder)
    kwargs.setdefault('cq', True)
    branch = kwargs.pop('branch', test_branch)
    child_specs = kwargs.pop('child_specs', ['dynamic-child'])
    collect_builds = kwargs.pop('collect_builds', [])
    expected_properties = kwargs.pop('expected_properties', {})

    # Mock the ref on the gitiles_commit property
    input_props = kwargs.get('input_properties', {})
    input_props.setdefault('$chromeos/src_state', {})

    # Pass gitiles_commit to buildbucket explicitly via individual fields
    kwargs[
        'git_repo'] = 'https://chromium.googlesource.com/chromiumos/manifest-internal'
    kwargs.setdefault('revision', 'deadbeef' * 10)
    kwargs['git_ref'] = f'refs/heads/{branch}'

    kwargs['input_properties'] = input_props

    child_builder_name = test_builder
    if kwargs.get('bucket') == 'staging':
      child_builder_name = f'staging-{test_builder}'

    builder_config_data = BuilderConfigs()
    # Always add the orchestrator's own config
    orch_config = builder_config_data.builder_configs.add()
    orch_config.id.name = kwargs['builder']
    for spec_name in child_specs:
      orch_config.orchestrator.child_specs.add().name = spec_name
      child_cfg = builder_config_data.builder_configs.add()
      child_cfg.id.name = spec_name
    orch_config.build.apply_gerrit_changes = True
    if not kwargs['cq']:
      orch_config.orchestrator.gitiles_commit.host = (
          'chrome-internal.googlesource.com')
      orch_config.orchestrator.gitiles_commit.project = (
          'chromeos/manifest-internal')
      orch_config.orchestrator.gitiles_commit.ref = f'refs/heads/{branch}'

    if name == 'follow-on-builders':
      followers = orch_config.orchestrator.follow_on_builders
      followers.names.extend(
          ['chromeos/firmware/firmware-android-R148-16640.2.B-branch'])
      followers.await_completion = True
      followers.rev_bump = True

    # Add the named child config only if not 'no-child' test
    if kwargs['cq'] and name not in [
        'no-child', 'bump-version', 'older-branch', 'follow-on-builders'
    ]:
      builder = builder_config_data.builder_configs.add()
      builder.id.name = child_builder_name
      # Add bucket to ensure config is valid/found
      builder.id.bucket = kwargs.get('bucket', 'cq')

    args += (api.cros_infra_config.override_builder_configs_test_data(
        builder_config_data),)

    if kwargs['cq']:
      kwargs['properties'] = expected_properties
    return api.orch_menu.test(name, *args, collect_builds=collect_builds,
                              **kwargs)

  def check_publish_message(
      check: Any,
      steps: Mapping[str, Any],
      step_name: str,
      *,
      project_id: str,
      branch: str,
      board: str,
      milestone: str,
      platform_version: str,
      gcs_uri: str,
  ) -> None:
    """Verifies the publish-message step command and BuildReport payload.

    Args:
      check: Recipe post_check assertion callable.
      steps: Executed step dictionary keyed by step name.
      step_name: Full nested name of the publish-message step.
      project_id: Expected Pub/Sub GCP project ID.
      branch: Expected BuildReport branch name.
      board: Expected BuildReport build target name.
      milestone: Expected milestone version string.
      platform_version: Expected platform version string.
      gcs_uri: Expected GCS URI for the FIRMWARE_IMAGE_ARCHIVE artifact.
    """
    step = steps[step_name]
    check(step.cmd == ['[START_DIR]/cipd/support/publish-message'])
    req = json.loads(step.stdin)
    check(req['project_id'] == project_id)
    check(req['topic_id'] == 'chromeos-builds-all')
    check(req['endpoint'] == 'us-central1-pubsub.googleapis.com:443')
    check(bool(req['ordering_key']))
    report = BuildReport.FromString(base64.b64decode(req['data']))
    check(report.type == BuildReport.BUILD_TYPE_FIRMWARE)
    check(report.status.value == BuildReport.BuildStatus.SUCCESS)
    check(report.config.branch.name == branch)
    check(report.config.target.name == board)
    versions = {v.kind: v.value for v in report.config.versions}
    check(
        versions == {
            BuildReport.BuildConfig.VERSION_KIND_MILESTONE: milestone,
            BuildReport.BuildConfig.VERSION_KIND_PLATFORM: platform_version,
        })
    check(len(report.artifacts) == 1)
    check(report.artifacts[0].type ==
          BuildReport.BuildArtifact.FIRMWARE_IMAGE_ARCHIVE)
    check(report.artifacts[0].uri.gcs == gcs_uri)

  yield test(
      'cq', api.post_check(post_process.DoesNotRun, 'set up orchestrator'),
      expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': test_builder
      })

  yield test(
      'staging-cq',
      api.post_check(post_process.DoesNotRun, 'set up orchestrator'),
      expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': f'staging-{test_builder}'
      }, bucket='staging')

  yield test(
      'cq-tagged', api.post_check(post_process.MustRun, 'set up orchestrator'),
      expected_properties={
          'manifest_branch': f'{test_base}-main',
          'child_verifier': test_builder
      }, branch=f'{test_base}-main')

  yield test(
      'failed-child',
      api.post_check(post_process.DoesNotRun, 'set up orchestrator'),
      status='FAILURE',
      expected_properties={'manifest_branch': test_branch,
                             'child_verifier': test_builder}) + \
        api.buildbucket.simulated_collect_output(
            [
                api.test_util.test_build(builder=test_builder, status='FAILURE',
                                         critical='YES').message
            ],
            step_name='launch child.collect'
        )

  yield test(
      'no-child', api.post_check(post_process.MustRun, 'set up orchestrator'),
      api.post_check(post_process.DoesNotRun,
                     'set up orchestrator.bump version'), expected_properties={
                         'manifest_branch': f'{test_base}6.B',
                         'child_verifier': 'dynamic'
                     }, branch=f'{test_base}6.B')

  yield test(
      'bump-version', api.post_check(post_process.MustRun,
                                     'set up orchestrator'),
      api.cros_version.workspace_version('R100-55556.0.0'),
      api.post_check(post_process.MustRun,
                     'set up orchestrator.bump version'), expected_properties={
                         'manifest_branch': f'{test_base}6.B',
                         'child_verifier': 'dynamic'
                     }, branch=f'{test_base}6.B', bucket='staging',
      input_properties={'$chromeos/orch_menu': {
          'bump_version': True
      }})

  yield test('older-branch',
             api.cros_version.workspace_version('R99-14505.0.0'),
             status='FAILURE', branch='firmware-brya-14505.B',
             input_properties={'$chromeos/orch_menu': {
                 'bump_version': True
             }})

  yield test(
      'follow-on-builders',
      api.post_check(
          post_process.MustRun,
          'run follow on builders.run follow on builder chromeos/firmware/firmware-android-R148-16640.2.B-branch'
      ), api.post_process(post_process.DropExpectation), expected_properties={
          'manifest_branch': test_branch,
          'child_verifier': test_builder
      })

  yield test(
      'milestone-orchestrator',
      api.post_check(
          post_process.StepCommandContains,
          'publish merged firmware.calypso.gsutil upload merged tarball',
          [
              'gs://firmware-image-archive/calypso/'
              'firmware-R158-16868.3.B/16868.3.10/'
              'calypso/firmware_from_source.tar.bz2'
          ],
      ),
      api.post_check(
          post_process.StepCommandContains,
          'publish merged firmware.rex.gsutil upload merged tarball',
          [
              'gs://firmware-image-archive/rex/'
              'firmware-R158-16868.3.B/16868.3.10/'
              'rex/firmware_from_source.tar.bz2'
          ],
      ),
      api.post_check(
          check_publish_message,
          'publish merged firmware.calypso.publish artifacts to pubsub.'
          'build status pubsub update.publish message.publish-message',
          project_id='chromeos-build-reporting',
          branch='firmware-R158-16868.3.B',
          board='calypso',
          milestone='158',
          platform_version='16868.3.10',
          gcs_uri=('gs://firmware-image-archive/calypso/'
                   'firmware-R158-16868.3.B/16868.3.10/'
                   'calypso/firmware_from_source.tar.bz2'),
      ),
      api.post_check(
          check_publish_message,
          'publish merged firmware.rex.publish artifacts to pubsub.'
          'build status pubsub update.publish message.publish-message',
          project_id='chromeos-build-reporting',
          branch='firmware-R158-16868.3.B',
          board='rex',
          milestone='158',
          platform_version='16868.3.10',
          gcs_uri=('gs://firmware-image-archive/rex/'
                   'firmware-R158-16868.3.B/16868.3.10/'
                   'rex/firmware_from_source.tar.bz2'),
      ),
      builder='firmware-R158-orchestrator',
      cq=False,
      bucket='firmware',
      branch='firmware-R158-16868.3.B',
      revision=None,
      child_specs=[
          'firmware-ec-R158-16868.3.B-branch',
          'firmware-ap-R158-16868.3.B-branch',
      ],
      collect_builds=[
          api.test_util.test_build(
              cq=False,
              build_id=8922054662172514000,
              bucket='firmware',
              builder='firmware-ec-R158-16868.3.B-branch',
              critical='YES',
              status='SUCCESS',
              output_properties={
                  'chromeos_version': 'R158-16868.3.10-1',
                  'artifacts': {
                      'gs_bucket': 'firmware-image-archive',
                      'gs_path': ('firmware-ec-R158-16868.3.B-branch/'
                                  'R158-16868.3.10-1-8922054662172514000'),
                      'files_by_artifact': {
                          'FIRMWARE_TARBALL': [
                              'calypso.EC.16868.3.10.tar.bz2',
                              'calypso/firmware_from_source.tar.bz2',
                              'rex/firmware_from_source.tar.bz2',
                          ],
                      },
                  },
              },
          ).message,
          api.test_util.test_build(
              cq=False,
              build_id=8922054662172514001,
              bucket='firmware',
              builder='firmware-ap-R158-16868.3.B-branch',
              critical='YES',
              status='SUCCESS',
              output_properties={
                  'chromeos_version': 'R158-16868.3.10-1',
                  'artifacts': {
                      'gs_bucket': 'firmware-image-archive',
                      'gs_path': ('firmware-ap-R158-16868.3.B-branch/'
                                  'R158-16868.3.10-1-8922054662172514001'),
                      'files_by_artifact': {
                          'FIRMWARE_TARBALL': [
                              'calypso/firmware_from_source.tar.bz2',
                          ],
                      },
                  },
              },
          ).message,
      ],
  )

  yield test(
      'staging-milestone-orchestrator',
      api.post_check(
          post_process.StepCommandContains,
          'publish merged firmware.rex.gsutil upload merged tarball',
          [
              'gs://staging-chromeos-image-archive/rex/'
              'firmware-R158-16868.3.B/16868.3.10/'
              'rex/firmware_from_source.tar.bz2'
          ],
      ),
      api.post_check(
          check_publish_message,
          'publish merged firmware.rex.publish artifacts to pubsub.'
          'build status pubsub update.publish message.publish-message',
          project_id='chromeos-build-reporting-dev',
          branch='firmware-R158-16868.3.B',
          board='rex',
          milestone='158',
          platform_version='16868.3.10',
          gcs_uri=('gs://staging-chromeos-image-archive/rex/'
                   'firmware-R158-16868.3.B/16868.3.10/'
                   'rex/firmware_from_source.tar.bz2'),
      ),
      api.post_process(post_process.DropExpectation),
      builder='staging-firmware-R158-orchestrator',
      cq=False,
      bucket='staging',
      branch='firmware-R158-16868.3.B',
      revision=None,
      child_specs=['staging-firmware-ec-R158-16868.3.B-branch'],
      collect_builds=[
          api.test_util.test_build(
              cq=False,
              build_id=8922054662172514000,
              bucket='staging',
              builder='staging-firmware-ec-R158-16868.3.B-branch',
              critical='YES',
              status='SUCCESS',
              output_properties={
                  'chromeos_version': 'R158-16868.3.10-1',
                  'artifacts': {
                      'gs_bucket': 'staging-chromeos-image-archive',
                      'gs_path': ('staging-firmware-ec-R158-16868.3.B-branch/'
                                  'R158-16868.3.10-1-8922054662172514000'),
                      'files_by_artifact': {
                          'FIRMWARE_TARBALL': [
                              'rex/firmware_from_source.tar.bz2',
                          ],
                      },
                  },
              },
          ).message,
      ],
  )

  yield test(
      'milestone-orchestrator-no-artifacts',
      api.post_check(
          post_process.StepTextContains,
          'publish merged firmware',
          ['No board firmware tarballs to publish'],
      ),
      api.post_process(post_process.DropExpectation),
      builder='firmware-R158-orchestrator',
      cq=False,
      bucket='firmware',
      branch='firmware-R158-16868.3.B',
      revision=None,
      child_specs=['firmware-ec-R158-16868.3.B-branch'],
      collect_builds=[
          api.test_util.test_build(
              cq=False,
              build_id=8922054662172514000,
              bucket='firmware',
              builder='firmware-ec-R158-16868.3.B-branch',
              critical='YES',
              status='SUCCESS',
              output_properties={
                  'chromeos_version': 'R158-16868.3.10-1',
              },
          ).message,
      ],
  )

  yield test(
      'tot-milestone-orchestrator',
      api.post_check(post_process.DoesNotRun, 'publish merged firmware'),
      api.post_process(post_process.DropExpectation),
      builder='firmware-R159-orchestrator',
      cq=False,
      bucket='postsubmit',
      branch='main',
      revision=None,
      child_specs=['firmware-zephyr-postsubmit'],
  )
