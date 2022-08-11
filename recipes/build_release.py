# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building images for release."""

DEPS = [
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'bot_scaling',
    'build_menu',
    'build_reporting',
    'builder_metadata',
    'cros_build_api',
    'cros_infra_config',
    'cros_release',
    'cros_sdk',
    'cros_signing',
    'cros_source',
    'cros_tags',
    'debug_symbols',
    'easy',
]

from google.protobuf.json_format import MessageToDict, MessageToJson
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_engine.result import RawResult
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import (
    CrosArtifactsProperties)
from PB.recipes.chromeos.build_release import BuildReleaseProperties
from PB.recipe_modules.chromeos.cros_signing.cros_signing import \
  CrosSigningProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties, ManifestLocation)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = BuildReleaseProperties

StepDetails = BuildReport.StepDetails


def snoopy_report(api, report):
  """Report a step to snoopy.

  Args:
    api (recipe_api.RecipeApi): the RecipeApi object, used for step display.
    report (str): The build stage (e.g. start, compile) to report to snoopy.
  """
  # TODO(crbug/1274931) once snoopy is deemed "stable"
  # ensure the exception is properly handled
  with api.step.nest('snoopy: %s' % report) as step:
    try:
      api.bcid_reporter.report_stage(report)
    except StepFailure as e:
      step.status = api.step.FAILURE
      step.step_text = 'failed to report %s to snoopy: %s' % (report, e)


def RunSteps(api, properties):
  api.easy.log_parent_step()
  api.cros_release.set_output_properties()

  if api.cros_infra_config.is_staging:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=4, max_drop_ratio=.75)

  try:
    api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                       api.build_menu.build_target.name)
    snoopy_report(api, 'start')

    #TODO(b/181879769): CHROMEOS_OFFICIAL to be parameterized by config.
    with api.context(env=dict(CHROMEOS_OFFICIAL='1')):
      with api.build_reporting.publish_to_gs():
        with api.build_reporting.step_reporting(StepDetails.STEP_OVERALL,
                                                raise_on_failed_publish=True):
          with api.build_menu.configure_builder() as config, \
              api.build_menu.setup_workspace_and_chroot():
            return DoRunSteps(api, config, properties)
  finally:
    # If the parent build is cancelled, by default the child build will have an
    # INFRA_FAILURE status. Check if this build was cancelled because its
    # parent was cancelled, and set the status.
    parent = api.cros_tags.get_values('parent_buildbucket_id')
    if parent and api.runtime.in_global_shutdown:
      # pylint: disable=lost-exception
      return RawResult(
          status=common.CANCELED,
          summary_markdown='Parent orchestrator ({}) cancelled'.format(
              api.buildbucket.build_url(build_id=parent[0])))


