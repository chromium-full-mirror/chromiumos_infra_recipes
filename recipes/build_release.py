# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building images for release."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'build_reporting',
    'builder_metadata',
    'cros_infra_config',
    'cros_release',
    'cros_sdk',
    'cros_source',
]

from google.protobuf.json_format import MessageToDict
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties, ManifestLocation)
from PB.recipes.chromeos.build_release import BuildReleaseProperties

StepDetails = BuildReport.StepDetails
PROPERTIES = BuildReleaseProperties


def launch_debug_symbols(api, gs_image_dir, worker_count, retry_quota,
                         staging=False, dryrun=False, **kwargs):
  """Asynchronously launch the upload debug symbols builder.

  Args:
    gs_image_dir (str): Google Storage directory where the sybmols are stored.
    worker_count (int): Maximum number of concurrent workers allowed to upload.
    retry_quota (int):  Maximum amount of upload retries allowed. This number is
                        for the entire builder run, not per symbol.
    staging (bool):     Is the run in a staging environment? This affects
                        which crash service we upload to.
    dryrun (bool):      Should the builder dryrun the upload?
    **kwargs:           Extra args for buildbucket.schedule_request().

  Returns:
    `Build` message describing the launched builder. See
    https://chromium.googlesource.com/infra/luci/luci-go/+/HEAD/buildbucket/proto/build.proto
    for more info.
  """
  gs_debug_image_location = '%s/debug_breakpad.tar.xz' % (gs_image_dir)

  bb_request = api.buildbucket.schedule_request(
      'staging-upload-debug-symbols' if staging else 'upload-debug-symbols',
      bucket='staging' if staging else 'release', properties={
          'cipd_ref': 'staging' if staging else 'prod',
          'gs_path': gs_debug_image_location,
          'worker_count': worker_count,
          'retry_quota': retry_quota,
          'staging': staging,
          'dryrun': dryrun
      }, **kwargs)

  return api.buildbucket.schedule([bb_request])[0]


def RunSteps(api, properties):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE)

  #TODO(b/181879769): CHROMEOS_OFFICIAL to be parameterized by config.
  with api.context(env=dict(CHROMEOS_OFFICIAL='1')):
    with api.build_reporting.step_reporting(StepDetails.STEP_OVERALL):
      with api.build_menu.configure_builder() as config, \
          api.build_menu.setup_workspace_and_chroot():
        return DoRunSteps(api, config, properties)


def DoRunSteps(api, config, properties):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  staging = api.cros_infra_config.is_staging
  # After the sysroot is setup we have the package versions determined.
  api.build_reporting.publish_versions(api.build_menu.target_versions)

  failing_build_exception = None
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, env_info.packages):
      with api.step.nest('determine build and model metadata') as presentation:
        # First look up builder metadata from build-api.
        builder_metadata = api.builder_metadata.look_up_builder_metadata()
        # Then fire off a pub/sub call with that builder meta.
        api.build_reporting.publish_build_target_and_model_metadata(
            api.cros_source.manifest_branch, builder_metadata)
      api.build_menu.build_and_test_images(config, include_version=True)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (there is value in uploading the artifact even in cases of
    # build failure for debug purposes).
    failing_build_exception = sf

  try:
    api.build_menu.upload_artifacts(config)
  except StepFailure as sf:
    # If uploading artifacts threw an exception, surface that exception unless
    # build_and_test_images above threw an exception, in which case we want to
    # surface *that* exception for accuracy in reporting the build (and it's
    # likely that upload artifacts failed as a result of those previous issues).
    raise failing_build_exception or sf

  # Finally, if there was an exception caught above in building the image, but
  # the upload succeeded, raise that exception.
  if failing_build_exception:
    raise failing_build_exception  # pylint: disable=raising-bad-type

  gs_image_dir, _ = api.cros_release.push_and_sign_images(
      config, api.build_menu.sysroot)

  with api.step.nest("schedule debug symbols upload") as presentation:
    # Launch the upload debug symbols builder
    debug_builder = launch_debug_symbols(api, gs_image_dir,
                                         properties.debug_symbols.worker_count,
                                         properties.debug_symbols.retry_quota,
                                         staging,
                                         properties.debug_symbols.dryrun)

    # Add link to builder in step
    builder_url = api.buildbucket.build_url(build_id=debug_builder.id)
    presentation.links["builder page"] = builder_url

  api.cros_release.schedule_payload_generation()


def GenTests(api):
  manifest_url = 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  # Normal release build.
  yield api.build_menu.test(
      'release-build',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='releasespecs/91/13818.0.0.xml'))),
              'debug_symbols': {
                  'worker_count': 200,
                  'retry_quota': 1000,
                  'dryrun': False
              }
          }),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      build_target='kukui-main',
      bucket='release',
  )

  # Release build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
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
      build_target='kukui-main',
  )

  # Release build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1),
      bucket='release',
      build_target='kukui-main',
  )

  # Release build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
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
      build_target='kukui-main',
  )

  yield api.build_menu.test(
      'paygen-failure',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='releasespecs/91/13818.0.0.xml'))),
          }),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.buildbucket.simulated_collect_output(
          [build_pb2.Build(id=8922054662172514001, status='FAILURE')],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.StatusFailure),
      build_target='kukui-main',
      bucket='release',
  )
