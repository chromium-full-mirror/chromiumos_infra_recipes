# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for CQ."""

from typing import Generator
from typing import Optional

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromite.api.sysroot import InstallPackagesRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure
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
    'cros_build_api',
    'cros_infra_config',
    'deferrals',
    'easy',
    'gerrit',
    'future_utils',
    'src_state',
    'test_util',
]


GERRIT_HOST = 'chromium-review.googlesource.com'
CHANGE_NUM = 123456
PROJECT_NAME = 'chromiumos/overlays/chromiumos-overlay'

GERRIT_CHANGE = GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)
EBUILD_PATH = 'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild'


class ArtifactUploadState:
  """State about artifacts we've uploaded so far."""

  def __init__(self):
    # An optional list of artifacts that've been already uploaded.
    self.uploaded_artifacts = None
    # Set to True if all artifact uploading should be skipped.
    self.skip_upload = False

  def add(self, uploaded_artifacts: Optional['build_menu.UploadedArtifacts']):
    """Add uploaded artifacts."""
    if not self.uploaded_artifacts:
      self.uploaded_artifacts = uploaded_artifacts
    elif uploaded_artifacts:
      self.uploaded_artifacts = self.uploaded_artifacts.union(
          uploaded_artifacts)


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  api.easy.log_parent_step()

  api.bot_scaling.drop_cpu_cores(min_cpus_left=4, max_drop_ratio=.75)

  with api.build_menu.configure_builder() as config:
    # Prefer the type of the first deferred exception: if uploading artifacts
    # hits an InfraFailure after DoRunSteps has a StepFailure, it's likely the
    # DoRunSteps exception was the cause of the InfraFailure.
    with api.build_menu.setup_workspace(), \
        api.deferrals.raise_exceptions_at_end(prefer_first_type=True):
      upload_state = ArtifactUploadState()
      with api.deferrals.defer_exceptions([StepFailure]):
        is_relevant = api.build_menu.setup_chroot()
        if is_relevant:
          result = DoRunSteps(api, config, upload_state)
        else:
          upload_state.skip_upload = True
          result = RawResult(status=common.SUCCESS,
                             summary_markdown='Build was not relevant.')

      if not upload_state.skip_upload:
        # Defer InfraFailures as well here, since any exceptions raised in this
        # block might have been caused by StepFailures suppressed above.
        with api.deferrals.defer_exceptions([InfraFailure, StepFailure]):
          api.build_menu.upload_artifacts(
              config, name='final upload artifacts',
              previously_uploaded_artifacts=upload_state.uploaded_artifacts,
              ignore_breakpad_symbol_generation_errors=api.deferrals
              .are_exceptions_pending())
  return result


