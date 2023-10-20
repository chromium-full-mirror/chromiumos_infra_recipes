# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for Android uprev.

The target Android package/version to uprev is specified via input properties,
for example:

"$chromeos/android": {
  "android_package": "android-vm-rvc",
  "android_version": "7444938"
}
"""

from typing import Generator

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipes.chromeos.android_uprev import AndroidUprevProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'android',
    'build_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = AndroidUprevProperties


def RunSteps(api: RecipeApi, properties: AndroidUprevProperties) -> None:
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, properties, config)


def DoRunSteps(api: RecipeApi, properties: AndroidUprevProperties,
               config: BuilderConfig) -> None:
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  packages = env_info.packages

  # Bootstrap sysroot, and skip the rest if android is not revved at all (unless
  # |always_build| is set).
  api.build_menu.bootstrap_sysroot(config)
  revved = api.android.uprev(api.build_menu.chroot, api.build_menu.sysroot,
                             properties.android_package,
                             properties.android_version,
                             properties.android_branch,
                             ignore_data_collector_artifacts=True)
  if not revved and not properties.always_build:
    return

  # Artifacts are frequently of use even if the build failed.  For example, it
  # is likely that the developer will want to see the ebuild logs from install
  # packages when that step fails, or even if build images fail afterward.
  # Thus, we track raise_upload_failure to avoid raising an upload failure if
  # the build has already failed. See also crbug/1086630.
  raise_upload_failure = True
  try:
    if api.build_menu.install_packages(config, packages):
      # We have no steps following build_images, so we don't need to
      # check the return value.
      api.build_menu.build_images(config)
      api.build_menu.create_containers(builder_config=config)
  except StepFailure:
    raise_upload_failure = False
    raise
  finally:
    try:
      api.build_menu.upload_artifacts(
          config,
          ignore_breakpad_symbol_generation_errors=not raise_upload_failure)
    except StepFailure:
      # TODO(crbug/1086630): We do not need to catch StepFailure here after
      # 2020-12-31.
      if raise_upload_failure:
        raise


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  uprev_props = api.properties(android_package='android-package',
                               android_branch='android-branch',
                               android_version='7123456')

  # Normal Android uprev build.
  yield api.build_menu.test(
      'basic',
      api.buildbucket.ci_build(builder='eve-android-uprev'),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-android-uprev.{cros-version}-{bbid}'
              }
          }),
      uprev_props,
      api.android.set_mark_stable_success(),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
  )

  # Android uprev build where uprev is not needed.
  yield api.build_menu.test(
      'android-not-revved',
      api.buildbucket.ci_build(builder='eve-android-uprev'),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-android-uprev.{cros-version}-{bbid}'
              }
          }),
      uprev_props,
      api.android.set_mark_stable_early_exit(),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
  )

  # Android uprev build where uprev is not needed yet |always_build| is set.
  yield api.build_menu.test(
      'always-build',
      api.buildbucket.ci_build(builder='eve-android-uprev'),
      api.properties(
          **{
              '$chromeos/cros_relevance': {
                  'force_postsubmit_relevance': True,
              },
              'always_build': True,
          }),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-android-uprev.{cros-version}-{bbid}'
              }
          }),
      uprev_props,
      api.android.set_mark_stable_early_exit(),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
  )

  # Android uprev build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.buildbucket.ci_build(builder='eve-android-uprev'),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-android-uprev.{cros-version}-{bbid}'
              }
          }),
      uprev_props,
      api.android.set_mark_stable_success(),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  # Android uprev build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail',
      api.buildbucket.ci_build(builder='eve-android-uprev'),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-android-uprev.{cros-version}-{bbid}'
              }
          }),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      uprev_props,
      api.android.set_mark_stable_success(),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  # Android uprev build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.buildbucket.ci_build(builder='eve-android-uprev'),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'eve'
                  },
                  'container_version_format':
                      '{staging?}{build-target}-android-uprev.{cros-version}-{bbid}'
              }
          }),
      uprev_props,
      api.android.set_mark_stable_success(),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
