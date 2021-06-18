# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building images for release."""

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'build_reporting',
    'cros_release',
    'test_util',
]

from google.protobuf.json_format import MessageToDict
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.recipes.chromeos.build_target import (BuildTargetProperties,
                                              ManifestLocation)


# TODO(crbug/1099259): Drop our properties.
# Our properties are processed and used by both the build_menu module, as well
# as various downstream dashboards and other consumers of buildbucket output
# properties.  They are not used directly within the recipe.
PROPERTIES = BuildTargetProperties

StepDetails = BuildReport.StepDetails


def RunSteps(api, properties):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE)

  with api.build_reporting.step_reporting(StepDetails.STEP_OVERALL):
    with api.build_menu.configure_builder() as config, \
        api.build_menu.setup_workspace_and_chroot(
          sync_to_manifest=properties.sync_to_manifest):
      return DoRunSteps(api, config, properties)


def DoRunSteps(api, config, _properties):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  packages = env_info.packages

  # Artifacts are frequently of use even if the build failed.  For example, it
  # is likely that the developer will want to see the ebuild logs from install
  # packages when that step fails, or even if build images fail afterward.
  failing_build = False
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      if api.build_menu.build_and_test_images(config, include_version=True):
        api.build_menu.upload_prebuilts(config)
  except StepFailure:
    failing_build = True
    raise
  finally:
    try:
      api.build_menu.upload_artifacts(config, failing_build=failing_build)
    except StepFailure:
      if not failing_build:
        raise

  api.cros_release.push_and_sign_images()
  api.cros_release.schedule_payload_generation()


def GenTests(api):
  manifest_url = 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  # Normal release build.
  yield api.build_menu.test(
      'release-build',
      api.properties(
          **{
              'sync_to_manifest':
                  MessageToDict(
                      ManifestLocation(
                          manifest_repo_url=manifest_url, branch='release',
                          manifest_file='releasespecs/91/13818.0.0.xml'))
          }), api.post_check(post_process.MustRun,
                             'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess), build_target='kukui-main',
      bucket='release')

  # Release build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1))

  # Release build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail', api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1))

  # Release build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return('upload artifacts',
                                          'ArtifactsService/Get', retcode=1))
