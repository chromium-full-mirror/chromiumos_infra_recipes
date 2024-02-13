# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating artifacts for Factory builders.

This recipe supports the workflow necessary to support factory builders."""

from google.protobuf.json_format import MessageToDict

from recipe_engine import post_process

from PB.chromiumos.build_report import BuildReport
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
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
    'signing',
    'src_state',
    'test_util',
]


PROPERTIES = BuildFactoryProperties

StepDetails = BuildReport.StepDetails


def RunSteps(api, properties: BuildFactoryProperties):
  api.cros_release.check_buildspec(fatal=not api.cros_infra_config.is_staging)
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_FACTORY,
                                     api.build_menu.build_target.name)

  with api.build_reporting.publish_to_gs():
    with api.build_reporting.status_reporting():
      with api.build_reporting.step_reporting(StepDetails.STEP_OVERALL,
                                              raise_on_failed_publish=True):
        with api.build_menu.configure_builder(
        ) as config, api.build_menu.setup_workspace_and_chroot():
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
                                          timeout_sec=60 * 60 * 12)
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

          _, instructions = api.cros_release.push_and_sign_images(
              config, api.build_menu.sysroot)

          if instructions and not api.build_menu.is_staging:
            with api.step.nest('get signed build metadata') as pres:
              metadata = api.signing.wait_for_signing(instructions)
              signed_build_metadata_list = (
                  api.signing.get_signed_build_metadata(metadata))
              # Publish any signed build metadata we have on the pubsub.
              api.build_reporting.publish_signed_build_metadata(
                  signed_build_metadata_list)
              api.signing.verify_signing_success(metadata, pres)
          else:
            with api.step.nest('skipping signing') as pres:
              if not instructions:
                pres.step_text = 'no signing instructions generated'
              if api.build_menu.is_staging:
                pres.step_text = 'signing is not run in staging'


def GenTests(api):
  manifest_url = 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  yield api.build_menu.test(
      'basic',
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
      # Make sure signing times out after 5 seconds to not explode test runs.
      api.signing.set_timeout(timeout=5),
      # Mock signing responses.
      api.signing.setup_mocks(board='corsola'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'get signed build metadata'),
      api.post_check(post_process.DoesNotRun,
                     'uploading factory artifacts for older branch'),
      builder='factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'staging',
      api.properties(
          **{
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
      api.post_check(post_process.MustRun, 'skipping signing'),
      api.post_check(
          post_process.StepTextContains,
          'skipping signing',
          ['signing is not run in staging'],
      ),
      api.post_process(post_process.DropExpectation),
      builder='staging-factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'no instructions',
      api.properties(
          **{
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
      api.cros_build_api.set_api_return(
          parent_step_name='push images',
          endpoint='ImageService/PushImage',
          data='{}',
          retcode=0,
      ),
      api.post_check(post_process.MustRun, 'skipping signing'),
      api.post_check(
          post_process.StepTextContains,
          'skipping signing',
          ['no signing instructions generated'],
      ),
      api.post_process(post_process.DropExpectation),
      builder='factory-corsola-15197.B-corsola',
  )

  yield api.build_menu.test(
      'version-before-14000',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url,
                              branch='main',
                              manifest_file='buildspecs/99/13928.55.0.xml',
                          )))
          }),
      api.step_data(
          'read chromeos version.read chromeos_version.sh',
          api.file.read_text(
              text_content=api.cros_version.chromeos_version_contents(
                  'R99-13928.55.0'))),
      # Make sure signing times out after 5 seconds to not explode test runs.
      api.signing.set_timeout(timeout=5),
      # Mock signing responses.
      api.signing.setup_mocks(board='corsola'),
      api.post_check(post_process.MustRun,
                     'uploading factory artifacts for older branch'),
      api.post_process(post_process.DropExpectation),
      builder='factory-corsola-15197.B-corsola',
  )
