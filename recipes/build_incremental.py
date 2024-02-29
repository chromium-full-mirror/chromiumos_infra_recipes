# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget incrementally."""

from typing import Generator, Optional

# pylint: disable=import-error
from PB.chromiumos import common as common_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.incremental.incremental import IncrementalProperties, ErrorType
from PB.recipe_engine.result import RawResult

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'build_plan',
    'cros_build_api',
    'cros_infra_config',
    'cros_prebuilts',
    'cros_sdk',
    'easy',
    'git',
    'incremental',
    'repo',
    'src_state',
    'workspace_util',
]

REPO_SYNC_JOBS = 64

PROPERTIES = IncrementalProperties

def RunSteps(api: RecipeApi,
             properties: IncrementalProperties) -> Optional[RawResult]:
  with api.build_menu.configure_builder() as config, \
    api.build_menu.setup_workspace(cherry_pick_changes=False):

    # Disable cros clean-outdated-pkgs via ENV var, if necessary.
    cop_enabled = properties.cop_enabled
    if not cop_enabled:
      with api.context(env_suffixes={'CROS_CLEAN_OUTDATED_PKGS': '0'}):
        return DoRunSteps(api, config, properties)
    else:
      return DoRunSteps(api, config, properties)


def DoRunSteps(api: RecipeApi, config: BuilderConfig,
               properties: IncrementalProperties) -> Optional[RawResult]:
  """Tests reliability of incremental build by performing two builds.

  First, revert the checkout back in time, build_packages for that old state,
  generating local artifacts, and move the checkout back to ToT.
  Then, attempt to build from the current state with old state intact.

  Args:
    api: The recipe API.
    config: The BuilderConfig for this incremental builder.
    properties: Input properties for this build.

  Returns:
    A list of relevant packages built.
  """
  failing_build_exception = None
  error_type = ErrorType.UNKNOWN

  build_time_delta = properties.build_time_delta
  if not build_time_delta:
    raise StepFailure('build_time_delta input property is empty')

  relevant_pkgs = None
  gerrit_changes = api.cros_infra_config.gerrit_changes
  if properties.run_relevancy_check:
    # TODO(sfrolov): remove manual check when cros query is in cq-orchestrator.
    _build_target = common_pb2.BuildTarget(
        name=api.build_menu.build_target.name,
        profile=common_pb2.Profile(name='base'))
    _builder_config = BuilderConfig(build_target=_build_target)
    relevant_builder_configs = api.build_plan.get_relevant_builder_configs(
        [_builder_config], gerrit_changes)

    if not relevant_builder_configs:
      return RawResult(status=common.SUCCESS,
                       summary_markdown='Build was not relevant.')

  try:
    _relevant_pkgs = api.incremental.DoOldBuild(api, config, properties)
    relevant_pkgs = relevant_pkgs or _relevant_pkgs
    old_build_successful = True
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (as stated above there is value in uploading the artifact even
    # in cases of build failure for debug purposes).
    failing_build_exception = sf
    old_build_successful = False
    error_type = ErrorType.NON_INCREMENTAL

  # Attempt to build the current snapshot.
  if not failing_build_exception:
    try:
      api.workspace_util.apply_changes(changes=gerrit_changes,
                                       ignore_missing_projects=False)
      # TODO(sfrolov): remove update_chroot call when cros_sdk revamp is ready.
      api.cros_sdk.update_chroot(
          toolchain_targets=[api.build_menu.build_target],
          build_source=config.build.sdk_update.compile_source)

      # Get the prebuilts metadata to use with the current snapshot.
      branch = 'green' if properties.use_llfg else 'snapshot'
      manifest_dir = api.src_state.workspace_path.join('.repo', 'manifests')
      remotes = api.git.ls_remote([f'refs/remotes/origin/{branch}'],
                                  repo_url=manifest_dir)
      current_commit_hash = remotes[0].hash if remotes else None
      current_commit = GitilesCommit(
          host=api.src_state.gitiles_commit.host,
          project=api.src_state.gitiles_commit.project, id=current_commit_hash)
      package_indexes = api.cros_prebuilts.get_package_index_info(
          config.artifacts.prebuilts_gs_bucket,
          snapshot=current_commit if current_commit_hash else None)

      # b/321760005: toolchain files like `package.provided` may need to be
      # updated.
      api.build_menu.bootstrap_sysroot(config=config)
      api.build_menu.install_packages(config=config, packages=relevant_pkgs,
                                      package_indexes=package_indexes)
    except StepFailure as sf:
      failing_build_exception = sf

  if failing_build_exception and old_build_successful:
    # If first build succeeded, and second one failed, the error is incremental.
    error_type = ErrorType.INCREMENTAL

  api.easy.set_properties_step(step_name='set incremental failure',
                               error_type=error_type)

  # Finally, if there was an exception caught above in building the image, but
  # the upload succeeded, raise that exception.
  if failing_build_exception and old_build_successful:
    raise failing_build_exception  # pylint: disable=raising-bad-type
  return None


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  # Normal Build.
  yield api.build_menu.test(
      'inc-build',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          IncrementalProperties(**{'build_time_delta': '7.days.ago'})),
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.post_check(post_process.DoesNotRun,
                     'Disable cros clean-outdated-pkgs'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.MustRun, 'install toolchain (2)'),
      api.post_check(post_process.MustRun, 'install packages (2)'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
      api.post_check(post_process.DoesNotRun, 'install packages (3)'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests (2)'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.PropertyEquals, 'error_type',
                     ErrorType.UNKNOWN),
      build_target='amd64-generic',
      status='SUCCESS',
  )
  # Normal Build with LLFG.
  yield api.build_menu.test(
      'inc-build-llfg',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          IncrementalProperties(**{
              'build_time_delta': '7.days.ago',
              'use_llfg': True
          })),
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.post_check(post_process.DoesNotRun,
                     'Disable cros clean-outdated-pkgs'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.MustRun, 'install packages (2)'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
      api.post_check(post_process.DoesNotRun, 'install packages (3)'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests (2)'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.PropertyEquals, 'error_type',
                     ErrorType.UNKNOWN),
      build_target='amd64-generic',
      status='SUCCESS',
  )

  # Normal Build without cros clean-outdated-pkgs.
  yield api.build_menu.test(
      'inc-build-no-cop',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          IncrementalProperties(**{'build_time_delta': '7.days.ago'})),
      api.properties(IncrementalProperties(**{'cop_enabled': False})),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'update sdk (2)'),
      api.post_check(post_process.MustRun, 'install packages (2)'),
      api.post_check(post_process.DoesNotRun, 'update sdk (3)'),
      api.post_check(post_process.DoesNotRun, 'install packages (3)'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests (2)'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.PropertyEquals, 'error_type',
                     ErrorType.UNKNOWN),
      build_target='amd64-generic',
      status='SUCCESS',
  )

  # Build with install-packages failure in first build, must be successful.
  yield api.build_menu.test(
      'inc-install-packages-success',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          IncrementalProperties(**{'build_time_delta': '7.days.ago'})),
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.PropertyEquals, 'error_type',
                     ErrorType.NON_INCREMENTAL),
      api.build_menu.set_build_api_return(
          'install packages', endpoint='SysrootService/InstallPackages',
          retcode=2,
          data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
      ), build_target='amd64-generic', status='SUCCESS')

  # Build with install-packages failure in second build, must be failure.
  yield api.build_menu.test(
      'inc-install-packages-2-fail',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          IncrementalProperties(**{'build_time_delta': '7.days.ago'})),
      api.properties(IncrementalProperties(**{'cop_enabled': True})),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.PropertyEquals, 'error_type',
                     ErrorType.INCREMENTAL),
      api.build_menu.set_build_api_return(
          'install packages (2)', endpoint='SysrootService/InstallPackages',
          retcode=2,
          data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
      ), build_target='amd64-generic', status='FAILURE')

  # Build without build_time_delta
  yield api.build_menu.test(
      'inc-no-build-time-delta-failure',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'install packages'),
      build_target='amd64-generic',
      status='FAILURE',
  )

  # Build with pointless build check enabled.
  yield api.build_menu.test(
      'inc-pointless-build-check',
      api.buildbucket.ci_build(builder='cq-orchestrator'),
      api.cros_build_api.set_api_return(
          parent_step_name='',
          endpoint='RelevancyService/GetRelevantBuildTargets', data='{}'),
      api.properties(
          IncrementalProperties(**{'build_time_delta': '7.days.ago'})),
      api.properties(IncrementalProperties(**{'run_relevancy_check': True})),
      api.post_check(post_process.DoesNotRun, 'install packages'),
      build_target='amd64-generic',
      status='SUCCESS',
  )
