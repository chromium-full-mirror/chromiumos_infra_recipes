# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building an AFDO benchmark profile."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_relevance',
    'cros_sdk',
    'cros_version',
    'easy',
    'sysroot_util',
    'workspace_util',
]

from google.protobuf import json_format as json_pb

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.afdo_process import AfdoProcessProperties

PROPERTIES = AfdoProcessProperties


def RunSteps(api, properties):
  build_target = properties.build_target
  force_relevant_build = properties.force_relevant_build
  input_artifacts = properties.input_artifacts

  config = api.cros_infra_config.configure_builder(
      api.buildbucket.gitiles_commit,
      api.buildbucket.build.input.gerrit_changes)
  if not config:
    # No config found, already logged.
    return

  api.cros_sdk.set_use_flags(config.build.use_flags)
  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    DoRunSteps(api, build_target, config, api.cros_infra_config.gitiles_commit,
               api.cros_infra_config.gerrit_changes, force_relevant_build,
               input_artifacts)


def DoRunSteps(api, build_target, config, gitiles_commit, gerrit_changes,
               force_relevant_build, input_artifacts):

  # Set up source checkouts.
  api.workspace_util.sync_to_commit(
      staging=config.general.environment == BuilderConfig.General.STAGING)
  # Apply any appropriate gerrit_changes.
  api.workspace_util.apply_changes()

  # If we received any extra input_artifacts, add them to the values from the
  # config.
  if input_artifacts:
    config.artifacts.input_artifacts.extend(input_artifacts)

  # Early check to see if the build is pointless. (No chroot nor sysroot yet.)
  relevance = api.sysroot_util.update_for_artifact_build(
      None, config.artifacts, force_relevance=force_relevant_build)
  if relevance == Relevance.POINTLESS:
    return

  api.cros_sdk.uprev_packages(build_targets=[build_target])
  api.cros_sdk.create_chroot(version=config.general.sdk_cache_version,
                             timeout_sec=None)
  api.cros_sdk.update_chroot(
      gitiles_commit, gerrit_changes, toolchain_targets=[build_target],
      build_source=config.build.sdk_update.compile_source, timeout_sec=None)

  sysroot = None
  if gerrit_changes:
    sysroot = api.sysroot_util.create_sysroot(
        build_target, config.build.portage_profile.profile)

  # This update_for_artifact_build call will download the input artifacts into
  # the chroot.  This builder is only appropriate to use if there are no package
  # builds needed prior to making artifacts, and those artifacts will be created
  # by the appropriate Build API Bundle() calls in upload_artifacts (below).
  api.sysroot_util.update_for_artifact_build(
      api.cros_sdk.chroot, config.artifacts, force_relevance=True,
      name='prepare artifacts final')

  api.easy.set_property_step('chromeos_version',
                             str(api.cros_version.read_workspace_version()))

  api.cros_artifacts.upload_artifacts(
      config.id.name, build_target, config.id.type,
      config.artifacts.artifacts_gs_bucket,
      artifacts_info=config.artifacts.artifacts_info,
      sysroot=sysroot, chroot=api.cros_sdk.chroot)

  with api.step.nest('validate SDK reuse') as presentation:
    # If there are no gerrit changes, then the SDK remains clean.  If there are
    # gerrit changes, determine if they affect the SDK.
    if gerrit_changes:
      step_text = 'Clean: changes do not affect SDK'
      if api.cros_relevance.is_depgraph_affected(
          gerrit_changes, gitiles_commit,
          dep_graph=api.cros_relevance.get_dependency_graph(
              build_target=build_target, chroot=api.cros_sdk.chroot,
              packages=config.build.install_packages.packages).sdk):
        step_text = 'Dirty: changes affect SDK'
        api.cros_sdk.mark_sdk_as_dirty()
    else:
      step_text = 'Clean: no changes'
    presentation.step_text = step_text

  api.bot_cost.set_build_cost(api.buildbucket.build.id, 'large')


def GenTests(api):
  mock_CLs = [
      common_pb2.GerritChange(change=1234),
      common_pb2.GerritChange(change=2341),
  ]

  def test_build(builder='benchmark-afdo-process', build_target='eve',
                 gerrit_changes=True):
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(
        project='chromeos', bucket='toolchain', builder=builder, tags=[{
            'key': 'parent_buildbucket_id',
            'value': 'parent_id'
        }])
    if gerrit_changes:
      build.input.gerrit_changes.extend(mock_CLs)
    ret = api.buildbucket.build(build)
    if build_target:
      ret += api.properties(build_target={'name': build_target})
    return ret

  yield api.test('basic', test_build())

  yield api.test('no-changes', test_build(gerrit_changes=False))

  yield api.test(
      'pointless', test_build(),
      api.step_data(
          'prepare artifacts.call chromite.api.ArtifactsService/'
          'PrepareForBuild.read output file',
          api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield api.test(
      'with-input-artifacts', test_build(),
      api.properties(input_artifacts=[{
          'input_artifact_type':
              BuilderConfig.Artifacts.IMAGE_ZIP,
          'input_artifact_gs_locations':
              ['chromeos-image-archive/BUILDER/VERSION-BUILD_ID']
      }]))

  yield api.test(
      'forced-pointless', test_build(),
      api.properties(force_relevant_build=True, input_artifacts=[{
          'input_artifact_type':
              BuilderConfig.Artifacts.IMAGE_ZIP,
          'input_artifact_gs_locations':
              ['chromeos-image-archive/BUILDER/VERSION-BUILD_ID']
      }]),
      api.step_data(
          'prepare artifacts.call chromite.api.ArtifactsService/'
          'PrepareForBuild.read output file',
          api.file.read_raw(content='{"build_relevance": "POINTLESS"}')))

  yield api.test('builder-no-longer-exists',
                 test_build(builder='no-such-builder'))
