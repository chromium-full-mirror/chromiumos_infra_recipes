# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building public ChromiumOS images."""

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_source',
    'cros_tags',
    'debug_symbols',
    'easy',
]

from google.protobuf.json_format import MessageToDict
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.recipes.chromeos.build_chromiumos import BuildChromiumosProperties
from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties, ManifestLocation)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = BuildChromiumosProperties
StepDetails = BuildReport.StepDetails


def RunSteps(api, properties):
  api.easy.log_parent_step()

  with api.build_menu.configure_builder() as config, \
        api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, config, properties)


def DoRunSteps(api, config, properties):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()

  failing_build_exception = None
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, env_info.packages):
      api.build_menu.build_and_test_images(config, include_version=True)
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (there is value in uploading the artifact even in cases of
    # build failure for debug purposes).
    failing_build_exception = sf

  try:
    api.build_menu.upload_artifacts(config)

    if properties.latest_files_gs_bucket and properties.latest_files_gs_path:
      api.build_menu.publish_latest_files(properties.latest_files_gs_bucket,
                                          properties.latest_files_gs_path)
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


def GenTests(api):
  manifest_url = 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

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
                              manifest_repo_url=manifest_url, branch='release',
                              manifest_file='buildspecs/91/13818.0.0.xml'))),
          }),
      api.post_check(post_process.MustRun, 'sync to specified manifest'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-1234.56.0.gsutil write gs://chromiumos-image-archive/kukui-main-public/LATEST-1234.56.0'
      ),
      api.post_check(
          post_process.MustRun,
          'write LATEST files.write LATEST-main.gsutil write gs://chromiumos-image-archive/kukui-main-public/LATEST-main'
      ),
      api.post_check(post_process.StatusSuccess),
      build_target='kukui-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'public-build-staging',
      build_target='staging-eve',
      bucket='release',
  )

  # Public build with install-packages failure.
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

  # Public build with artifact bundling failure.
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

  # Public build with failures in install packages and bundle artifacts.
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
