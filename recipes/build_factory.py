# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating artifacts for Factory builders.

This recipe supports the workflow necessary to support factory builders."""

from typing import Optional
from google.protobuf.json_format import MessageToDict

from recipe_engine import post_process

from PB.chromiumos.build_report import BuildReport
from PB.chromiumos import common as common_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from PB.recipes.chromeos.build_factory import BuildFactoryProperties

DEPS = [
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'build_reporting',
    'cros_build_api',
    'cros_infra_config',
    'cros_release',
    'cros_version',
    'factory_util',
    'mutable_output',
    'signing',
    'signing_utils',
    'src_state',
    'test_util',
]


PROPERTIES = BuildFactoryProperties

StepDetails = BuildReport.StepDetails


def sign_locally(api, skip_signing: bool = False) -> None:
  """Sign the factory image using the local signing flow.

  Also uploads the signed artifact to the release bucket.
  """
  if api._test_data.enabled:  # pylint: disable=protected-access
    api.signing.test_api.signing_config_test_data = api._test_data.get(  # pylint: disable=protected-access
        'signing_config', api.signing.test_api.signing_config_test_data)
  release_sign_types = api.cros_release.sign_types
  channels = api.cros_release.channels
  if skip_signing:
    api.signing.stage_all_artifacts(channels)
    with api.step.nest('skipping signing') as pres:
      pres.step_text = 'build configured to skip signing'
  else:
    signed_image_response = api.signing.sign_artifacts(
        sign_types=release_sign_types, channels=channels, include_paygen=False)
    if signed_image_response:
      signed_build_list = api.signing_utils.signing_response_to_metadata(
          signed_image_response)
      api.build_reporting.publish_signed_build_metadata(signed_build_list)
  with api.step.nest('set up bucket metadata') as step:
    api.cros_release.emit_release_buckets(
        api.build_menu.sysroot.build_target.name, step)


def sign_on_legacy_signer(api, config: Optional[BuilderConfig]) -> None:
  """Sign the factory image using the legacy (remote) signing flow."""
  _, instructions = api.cros_release.push_and_sign_images(
      config, api.build_menu.sysroot)

  with api.step.nest('skipping signing') as pres:
    if not instructions:
      pres.step_text = 'no signing instructions generated'


def RunSteps(api, properties: BuildFactoryProperties):
  api.cros_release.check_buildspec(fatal=not api.cros_infra_config.is_staging)
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_FACTORY,
                                     api.build_menu.build_target.name)

  with (api.mutable_output.wrap(), api.build_reporting.publish_to_gs(),
        api.build_reporting.status_reporting(),
        api.build_reporting.step_reporting(StepDetails.STEP_OVERALL,
                                           raise_on_failed_publish=True),
        api.build_menu.configure_builder() as
        config, api.build_menu.setup_workspace_and_chroot()):
    # Publish branch to pubsub.
    branch = api.src_state.gitiles_commit.ref
    if branch.startswith('refs/heads/'):
      branch = branch[len('refs/heads/'):]
    api.build_reporting.publish_branch(branch)

    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    # After the sysroot is setup we have the package versions determined.
    api.build_reporting.publish_versions(api.build_menu.target_versions)

    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config, env_info.packages,
                                    timeout_sec=60 * 60 * 18)
    api.build_menu.build_and_test_images(
        config, include_version=True, is_official=True,
        build_images_timeout_sec=properties.build_images_timeout_sec)

    (
        uploaded_artifacts,
        artifact_dir,
    ) = api.build_menu.upload_artifacts(config)
    # TODO(b/316925119): Remove support when all factory versions>=13963.
    # Workaround to support branches cut before ArtifactsService.
    if not api.cros_version.version.is_after('14000.0.0'):
      api.factory_util.upload_factory(config, artifact_dir)
    if uploaded_artifacts:
      api.build_reporting.publish_build_artifacts(uploaded_artifacts,
                                                  artifact_dir)

    if api.signing.local_signing:
      sign_locally(api, properties.skip_signing)
    else:
      sign_on_legacy_signer(api, config)


def GenTests(api):
  manifest_url = 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  yield api.build_menu.test(
      'basic-legacy-signing',
      api.properties(
          BuildFactoryProperties(build_images_timeout_sec=3 * 60 * 60), **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url,
                              branch='main',
                              manifest_file='buildspecs/100/15197.0.0.xml',
                          )))
          }),
      api.step_data(
          'read chromeos version.read chromeos_version.sh',
          api.file.read_text(
              text_content=api.cros_version.chromeos_version_contents(
                  'R92-14929.158.0'))),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StepTextContains, 'push images',
                     ['push_and_sign_images is deprecated']),
      api.post_check(post_process.DoesNotRun, 'get signed build metadata'),
      api.post_check(post_process.DoesNotRun,
                     'uploading factory artifacts for older branch'),
      builder='factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'basic-local-signing',
      api.properties(
          **{
              'build_images_timeout_sec':
                  3 * 60 * 60,
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui'
                  }
              },
              '$chromeos/cros_release': {
                  'sign_types': [common_pb2.IMAGE_TYPE_FACTORY],
              },
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url,
                              branch='release',
                              manifest_file='buildspecs/100/15197.0.0.xml',
                          ))),
              '$chromeos/signing':
                  MessageToDict(SigningProperties(local_signing=True))
          }),
      api.step_data(
          'read chromeos version.read chromeos_version.sh',
          api.file.read_text(
              text_content=api.cros_version.chromeos_version_contents(
                  'R92-14929.158.0'))),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun,
                     'sign artifacts.download release artifacts'),
      api.post_check(post_process.DoesNotRun, 'push images'),
      api.post_check(post_process.DoesNotRun, 'get signed build metadata'),
      api.post_check(post_process.DoesNotRun,
                     'uploading factory artifacts for older branch'),
      builder='factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'staging',
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui'
                  }
              },
              '$chromeos/cros_release': {
                  'sign_types': [common_pb2.IMAGE_TYPE_FACTORY],
              },
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url,
                              branch='main',
                              manifest_file='buildspecs/100/15197.0.0.xml',
                          ))),
              '$chromeos/signing':
                  MessageToDict(SigningProperties(local_signing=True))
          }),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(
          post_process.LogContains,
          'sign artifacts.call BAPI.call chromite.api.ImageService/SignImage',
          'request', ['\"keyset\": \"DevPreMPKeys\"']),
      api.post_process(post_process.DropExpectation),
      builder='staging-factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'skip signing',
      api.properties(
          **{
              'skip_signing':
                  True,
              '$chromeos/signing':
                  MessageToDict(SigningProperties(local_signing=True)),
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url,
                              branch='main',
                              manifest_file='buildspecs/100/15197.0.0.xml',
                          )))
          }),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'download release artifacts'),
      api.post_check(post_process.DoesNotRun, 'push images'),
      api.post_check(post_process.DoesNotRun, 'get signed build metadata'),
      api.post_check(post_process.MustRun, 'skipping signing'),
      api.post_check(
          post_process.StepTextContains,
          'skipping signing',
          ['build configured to skip signing'],
      ),
      api.post_process(post_process.DropExpectation),
      builder='factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'version-before-14000',
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'kukui'
                  }
              },
              '$chromeos/cros_release': {
                  'sign_types': [common_pb2.IMAGE_TYPE_FACTORY],
              },
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url,
                              branch='main',
                              manifest_file='buildspecs/99/13928.55.0.xml',
                          ))),
              '$chromeos/signing':
                  MessageToDict(SigningProperties(local_signing=True))
          }),
      api.step_data(
          'read chromeos version.read chromeos_version.sh',
          api.file.read_text(
              text_content=api.cros_version.chromeos_version_contents(
                  'R99-13928.55.0'))),
      api.post_check(post_process.MustRun,
                     'uploading factory artifacts for older branch'),
      api.post_process(post_process.DropExpectation),
      builder='factory-corsola-15197.B-corsola',
  )