def DoRunSteps(api, config, properties):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  # After the sysroot is setup we have the package versions determined.
  api.build_reporting.publish_versions(api.build_menu.target_versions)
  snoopy_report(api, 'fetch')

  failing_build_exception = None

  critical = ('1' if (config.general.critical and config.general.critical.value)
              else '0')
  api.easy.set_properties_step('set critical property', critical=critical)

  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, env_info.packages):
      # TODO(b/231739303): Make this step critical once cloud container build stablizes.
      with api.step.nest('try creating test service containers') as step:
        try:
          api.build_menu.create_containers(config)
        except StepFailure as sf:
          # For now only mark the step as failed. Do not fail the build.
          step.status = api.step.FAILURE
          step.step_summary_text = 'One or more test service containers failed to build.'

      with api.step.nest('determine build and model metadata'):
        # First look up builder metadata from build-api.
        builder_metadata = api.builder_metadata.look_up_builder_metadata()
        # Then fire off a pub/sub call with that builder meta.
        api.build_reporting.publish_build_target_and_model_metadata(
            api.cros_source.manifest_branch, builder_metadata)

        snoopy_report(api, 'compile')

      api.build_menu.build_images(config, include_version=True)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (there is value in uploading the artifact even in cases of
    # build failure for debug purposes).
    failing_build_exception = sf

  snoopy_report(api, 'upload')

  try:
    api.build_menu.upload_artifacts(config, report_to_spike=True)
  except StepFailure as sf:
    # If uploading artifacts threw an exception, surface that exception unless
    # build_and_test_images above threw an exception, in which case we want to
    # surface *that* exception for accuracy in reporting the build (and it's
    # likely that upload artifacts failed as a result of those previous issues).
    raise failing_build_exception or sf

  snoopy_report(api, 'upload-complete')

  with api.step.nest("publish toolchain metadata"):
    toolchain_info = api.cros_sdk.get_toolchain_info(
        api.build_menu.build_target.name)
    api.build_reporting.publish_toolchain_info(toolchain_info)

  # Finally, if there was an exception caught above in building the image, but
  # the upload succeeded, raise that exception.
  if failing_build_exception:
    raise failing_build_exception  # pylint: disable=raising-bad-type

  gs_image_dir, instructions = api.cros_release.push_and_sign_images(
      config, api.build_menu.sysroot)

  with api.build_reporting.step_reporting(StepDetails.STEP_DEBUG_SYMBOLS):
    with api.step.nest("upload debug symbols"):
      api.debug_symbols.upload_debug_symbols(gs_image_dir)

  with api.build_reporting.step_reporting(StepDetails.STEP_UNIT_TESTS):
    api.build_menu.unit_test_images(config)

  # Signing does not work in staging, so we shouldn't wait for it in that case.
  # We also can't sign anything if push_and_sign_images returned 0 instructions.
  # Otherwise, wait for signing to complete.
  if not api.cros_infra_config.is_staging and instructions:
    with api.step.nest('get signed build metadata'):
      # Wait for signing to complete. Note - "complete" does not mean "passed",
      # it means "signing returned a terminal state or timed out".
      metadata = api.cros_signing.wait_for_signing(instructions)
      # Get the signed build metadata now that it is complete.
      signed_build_metadata_list = api.cros_signing.get_signed_build_metadata(
          metadata)
      # Publish any signed build metadata we have on the pubsub.
      api.build_reporting.publish_signed_build_metadata(
          signed_build_metadata_list)

      # Now that we've published informational artifacts, we need to fail the
      # build if the outcome was anything other than "passed".
      api.cros_signing.verify_signing_success(metadata)
  elif not instructions:
    with api.step.nest('wait for signing') as pres:
      pres.step_text = 'no signing instructions generated'
      pres.status = api.m.step.FAILURE

  api.cros_release.run_payload_generation()

  if properties.latest_files_gs_bucket and properties.latest_files_gs_path:
    api.build_menu.publish_latest_files(properties.latest_files_gs_bucket,
                                        properties.latest_files_gs_path)


def GenTests(api):
  manifest_url = 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  successful_paygen_orch = build_pb2.Build(id=8922054662172514000,
                                           status='SUCCESS')
  successful_paygen_orch.output.properties['payloads'] = [
      MessageToJson(
          BuildReport.Payload(size=1337),
      )
  ]

  # Normal release build.
  yield api.build_menu.test(
      'release-build',
      api.properties(
          **{
              'latest_files_gs_bucket':
                  'chromeos-image-archive',
              'latest_files_gs_path':
                  '{target}-release',
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      "{staging?}{build-target}-release.{cros-version}",
              },
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
              '$chromeos/debug_symbols': {
                  'worker_count': 200,
                  'retry_quota': 1000,
                  'dryrun': False
              },
              '$chromeos/cros_signing':
                  MessageToDict(CrosSigningProperties(timeout=5))
          }),
      api.cros_signing.setup_mocks(),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-1234.56.0.gsutil write gs://chromeos-image-archive/kukui-release/LATEST-1234.56.0'
      ),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-main.gsutil write gs://chromeos-image-archive/kukui-release/LATEST-main'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'upload build report to GS.gsutil write build_report.json to GS',
          [
              'gs://chromeos-releases-test/kukui-release/R99-1234.56.0-101/build_report.json'
          ],
      ),
      api.post_process(post_process.PropertyEquals, 'critical', '1'),
      api.post_process(
          post_process.PropertyEquals, 'artifact_link',
          'gs://chromeos-releases-test/kukui-release/R99-1234.56.0-101'),
      api.post_check(post_process.StatusSuccess),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  # Normal release build.
  yield api.build_menu.test(
      'release-build-noncritical',
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve',
                  },
                  'container_version_format':
                      "{staging?}{build-target}-release.{cros-version}",
              },
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
              '$chromeos/debug_symbols': {
                  'worker_count': 200,
                  'retry_quota': 1000,
                  'dryrun': False
              },
              '$chromeos/cros_signing':
                  MessageToDict(CrosSigningProperties(timeout=5))
          }),
      api.cros_signing.setup_mocks(),
      api.post_process(post_process.PropertyEquals, 'critical', '0'),
      api.post_check(post_process.StatusSuccess),
      build_target='eve',
      builder='eve-kernelnext-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'release-no-instructions',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
              '$chromeos/debug_symbols': {
                  'worker_count': 200,
                  'retry_quota': 1000,
                  'dryrun': False
              },
              '$chromeos/cros_signing':
                  MessageToDict(CrosSigningProperties(timeout=5))
          }),
      api.cros_build_api.set_api_return(parent_step_name='push images',
                                        endpoint='ImageService/PushImage',
                                        data='{}', retcode=0),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'get signed build metadata'),
      api.post_check(post_process.MustRun, 'wait for signing'),
      api.post_check(post_process.StatusSuccess),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'release-build-staging',
      build_target='staging-eve',
      builder='staging-eve-release-main',
      bucket='release',
  )

  # Release build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
          }),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
  )

  # Release build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
          }),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
  )

  # Release build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
          }),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
  )

  yield api.build_menu.test(
      'paygen-failure',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
          }),
      api.cros_signing.setup_mocks(),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(
              id=8922054662172514000, status='FAILURE',
              summary_markdown='1 of 2 passed\n\nhttps://cr-buildbucket.appspot.com/build/8812345678901234567'
          )
      ], 'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.StatusFailure),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'parent-cancelled',
      api.runtime.global_shutdown_on_step(
          'configure builder.gitiles-fetch-ref'),
      api.post_check(
          post_process.ResultReason,
          'Parent orchestrator (https://cr-buildbucket.appspot.com/build/123) cancelled'
      ),
      api.post_process(post_process.StatusException),
      api.post_process(post_process.DropExpectation),
      tags=api.cros_tags.tags(parent_buildbucket_id='123'),
      cq=True,
      builder='kukui-cq',
      build_target='kukui',
  )

  # Release build with container creation failure.
  yield api.build_menu.test(
      'container-creation-fail',
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      "{staging?}{build-target}-release.{cros-version}",
              },
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
          }),
      api.cros_signing.setup_mocks(),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.build_menu.set_build_api_return(
          'try creating test service containers.create test service containers',
          'TestService/BuildTestServiceContainers', retcode=1),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
  )

  yield api.build_menu.test(
      'snoopy-fail',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
              '$chromeos/debug_symbols': {
                  'worker_count': 200,
                  'retry_quota': 1000,
                  'dryrun': False
              },
              '$chromeos/cros_signing':
                  MessageToDict(CrosSigningProperties(timeout=5))
          }),
      api.cros_signing.setup_mocks(),
      api.step_data('snoopy: start.report_stage', retcode=1),
      api.post_check(
          post_process.StepTextContains,
          'snoopy: start',
          ['failed to report start to snoopy'],
      ),
      api.post_check(post_process.StepFailure, 'snoopy: start'),
      api.post_check(post_process.StatusSuccess),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )
