# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building images for release."""
from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.checkpoint import RetryStep
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import \
  CrosArtifactsProperties
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.recipe_modules.chromeos.cros_release.cros_release import \
  CrosReleaseProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import \
  CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from PB.recipes.chromeos.build_release import BuildReleaseProperties
from RECIPE_MODULES.chromeos.checkpoint.api import STATUS_FAILED
from RECIPE_MODULES.chromeos.checkpoint.api import STATUS_SUCCESS
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/led',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'bot_scaling',
    'build_menu',
    'build_reporting',
    'builder_metadata',
    'checkpoint',
    'cros_build_api',
    'cros_infra_config',
    'cros_prebuilts',
    'cros_release',
    'cros_sdk',
    'cros_test_plan',
    'cros_try',
    'cros_source',
    'cros_tags',
    'debug_symbols',
    'dlc_utils',
    'easy',
    'failures',
    'mass_deploy',
    'signing',
    'src_state',
    'vmlab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildReleaseProperties

StepDetails = BuildReport.StepDetails

def RunSteps(api, properties):
  api.easy.log_parent_step()
  api.cros_try.check_try_version()
  api.checkpoint.register()
  if api.checkpoint.is_retry():
    api.build_reporting.init_report_from_previous_build()
  api.cros_release.check_buildspec(fatal=not api.cros_infra_config.is_staging)
  api.cros_release.validate_sign_types()
  api.cros_release.check_channel_override()
  api.cros_release.set_output_properties()
  # For dlc_utils.get_dlc_artifacts.
  api.path.mock_add_paths(
      api.path['cleanup'].join('artifacts_tmp_1/dlc/fake/dlc.img'))
  api.path.mock_add_paths(
      api.path['cleanup'].join('artifacts_tmp_1/dlc/fake2/dlc.img'))

  if api.cros_infra_config.is_staging and not api.led.run_id:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=16, max_drop_ratio=.50)

  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     api.build_menu.build_target.name)

  with api.failures.ignore_exceptions():
    with api.step.nest('checking attestation eligibility') as pres:
      # Config determines whether to report artifacts.
      if api.cros_infra_config.config.artifacts.attestation_eligible:
        api.bcid_reporter.report_stage('start')
        pres.step_text = f'{api.cros_infra_config.config.id.name} is attestation eligible'
      else:
        pres.step_text = f'{api.cros_infra_config.config.id.name} NOT attestation eligible'

  #TODO(b/181879769): CHROMEOS_OFFICIAL to be parameterized by config.
  with api.context(env={'CHROMEOS_OFFICIAL': '1'}):
    with api.build_reporting.publish_to_gs():
      with api.build_reporting.status_reporting():
        with api.build_reporting.step_reporting(StepDetails.STEP_OVERALL,
                                                raise_on_failed_publish=True):
          with api.build_menu.configure_builder(
            lookup_config_with_bucket=True,
          ) as config, \
              api.build_menu.setup_workspace_and_chroot(replace=True):
            branch = api.src_state.gitiles_commit.ref
            if branch.startswith('refs/heads/'):
              branch = branch[len('refs/heads/'):]
            api.build_reporting.publish_branch(branch)

            api.build_reporting.publish_channels(api.cros_release.channels)

            with api.step.nest('check that test config exists'):
              try:
                api.cros_test_plan.generate_target_test_requirements_config(
                    paygen=True)
              except Exception as e:
                raise StepFailure(
                    "testing config doesn't exist for this build target, see go/onboard-to-rubik"
                ) from e

            return DoRunSteps(api, config, properties)