def DoRunSteps(api: RecipeApi, config: BuilderConfig,
               upload_state: ArtifactUploadState) -> Optional[RawResult]:
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()

  if env_info.pointless:
    # No artifacts are ever necessary from pointless builds.
    upload_state.skip_upload = True
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was pointless.')

  packages = env_info.packages

  api.build_menu.bootstrap_sysroot(config)
  if api.build_menu.install_packages(config, packages):
    # Create the test containers async.

    with api.step.nest('upload prebuilts'), api.context(infra_steps=True):
      upload = False
      with api.step.nest(
          'Check if the CQ uploads the prebuilts') as presentation:
        if (len(api.src_state.gerrit_changes) == 1 and
            api.chrome.is_chrome_pupr_atomic_uprev(
                api.src_state.gerrit_changes[0])):
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

    img_runner = api.future_utils.create_parallel_runner()
    img_runner.run_function_async(
        lambda cfg, _: api.build_menu.build_images(cfg, parallel_test=True),
        config)

    uploaded_artifacts, _ = api.build_menu.upload_symbols(config)
    upload_state.add(uploaded_artifacts)

    img_runner.wait_for_and_throw()

    # This Recipe support async unit testing by doing an initial upload of
    # artifacts after building images and before running unit tests. This allows
    # the orchestrator use the image artifacts without waiting for unit
    # testing to complete. A final upload will be done at the end of the
    # build, for any additional artifacts produced by unit testing, or if an
    # exception was thrown.
    uploaded_artifacts, _ = api.build_menu.upload_artifacts(
        config, previously_uploaded_artifacts=upload_state.uploaded_artifacts)
    upload_state.add(uploaded_artifacts)

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

    # Parallel steps run post image upload.
    post_upload_runner = api.future_utils.create_parallel_runner()
    # Ebuild unit tests.
    post_upload_runner.run_function_async(
        lambda cfg, _: api.build_menu.unit_tests(cfg), config)
    # Calculate and publish image and package size data.
    post_upload_runner.run_function_async(
        lambda cfg, _: api.build_menu.publish_image_size_data(cfg), config)
    # Image tests.
    post_upload_runner.run_function_async(
        lambda cfg, _: api.build_menu.test_images(cfg), config)
    post_upload_runner.wait_for_and_throw()

  return None


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  SECOND_GET_ARTIFACTS_DATA = '''{
    "artifacts": {
      "legacy": {"artifacts": [
        {"artifact_type": "EBUILD_LOGS", "paths": [
          {"location": 2, "path": "[CLEANUP]/artifacts_tmp_2/log.tar.gz"}
        ]}
      ]},
      "toolchain": {"artifacts": [{
        "artifact_type": "UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE",
        "paths": [{"location": 2, "path": "[CLEANUP]/artifacts_tmp_2/afdo"}]
      }]}
    }
  }'''
  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'cq-build',
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
      api.post_check(post_process.MustRun, 'build images'),
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
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
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
          # Why not test incrementals deletion too!
          'chromeos.sysroot_util.clean_incrementals',
      ],
  )

  # Test of "upload_prebuilts" flag.
  # CQ build on non-uprev CL, without uploading the prebuilts.
  yield api.build_menu.test(
      'upload-prebuilts-experiment-on-non-uprev-cq',
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.do upload'),
      cq=True,
      input_properties=api.test_util.build_menu_properties(
          override_prebuilts_config=BuilderConfig.Artifacts.PRIVATE),
      build_target='coral',
  )

  # This covers the Relevance check.
  yield api.build_menu.test(
      'prepare-for-build-pointless',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'upload symbols'),
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

  # The CQ should upload artifacts even if sysroot setup/update fails; some
  # artifacts (specifically toolchain ones) may still be usable in that case.
  yield api.build_menu.test(
      'setup-sysroot-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.build_menu.set_build_api_return('update sdk', 'SdkService/Update',
                                          retcode=1),
      cq=True,
      build_target='coral',
      status='FAILURE',
  )

  # This covers any staging-specific logic.
  yield api.build_menu.test(
      'staging-cq-build', api.post_check(post_process.MustRun, 'build images'),
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'final upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'), cq=True,
      build_target='staging-amd64-generic', pointless=False)

  yield api.build_menu.test(
      'publish-image-size-fails',
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
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
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
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

  # Build that uses Bazel for all its build steps.
  yield api.build_menu.test(
      'bazel',
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
      api.build_menu.assert_step_uses_bazel('install packages',
                                            'SysrootService/InstallPackages'),
      api.build_menu.assert_step_uses_bazel('build images',
                                            'ImageService/Create'),
      api.build_menu.assert_step_uses_bazel('run ebuild tests',
                                            'TestService/BuildTargetUnitTest'),
      cq=True,
      builder_name='amd64-generic-bazel-cq',
      build_target='amd64-generic',
  )

  # Bazel Lite build.
  yield api.build_menu.test(
      'bazel-lite',
      api.cros_build_api.set_api_return(
          'final upload artifacts.call artifacts service',
          'ArtifactsService/Get', SECOND_GET_ARTIFACTS_DATA),
      api.build_menu.assert_step_uses_bazel('install packages',
                                            'SysrootService/InstallPackages'),
      api.post_check(
          post_process.LogContains,
          'install packages.call chromite.api.SysrootService/InstallPackages',
          'request',
          [f'"bazelTargets": {InstallPackagesRequest.BazelTargets.LITE}']),
      cq=True,
      builder='amd64-generic-bazel-lite-cq',
      build_target='amd64-generic',
  )
