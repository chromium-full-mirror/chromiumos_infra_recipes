# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building public ChromiumOS images."""

from typing import Generator

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from PB.recipes.chromeos.build_chromiumos import BuildChromiumosProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'build_reporting',
    'builder_metadata',
    'cros_sdk',
    'cros_source',
    'cros_tags',
    'debug_symbols',
    'easy',
]


PROPERTIES = BuildChromiumosProperties
StepDetails = BuildReport.StepDetails


def RunSteps(api: RecipeApi, properties: BuildChromiumosProperties) -> None:
  api.easy.log_parent_step()

  with api.step.nest('check buildspec property'):
    sync_to_manifest = api.cros_source.sync_to_manifest
    if (not sync_to_manifest or
        not sync_to_manifest.manifest_gs_path.startswith(
            'gs://chromiumos-manifest-versions')):
      raise StepFailure(
          'public builder must be supplied a public buildspec in $chromeos/cros_source.syncToManifest'
      )
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_PUBLIC,
                                     api.build_menu.build_target.name)

  with api.build_reporting.publish_to_gs():
    with api.build_reporting.step_reporting(StepDetails.STEP_OVERALL,
                                            raise_on_failed_publish=True):
      with api.build_menu.configure_builder() as config, \
        api.build_menu.setup_workspace_and_chroot():
        return DoRunSteps(api, config, properties)


def DoRunSteps(api: RecipeApi, config: BuilderConfig,
               properties: BuildChromiumosProperties) -> None:
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  # After the sysroot is setup we have the package versions determined.
  api.build_reporting.publish_versions(api.build_menu.target_versions)

  failing_build_exception = None
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, env_info.packages):
      with api.step.nest('determine build and model metadata'):
        # First look up builder metadata from build-api.
        builder_metadata = api.builder_metadata.look_up_builder_metadata()
        # Then fire off a pub/sub call with that builder meta.
        api.build_reporting.publish_build_target_and_model_metadata(
            api.cros_source.manifest_branch, builder_metadata)

      with api.step.nest('try creating test service containers') as step:
        try:
          api.build_menu.create_containers(config)
        except StepFailure:
          # For now only mark the step as failed. Do not fail the build.
          step.status = api.step.FAILURE
          step.step_summary_text = 'One or more test service containers failed to build.'

      with api.build_reporting.step_reporting(StepDetails.STEP_UNIT_TESTS):
        api.build_menu.build_and_test_images(config, include_version=True)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (there is value in uploading the artifact even in cases of
    # build failure for debug purposes).
    failing_build_exception = sf

  try:
    api.build_menu.upload_artifacts(
        config, ignore_breakpad_symbol_generation_errors=failing_build_exception
        is not None)
  except StepFailure as sf:
    # If uploading artifacts threw an exception, surface that exception unless
    # build_and_test_images above threw an exception, in which case we want to
    # surface *that* exception for accuracy in reporting the build (and it's
    # likely that upload artifacts failed as a result of those previous issues).
    raise failing_build_exception or sf

  with api.step.nest('publish toolchain metadata'):
    toolchain_info = api.cros_sdk.get_toolchain_info(
        api.build_menu.build_target.name)
    api.build_reporting.publish_toolchain_info(toolchain_info)

  if properties.latest_files_gs_bucket and properties.latest_files_gs_path:
    api.build_menu.publish_latest_files(properties.latest_files_gs_bucket,
                                        properties.latest_files_gs_path)

  # Finally, if there was an exception caught above in building the image, but
  # the upload succeeded, raise that exception.
  if failing_build_exception:
    raise failing_build_exception  # pylint: disable=raising-bad-type


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  # Normal public build.
  yield api.build_menu.test(
      'public-build',
      api.properties(
          **{
              'latest_files_gs_bucket':
                  'chromiumos-image-archive',
              'latest_files_gs_path':
                  '{target}-public',
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromiumos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
          }),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-1234.56.0.gsutil write gs://chromiumos-image-archive/kukui-public/LATEST-1234.56.0'
      ),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-main.gsutil write gs://chromiumos-image-archive/kukui-public/LATEST-main'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'upload build report to GS.gsutil write build_report.json to GS',
          [
              'gs://chromeos-releases-test/kukui-public-main/R99-1234.56.0-101-8945511751514863184/build_report.json'
          ],
      ),
      build_target='kukui',
      builder='kukui-public-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'no-buildspec',
      api.post_check(post_process.StepFailure, 'check buildspec property'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-public-main',
      bucket='release',
      status='FAILURE',
  )

  yield api.build_menu.test(
      'wrong-buildspec',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromeos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-public-release.{cros-version}',
              },
          }),
      api.post_check(post_process.StepFailure, 'check buildspec property'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-public-main',
      bucket='release',
      status='FAILURE',
  )

  yield api.build_menu.test(
      'public-build-staging',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromiumos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-public-release.{cros-version}',
              },
          }),
      build_target='staging-eve',
      builder='staging-eve-public-main',
      bucket='release',
  )

  # Public build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromiumos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-public-release.{cros-version}',
              },
          }),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun,
                     'upload artifacts.publish artifacts'),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      bucket='release',
      builder='kukui-public-main',
      build_target='kukui',
      status='FAILURE',
  )

  # Public build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromiumos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-public-release.{cros-version}',
              },
          }),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      bucket='release',
      builder='kukui-public-main',
      build_target='kukui',
      status='INFRA_FAILURE',
  )

  # Public build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromiumos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-public-release.{cros-version}',
              },
          }),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      bucket='release',
      builder='kukui-public-main',
      build_target='kukui',
      status='FAILURE',
  )

  # Public build with container creation failure.
  yield api.build_menu.test(
      'container-creation-failed',
      api.properties(
          **{
              'latest_files_gs_bucket':
                  'chromiumos-image-archive',
              'latest_files_gs_path':
                  '{target}-public',
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path='gs://chromiumos-manifest-versions/buildspecs/91/13818.0.0.xml'
                          ))),
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-public-release.{cros-version}',
              },
          }),
      api.build_menu.set_build_api_return(
          'try creating test service containers.create test service containers',
          'TestService/BuildTestServiceContainers', retcode=1),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-1234.56.0.gsutil write gs://chromiumos-image-archive/kukui-public/LATEST-1234.56.0'
      ),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-main.gsutil write gs://chromiumos-image-archive/kukui-public/LATEST-main'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'upload build report to GS.gsutil write build_report.json to GS',
          [
              'gs://chromeos-releases-test/kukui-public-main/R99-1234.56.0-101-8945511751514863184/build_report.json'
          ],
      ),
      build_target='kukui',
      builder='kukui-public-main',
      bucket='release',
  )
