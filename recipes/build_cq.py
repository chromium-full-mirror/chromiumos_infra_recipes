# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for CQ."""

from typing import Generator
from typing import Optional

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/led',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_scaling',
    'build_menu',
    'chrome',
    'cros_infra_config',
    'easy',
    'gerrit',
    'future_utils',
    'src_state',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

GERRIT_HOST = 'chromium-review.googlesource.com'
CHANGE_NUM = 123456
PROJECT_NAME = 'chromiumos/overlays/chromiumos-overlay'

GERRIT_CHANGE = GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)
EBUILD_PATH = 'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild'


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  api.easy.log_parent_step()

  if api.cros_infra_config.is_staging and not api.led.run_id:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=4, max_drop_ratio=.75)

  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot() as is_relevant:
    if is_relevant:
      return DoRunSteps(api, config)
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was not relevant.')


def DoRunSteps(api: RecipeApi, config: BuilderConfig) -> Optional[RawResult]:
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()

  if env_info.pointless:
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was pointless.')

  packages = env_info.packages

  failing_build_exception = None
  uploaded_artifacts = None

  upload_prebuilts_from_cq = 'chromeos.build_cq.upload_prebuilts' in \
      api.buildbucket.build.input.experiments

  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      # Create the test containers async.

      with api.step.nest('upload prebuilts'), api.context(infra_steps=True):
        upload = False
        with api.step.nest(
            'Check if the CQ uploads the prebuilts') as presentation:
          if upload_prebuilts_from_cq:
            if len(api.src_state.gerrit_changes) == 1:
              if api.chrome.is_chrome_pupr_atomic_uprev(
                  api.src_state.gerrit_changes[0]):
                presentation.step_text = \
                    'decided to upload by chrome pupr change'
                upload = True
              else:
                presentation.step_text = \
                    'decided not to upload: not Chrome pupr atomic uprev'

        if upload:
          with api.step.nest('do upload'):
            api.build_menu.upload_chrome_prebuilts(config)

      test_containers_runner = api.future_utils.create_parallel_runner()
      test_containers_runner.run_function_async(
          lambda cfg, _: api.build_menu.create_containers(cfg), config)

      api.build_menu.build_images(config)

      # This Recipe support async unit testing by doing an initial upload of
      # artifacts after buing images and before running unit tests. This allows
      # the orchestrator use the image artifacts without waiting for unit
      # testing to complete. A final upload will be done at the end of the
      # build, for any additional artifacts produced by unit testing, or if an
      # exception was thrown.
      uploaded_artifacts, _ = api.build_menu.upload_artifacts(config)

      # Pause and throw if test containers failed to upload. Note that this
      # is done before the image_artifacts_uploaded property is set, as
      # containers need to be present for testing.
      test_containers_runner.wait_for_and_throw()

      # Set a property to indicate image artifacts are uploaded, so CQ
      # orchestrator can poll for this property.
      api.easy.set_properties_step(image_artifacts_uploaded=True)
      image_artifacts_uploaded_time = timestamp_pb2.Timestamp()
      image_artifacts_uploaded_time.FromDatetime(api.time.utcnow())
      api.easy.set_properties_step(
          image_artifacts_uploaded_time=json_format.MessageToDict(
              image_artifacts_uploaded_time))

      # We have no steps following unit_test_images, so we don't need to
      # check the return value.
      api.build_menu.unit_test_images(config)

      # Publish image and package sizes.
      # This method, as written, is expected to never raise exceptions.
      api.build_menu.publish_image_size_data(config)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (as stated above there is value in uploading the artifact even
    # in cases of build failure for debug purposes).
    failing_build_exception = sf

  # Always upload the artifacts, regardless of whether the above threw an
  # exception.
  try:
    api.build_menu.upload_artifacts(
        config, name='final upload artifacts',
        previously_uploaded_artifacts=uploaded_artifacts,
        ignore_breakpad_symbol_generation_errors=failing_build_exception
        is not None)
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
  return None


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'cq-build', api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'), cq=True,
      build_target='coral')

  # Build a change that has the ignore_breakpad_symbol_generation_errors set to
  # true in the builder config. Even though the build succeeds, the False passed
  # into api.build_menu.upload_artifacts should not override the True set in the
  # builder config.
  yield api.build_menu.test(
      'ignore_breakpad_symbol_generation_errors',
      api.post_check(
          post_process.LogContains,
          'final upload artifacts.call artifacts service.call chromite.api.ArtifactsService/Get',
          'request', ['"ignoreBreakpadSymbolGenerationErrors": true']),
      api.post_process(post_process.DropExpectation), cq=True,
      builder_name='amd64-generic-asan-cq', build_target='amd64-generic')

  # Test of "upload_prebuilts" flag.
  # CQ build on uprev CL, with uploading the prebuilts.
  yield api.build_menu.test(
      'upload-prebuilts-delete-incrementals-experiment',
      api.post_check(post_process.MustRun, 'upload prebuilts.do upload'),
      api.step_data(
          'upload prebuilts.Check if the CQ uploads the prebuilts.' + \
              'read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'upload prebuilts.Check if the CQ uploads the prebuilts',
          [GERRIT_CHANGE], {
              CHANGE_NUM: {
                  'project': PROJECT_NAME,
                  'branch': 'main',
                  'topic': 'chromeos-base/lacros-ash-atomic',
                  'files': {
                      EBUILD_PATH: {},
                  }
              },
          }, iteration=1),
      cq=True,
      input_properties=api.test_util.build_menu_properties(
          override_prebuilts_config=BuilderConfig.Artifacts.PUBLIC),
      build_target='amd64-generic',
      experiments=[
          # Flag to enable to upload the prebuilts
          'chromeos.build_cq.upload_prebuilts',
          # Why not test incrementals deletion too!
          'chromeos.sysroot_util.clean_incrementals',
      ],
  )

  # Test of "upload_prebuilts" flag.
  # CQ build on non-uprev CL, without uploading the prebuilts.
  yield api.build_menu.test(
      'upload-prebuilts-experiment-on-non-uprev-cq',
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.do upload'),
      cq=True,
      input_properties=api.test_util.build_menu_properties(
          override_prebuilts_config=BuilderConfig.Artifacts.PRIVATE),
      build_target='coral',
      experiments=[
          # Flag to enable to upload the prebuilts
          'chromeos.build_cq.upload_prebuilts',
      ],
  )

  # This covers the Relevance check.
  yield api.build_menu.test(
      'prepare-for-build-pointless',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'final upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'), cq=True,
      build_target='coral',
      input_properties=api.test_util.build_menu_properties(artifact_build=True),
      artifact_pointless=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test(
      'pointless-cq-build',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'final upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'), cq=True,
      build_target='staging-amd64-generic', pointless=True)

  # CQ build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.build_menu.set_build_api_return(
          'install packages', endpoint='SysrootService/InstallPackages',
          retcode=2,
          data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
      ),
      build_target='coral',
      cq=True,
      status='FAILURE',
  )

  # CQ build with initial upload artifact failure.
  yield api.build_menu.test(
      'initial-artifact-upload-bundle-fail',
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      cq=True,
      build_target='coral',
      status='INFRA_FAILURE',
  )

  # CQ build with final upload artifact failure.
  yield api.build_menu.test(
      'final-artifact-upload-bundle-fail',
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.build_menu.set_build_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', retcode=1),
      cq=True,
      build_target='coral',
      status='INFRA_FAILURE',
  )

  # CQ build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', retcode=1),
      cq=True,
      build_target='coral',
      status='FAILURE',
  )

  # This covers any staging-specific logic.
  yield api.build_menu.test(
      'staging-cq-build', api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'), cq=True,
      build_target='staging-amd64-generic', pointless=False)

  yield api.build_menu.test(
      'publish-image-size-fails',
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'collect image size data'),
      api.build_menu.set_build_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData', retcode=1),
      api.step_data(
          'call chromite.api.PackageService/GetTargetVersions.call build API script',
          api.m.file.read_raw(
              content='{"milestoneVersion":"110","platformVersion":"15255.0.0"}'
          )),
      api.step_data(
          'call chromite.api.PackageService/GetTargetVersions.read output file',
          api.m.file.read_raw(
              content='{"milestoneVersion":"110","platformVersion":"15255.0.0"}'
          )),
      cq=True,
      builder='amd64-generic-cq-img-pkg-sizes',
      build_target='amd64-generic',
      status='SUCCESS',
  )

  yield api.build_menu.test(
      'publish-image-size-succeeds',
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'collect image size data'),
      api.post_check(post_process.MustRun,
                     'collect image size data.add metadata from builder'),
      api.post_check(
          post_process.MustRun,
          'collect image size data.publish image size data.publish message'),
      api.step_data(
          'call chromite.api.PackageService/GetTargetVersions.call build API script',
          api.m.file.read_raw(
              content='{"milestoneVersion":"110","platformVersion":"15255.0.0"}'
          )),
      api.step_data(
          'call chromite.api.PackageService/GetTargetVersions.read output file',
          api.m.file.read_raw(
              content='{"milestoneVersion":"110","platformVersion":"15255.0.0"}'
          )),
      cq=True,
      builder='amd64-generic-cq-img-pkg-sizes',
      build_target='amd64-generic',
  )