def DoRunSteps(api, config, properties):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  # After the sysroot is setup we have the package versions determined.
  api.build_reporting.publish_versions(api.build_menu.target_versions)

  with api.failures.ignore_exceptions():
    if api.cros_infra_config.config.artifacts.attestation_eligible:
      api.bcid_reporter.report_stage('fetch')

  failing_build_exception = None

  critical = ('1' if (config.general.critical and config.general.critical.value)
              else '0')
  api.easy.set_properties_step('set critical property', critical=critical)

  api.build_menu.bootstrap_sysroot(config)

  with api.checkpoint.retry(RetryStep.STAGE_ARTIFACTS) as run_step:
    if run_step:
      try:
        if api.build_menu.install_packages(config, env_info.packages):
          # TODO(b/231739303): Make this step critical once cloud container build stablizes.
          with api.step.nest('try creating test service containers') as step:
            try:
              api.build_menu.create_containers(config)
            except StepFailure:
              # For now only mark the step as failed. Do not fail the build.
              step.status = api.step.FAILURE
              step.step_summary_text = 'One or more test service containers failed to build.'

          with api.failures.ignore_exceptions():
            if api.cros_infra_config.config.artifacts.attestation_eligible:
              api.bcid_reporter.report_stage('compile')

          api.build_menu.build_images(config, include_version=True)
          # Now that the image is built, we should have all metadata available.
          with api.step.nest('determine build and model metadata'):
            # First look up builder metadata from build-api.
            builder_metadata = api.builder_metadata.look_up_builder_metadata()
            # Then fire off a pub/sub call with that builder meta.
            api.build_reporting.publish_build_target_and_model_metadata(
                api.cros_source.manifest_branch, builder_metadata)

          # Publish image and package sizes.
          api.build_menu.publish_image_size_data(config)

          # We upload devinstall prebuilts at this stage instead of earlier on
          # because ImageService/Create (which is called in build_images above) is
          # the call that generates the package list that the devinstall prebuilts
          # call uses.
          api.build_menu.upload_devinstall_prebuilts(config)
      except StepFailure as sf:
        # If we catch an exception, swallow it and store it so the next steps can
        # still occur (there is value in uploading the artifact even in cases of
        # build failure for debug purposes).
        failing_build_exception = sf

      with api.failures.ignore_exceptions():
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('upload')

      try:
        uploaded_artifacts, artifact_dir = api.build_menu.upload_artifacts(
            config, report_to_spike=api.cros_infra_config.config.artifacts
            .attestation_eligible,
            ignore_breakpad_symbol_generation_errors=failing_build_exception
            is not None)
        if uploaded_artifacts:
          gs_image_dir = 'gs://{bucket}/{path}'.format(
              bucket=uploaded_artifacts.gs_bucket,
              path=uploaded_artifacts.gs_path)
          api.build_reporting.publish_build_artifacts(uploaded_artifacts,
                                                      artifact_dir)
          # Copy over the prebuilt DLCs to the upload bucket.
          prebuilt_dlcs = api.dlc_utils.copy_prebuilt_dlcs(
              uploaded_artifacts.gs_bucket,
              api.build_menu.sysroot or
              Sysroot(build_target=api.build_menu.build_target),
              api.build_menu.chroot,
              api.cros_infra_config.is_staging,
          )
          with api.step.nest('publish DLCs to pubsub'):
            dlc_artifacts = api.dlc_utils.get_dlc_artifacts(gs_image_dir)
            api.build_reporting.publish_dlc_artifacts(dlc_artifacts)
            # Publish prebuilt DLCs the new way (i.e. publish the DLC uri as
            # well as the hash for provenance).
            api.build_reporting.publish_dlc_artifacts(prebuilt_dlcs)
      except StepFailure as sf:
        # If uploading artifacts threw an exception, surface that exception unless
        # build_images above threw an exception, in which case we want to
        # surface *that* exception for accuracy in reporting the build (and it's
        # likely that upload artifacts failed as a result of those previous issues).
        raise failing_build_exception or sf

      with api.failures.ignore_exceptions():
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('upload-complete')

      # Trigger async image import for VM images. Exceptions are ignored as test
      # runners will also attempt to import.
      with api.failures.ignore_exceptions():
        if BuilderConfig.Artifacts.GCE_TARBALL in [
            t for artifacts in
            config.artifacts.artifacts_info.legacy.output_artifacts
            for t in artifacts.artifact_types
        ]:
          api.vmlab.import_image(
              name='import VM image',
              build_path=api.build_menu.artifacts_build_path(), wait=False)

      with api.step.nest('publish toolchain metadata'):
        toolchain_info = api.cros_sdk.get_toolchain_info(
            api.build_menu.build_target.name)
        api.build_reporting.publish_toolchain_info(toolchain_info)

      # Finally, if there was an exception caught above in building the image, but
      # the upload succeeded, raise that exception.
      if failing_build_exception:
        raise failing_build_exception  # pylint: disable=raising-bad-type
    else:
      api.easy.set_properties_step('set artifact_link property',
                                   artifact_link=api.checkpoint.artifact_link)

  # Eventually, signing will have its own checkpoint step, but for now
  # do it here. We do it before `PUSH_IMAGES` below because that is tightly
  # coupled with `COLLECT_SIGNING` below it as far as checkpoints is concerned.
  if api.signing.local_signing:
    release_sign_types = api.cros_release.sign_types
    channels = api.cros_release.channels
    api.signing.sign_artifacts(sign_types=release_sign_types, channels=channels)
    # TODO Publish any signed build metadata we have on the pubsub.
    # api.build_reporting.publish_signed_build_metadata()

  gs_image_dir = None
  instructions = None
  with api.checkpoint.retry(RetryStep.PUSH_IMAGES) as run_step:
    if not api.signing.local_signing:
      if run_step:
        gs_image_dir, instructions = api.cros_release.push_and_sign_images(
            config, api.build_menu.sysroot)
      else:
        gs_image_dir = api.checkpoint.artifact_link
        instructions = api.checkpoint.signing_instructions_uris
    else:
      with api.step.nest('set up bucket metadata') as step:
        gs_image_dir = api.cros_release.get_image_dir(config,
                                                      api.build_menu.sysroot,
                                                      step)
        api.cros_release.emit_release_buckets(
            api.build_menu.sysroot.build_target.name, step)
        instructions = []

  with api.checkpoint.retry(RetryStep.DEBUG_SYMBOLS) as run_step:
    if run_step:
      with api.build_reporting.step_reporting(StepDetails.STEP_DEBUG_SYMBOLS):
        with api.step.nest('upload debug symbols'):
          api.debug_symbols.upload_debug_symbols(gs_image_dir)

  # Launch unit tests asynchronously. Wait for results after paygen.
  def _run_and_report_unit_tests():
    """Helper function to run unit tests in a step_reporting wrapper."""
    with api.build_reporting.step_reporting(StepDetails.STEP_UNIT_TESTS):
      results = None
      try:
        results = api.build_menu.unit_test_images(config=config)
      except:
        # Add EBUILD_TESTS status to the retry_summary. b/265306388 for context.
        api.checkpoint.update_summary(RetryStep.EBUILD_TESTS, STATUS_FAILED)
        raise
      else:
        api.checkpoint.update_summary(RetryStep.EBUILD_TESTS, STATUS_SUCCESS)
      return results

  # TODO(b/262388770): Properly support ebuild tests within checkpoint.
  # For now, they're only run if the artifacts are built in the same run.
  unit_test_future = api.futures.spawn(lambda: True)
  if api.checkpoint.is_run_step(RetryStep.STAGE_ARTIFACTS):
    unit_test_future = api.futures.spawn(_run_and_report_unit_tests)

  exp = None
  try:
    with api.checkpoint.retry(RetryStep.COLLECT_SIGNING) as run_step:
      if (not api.signing.local_signing) and run_step:
        # Signing does not work in staging, so we shouldn't wait for it in that case.
        # We also can't sign anything if push_and_sign_images returned 0 instructions.
        # Otherwise, wait for signing to complete.
        if not api.cros_infra_config.is_staging and instructions:
          with api.step.nest('get signed build metadata') as pres:
            # Wait for signing to complete. Note - "complete" does not mean "passed",
            # it means "signing returned a terminal state or timed out".
            metadata = api.signing.wait_for_signing(instructions)
            # Get the signed build metadata now that it is complete.
            signed_build_metadata_list = api.signing.get_signed_build_metadata(
                metadata)
            # Publish any signed build metadata we have on the pubsub.
            api.build_reporting.publish_signed_build_metadata(
                signed_build_metadata_list)

            # Now that we've published informational artifacts, we need to fail the
            # build if the outcome was anything other than "passed".
            api.signing.verify_signing_success(metadata, pres)

          # If building mass deploy image, trigger that now, but don't wait for it
          # to finish.
          if properties.build_mass_deploy_image:
            api.mass_deploy.run_mass_deploy_generation(metadata)

        elif not instructions:
          with api.step.nest('skipping signing') as pres:
            pres.step_text = (
                'no signing instructions generated'
                if api.checkpoint.is_run_step(RetryStep.PUSH_IMAGES) else
                'no signing instructions retrieved from original build')

    with api.checkpoint.retry(RetryStep.PAYGEN) as run_step:
      if run_step:
        # With signing complete, we can start payload generation (only if there were
        # signed images generated). We _do_ want this in staging.
        if not properties.skip_paygen and (instructions or
                                           api.signing.local_signing):
          api.cros_release.run_payload_generation(
              override_qs_account=properties.override_qs_account,
              use_split_paygen=properties.use_split_paygen)
        else:
          with api.step.nest('skipping payloads') as pres:
            if properties.skip_paygen:
              pres.step_text = 'property `skip_paygen` was set'
            else:
              pres.step_text = 'no payloads generated since no signed images'

  except Exception as e:  #pylint: disable=broad-except
    # Defer any failures until after ebuild tests.
    # Failed steps within the try block will still marked appropriately.
    exp = e

  # Wait for unit tests to finish.
  unit_test_future.result()

  # Defer raising any exception that occurred while ebuild tests are running
  # until after we've collected ebuild tests.
  # We don't currently have means of retrying ebuild tests -- if they fail,
  # the build is doomed. As such, we want to a) make a best effort at finishing
  # tests and b) make it clear to users that the ebuild failure is the critical
  # one.
  if exp:
    raise exp

  if properties.latest_files_gs_bucket and properties.latest_files_gs_path:
    api.build_menu.publish_latest_files(properties.latest_files_gs_bucket,
                                        properties.latest_files_gs_path)

  # Mark whether the suite_scheduling query for firmware should find this.
  # Should happen for all release builds, but not in staging.
  api.easy.set_properties_step(
      suite_scheduling=str(not api.cros_infra_config.is_staging))


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
              'override_qs_account':
                  'release_high_prio',
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-release.{cros-version}',
              },
              '$chromeos/checkpoint': {
                  'force_retry_summary': True,
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
              '$chromeos/signing':
                  MessageToDict(SigningProperties(timeout=5)),
              '$chromeos/cros_release': {
                  'channels': [4, 3],
              }
          }),
      api.signing.setup_mocks(),
      api.step_data(
          'publish DLCs to pubsub.Hash DLCs.Find DLCs.gsutil ls dlc',
          stdout=api.raw_io.output_text('''
gs://chromeos-releases-test/kukui-release/R99-1234.56.0-101/dlc/fake/dlc.img
gs://chromeos-releases-test/kukui-release/R99-1234.56.0-101/dlc/fake2/dlc.img
      '''), retcode=0),
      api.post_check(post_process.LogContains,
                     'publish DLCs to pubsub.build status pubsub update',
                     'message', ['dlcArtifactDetails']),
      api.post_check(
          post_process.LogContains,
          'publish DLCs to pubsub.build status pubsub update', 'message', [
              '"gcs\": \"gs://chromeos-releases-test/kukui-release/R99-1234.56.0-101/dlc/fake/dlc.img\"'
          ]),
      api.post_check(post_process.LogContains,
                     'publish DLCs to pubsub.build status pubsub update',
                     'message', ['"sha256\": \"deadbeef\"']),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'request', ['"override_qs_account": "release_high_prio"']),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-1234.56.0.gsutil write gs://chromeos-image-archive/kukui-release/LATEST-1234.56.0'
      ),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-main.gsutil write gs://chromeos-image-archive/kukui-release/LATEST-main'
      ),
      api.post_check(post_process.MustRun, 'snoop: report_stage'),
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
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SUCCESS',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SUCCESS',
              RetryStep.Name(RetryStep.DEBUG_SYMBOLS): 'SUCCESS',
              RetryStep.Name(RetryStep.EBUILD_TESTS): 'SUCCESS',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS',
              RetryStep.Name(RetryStep.PAYGEN): 'SUCCESS'
          }),
      api.post_check(post_process.DoesNotRun, 'overriding release channels'),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  # Normal release build with local signing.
  yield api.build_menu.test(
      'release-build-local-signing',
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
                      '{staging?}{build-target}-release.{cros-version}',
              },
              '$chromeos/checkpoint': {
                  'force_retry_summary': True,
              },
              '$chromeos/cros_artifacts':
                  CrosArtifactsProperties(
                      gs_upload_path='{target}-release/{version}'),
              '$chromeos/cros_release': {
                  'sign_types': [common_pb2.IMAGE_TYPE_BASE],
              },
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
              '$chromeos/signing':
                  MessageToDict(SigningProperties(local_signing=True))
          }),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun,
                     'sign artifacts.download release artifacts'),
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
      api.post_check(post_process.DoesNotRun, 'push images'),
      api.post_check(post_process.DoesNotRun, 'get signed build metadata'),
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SUCCESS',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SUCCESS',
              RetryStep.Name(RetryStep.DEBUG_SYMBOLS): 'SUCCESS',
              RetryStep.Name(RetryStep.EBUILD_TESTS): 'SUCCESS',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS',
              RetryStep.Name(RetryStep.PAYGEN): 'SUCCESS'
          }),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  # Normal release build with VM board.
  yield api.build_menu.test(
      'release-build-vm',
      api.properties(
          **{
              'latest_files_gs_bucket':
                  'chromeos-image-archive',
              'latest_files_gs_path':
                  '{target}-release',
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'betty-arc-r',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-release.{cros-version}',
              },
              '$chromeos/checkpoint': {
                  'force_retry_summary': True,
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
              '$chromeos/signing':
                  MessageToDict(SigningProperties(timeout=5))
          }),
      api.signing.setup_mocks(),
      api.post_check(post_process.MustRun, 'import VM image'),
      build_target='betty-arc-r',
      builder='betty-arc-r-release-main',
      bucket='release',
  )

  # Release build missing test config should exit early.
  yield api.build_menu.test(
      'no-test-config',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
          }),
      api.step_data(
          'check that test config exists.generate target test requirements.generate_test_config',
          retcode=1),
      api.post_check(post_process.StepFailure, 'check that test config exists'),
      build_target='eve',
      builder='eve-kernelnext-release-main',
      bucket='release',
      status='FAILURE',
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
                      '{staging?}{build-target}-release.{cros-version}',
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
              '$chromeos/signing':
                  MessageToDict(SigningProperties(timeout=5))
          }),
      api.signing.setup_mocks(),
      api.post_process(post_process.PropertyEquals, 'critical', '0'),
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
              '$chromeos/signing':
                  MessageToDict(SigningProperties(timeout=5))
          }),
      api.cros_build_api.set_api_return(parent_step_name='push images',
                                        endpoint='ImageService/PushImage',
                                        data='{}', retcode=0),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun,
                     'determine build and model metadata'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'get signed build metadata'),
      api.post_check(post_process.MustRun, 'skipping signing'),
      api.post_check(post_process.DoesNotRun, 'generate payloads'),
      api.post_check(post_process.MustRun, 'skipping payloads'),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'release-build-staging',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
          }),
      build_target='staging-eve',
      builder='staging-eve-release-main',
      bucket='staging',
  )

  yield api.build_menu.test(
      'release-build-no-buildspec',
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation), build_target='eve',
      builder='eve-release-main', bucket='release', status='FAILURE')

  def build_result(bbid, buildspec):
    build = build_pb2.Build(id=bbid)
    build.input.properties['$chromeos/cros_source'] = {
        'syncToManifest': {
            'manifestGsPath': buildspec,
        }
    }
    return build

  # non-fatal so should proceed despite the step failure.
  yield api.build_menu.test(
      'release-build-staging-check-buildspec',
      api.properties(
          **{
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  },
              },
          }),
      api.buildbucket.simulated_search_results([
          build_result(
              123,
              'gs://chromeos-manifest-versions/buildspecs/114/15408.0.0.xml'),
          build_result(
              124,
              'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml'),
      ], step_name='check buildspec.check for previous builds.buildbucket.search'
                                              ),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      build_target='staging-eve',
      builder='staging-eve-release-main',
      bucket='staging',
  )

  # Release build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
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
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun,
                     'upload artifacts.publish artifacts'),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
      status='FAILURE',
  )

  # Release build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
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
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
      status='INFRA_FAILURE',
  )

  # Release build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
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
      builder='kukui-release-main',
      build_target='kukui',
      status='FAILURE',
  )

  # Release build with failure publishing image/package size data.
  yield api.build_menu.test(
      'publish-image-size-fail',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
          }),
      api.signing.setup_mocks(),
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
      bucket='release',
      builder='eve-release-publish-img-pkg-sizes',
      build_target='eve',
  )

  yield api.build_menu.test(
      'ebuild-tests-failure',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'force_retry_summary': True,
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
          }),
      api.signing.setup_mocks(),
      api.cros_build_api.set_api_return(
          'run ebuild tests',
          endpoint='TestService/BuildTargetUnitTest',
          retcode=1,
      ),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.StepFailure, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SUCCESS',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SUCCESS',
              RetryStep.Name(RetryStep.DEBUG_SYMBOLS): 'SUCCESS',
              RetryStep.Name(RetryStep.EBUILD_TESTS): 'FAILED',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS',
              RetryStep.Name(RetryStep.PAYGEN): 'SUCCESS'
          }),
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
      status='FAILURE',
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
      api.signing.setup_mocks(),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(
              id=8922054662172514000, status='FAILURE',
              summary_markdown='1 of 2 passed\n\nhttps://cr-buildbucket.appspot.com/build/8812345678901234567'
          )
      ], 'generate payloads.running paygen orchestrator.collect'),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
      status='FAILURE',
  )

  yield api.build_menu.test(
      'skip-paygen',
      api.properties(
          **{
              'skip_paygen':
                  True,
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
      api.signing.setup_mocks(),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'generate payloads'),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
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
                      '{staging?}{build-target}-release.{cros-version}',
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
          }),
      api.signing.setup_mocks(),
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
      bucket='release',
      builder='kukui-release-main',
      build_target='kukui',
  )

  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.input.properties['recipe'] = 'build_release'
  original_build.output.properties[
      'artifact_link'] = 'gs://chromeos-image-archive/kukui-release-main/R91-13818.0.0'
  original_build.output.properties[
      'signing_instructions_uris'] = api.cros_build_api.INSTRUCTIONS
  original_build.output.properties[
      'build_report_uri'] = 'gs://foo/build_report.json'

  # Retry release build.
  yield api.build_menu.test(
      'release-build-signing-retry',
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
                      '{staging?}{build-target}-release.{cros-version}',
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
              '$chromeos/signing':
                  MessageToDict(SigningProperties(timeout=5)),
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.DEBUG_SYMBOLS]
                  }
              }
          }),
      api.step_data(
          'read build report from previous build.gsutil cat',
          stdout=api.raw_io.output_text('{}'),
      ),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.signing.setup_mocks(),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) not retrying STAGE_ARTIFACTS'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun,
                     'determine build and model metadata'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) not retrying PUSH_IMAGES'),
      api.post_process(post_process.PropertyEquals, 'critical', '1'),
      api.post_process(
          post_process.PropertyEquals, 'artifact_link',
          'gs://chromeos-image-archive/kukui-release-main/R91-13818.0.0'),
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SKIPPED',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SKIPPED',
              RetryStep.Name(RetryStep.DEBUG_SYMBOLS): 'SUCCESS',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS',
              RetryStep.Name(RetryStep.PAYGEN): 'SUCCESS'
          }),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  # Release build with mass deploy.
  yield api.build_menu.test(
      'release-build-mass-deploy',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
              '$chromeos/signing':
                  MessageToDict(SigningProperties(timeout=5)),
              'build_mass_deploy_image':
                  True,
          }),
      api.signing.setup_mocks(channel='stable'),
      # This needs some work. signing needs to be mocked differently.
      api.post_check(post_process.MustRun, 'get signed build metadata'),
      api.post_check(post_process.MustRun, 'generate mass deploy builds'),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'channel-override',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      should_override_release_channels=True,
                      override_release_channels=['2', '3']),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
          }),
      api.signing.setup_mocks(),
      api.post_check(post_process.MustRun, 'overriding release channels'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  # TODO(b/305046854): Temporarily allow MPA bot pool overrides.
  yield api.build_menu.test(
      'release-mpa',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
              '$chromeos/cros_release':
                  MessageToDict(CrosReleaseProperties(paygen_mpa=True))
          }),
      api.signing.setup_mocks(),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'request', ['"builder": "paygen-orchestrator-mpa"']),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )
