# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating artifacts for Factory builders.

This recipe supports the workflow necessary to support factory builders."""
from google.protobuf.json_format import MessageToDict

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.cros_source import \
  CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'cros_release',
    'signing',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_release.check_buildspec(fatal=not api.cros_infra_config.is_staging)

  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config, env_info.packages)
    api.build_menu.build_and_test_images(config, include_version=True)
    api.build_menu.upload_artifacts(config)
    _, instructions = api.cros_release.push_and_sign_images(
        config, api.build_menu.sysroot)

    if instructions and not api.build_menu.is_staging:
      with api.step.nest('get signed build metadata') as pres:
        metadata = api.signing.wait_for_signing(instructions)
        api.signing.get_signed_build_metadata(metadata)
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
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='main',
                              manifest_file='buildspecs/100/15197.0.0.xml')))
          }),
      # Make sure signing times out after 5 seconds to not explode test runs.
      api.signing.set_timeout(timeout=5),
      # Mock signing responses.
      api.signing.mock_signing_successes([
          'gs://chromeos-releases/beta-channel/grunt/14493.0.0/ChromeOS-base-R100-14493.0.0-grunt.instructions.json',
          'gs://chromeos-releases/beta-channel/grunt/14493.0.0/ChromeOS-recovery-R100-14493.0.0-grunt.instructions.json'
      ], prestep='get signed build metadata.'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'get signed build metadata'),
      api.post_process(post_process.DropExpectation),
      builder='factory-corsola-15197.B-corsola')

  yield api.build_menu.test(
      'staging',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='main',
                              manifest_file='buildspecs/100/15197.0.0.xml')))
          }), api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'skipping signing'),
      api.post_check(post_process.StepTextContains, 'skipping signing',
                     ['signing is not run in staging']),
      api.post_process(post_process.DropExpectation),
      builder='staging-factory-corsola-15197.B-corsola')

  yield api.build_menu.test(
      'no instructions',
      api.properties(
          **{
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_repo_url=manifest_url, branch='main',
                              manifest_file='buildspecs/100/15197.0.0.xml')))
          }), api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.cros_build_api.set_api_return(parent_step_name='push images',
                                        endpoint='ImageService/PushImage',
                                        data='{}', retcode=0),
      api.post_check(post_process.MustRun, 'skipping signing'),
      api.post_check(post_process.StepTextContains, 'skipping signing',
                     ['no signing instructions generated']),
      api.post_process(post_process.DropExpectation),
      builder='factory-corsola-15197.B-corsola')
