# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building and testing a BuildTarget's packages."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'build_menu',
    'cros_infra_config',
    'cros_history',
    'cros_relevance',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.recipe_engine.result import RawResult


def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot() as is_relevant:
    if is_relevant:
      return DoRunSteps(api, config)
    else:
      return RawResult(status=common.SUCCESS,
                       summary_markdown='Build was not relevant.')


def DoRunSteps(api, config):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  if env_info.pointless:
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was pointless.')

  try:
    api.build_menu.bootstrap_sysroot(config)
  except StepFailure:
    api.build_menu.upload_artifacts(config, failing_build=True)
    raise

  packages = env_info.packages
  failing_build = False
  install_all_packages = _should_install_all_packages(api, config, packages)
  if api.cros_relevance.toolchain_cls_applied:
    config = api.cros_infra_config.get_builder_config(
        api.buildbucket.build.builder.builder.replace('-slim-cq', '-cq'))

  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages,
                                       force_all_deps=install_all_packages,
                                       include_rev_deps=True):
      api.build_menu.build_and_test_images(config)
  except StepFailure:
    failing_build = True
  finally:
    api.build_menu.upload_artifacts(config, failing_build=failing_build)
    if failing_build:
      raise


def _should_install_all_packages(api, config, packages):
  """Determine if all packages need to be installed.

  All packages need to be installed on retries or if Portage is unable to
  calculate the list of packages to install (b/188214351).

  Args:
    api (RecipeApi): See RunSteps documentation.
    config (BuilderConfig): The Builder Config for the build.
    packages (list[PackageInfo]): List of packages to install.

  Returns:
    Boolean whether the build needs to install all packages
      for the build target.
  """
  with api.step.nest('Determine which packages to build') as presentation:
    if api.cros_relevance.toolchain_cls_applied:
      presentation.step_text = 'Build all packages for toolchain CLs'
      presentation.properties[
          'subset_of_packages_built'] = 'ALL_FOR_TOOLCHAIN_CLS'
      return True
    if api.cros_history.is_retry(api.buildbucket.build):
      presentation.step_text = 'Build all packages on retries'
      presentation.properties['subset_of_packages_built'] = 'ALL_ON_RETRY'
      return True
    try:
      api.build_menu.install_packages(config, packages,
                                      name='Attempt to resolve package list',
                                      include_rev_deps=True, dryrun=True)
      presentation.step_text = 'Build only CL affected packages'
      presentation.properties['subset_of_packages_built'] = 'CL_AFFECTED'
      return False
    except StepFailure:
      presentation.step_text = 'Build all packages, failed to get package list'
      presentation.properties['subset_of_packages_built'] = 'ALL'
      presentation.status = 'WARNING'
      return True


def GenTests(api):

  # Slim CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'slim-cq-build',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess),
      cq=True,
      build_target='atlas-slim',
  )

  # This covers the Relevance check.
  yield api.build_menu.test(
      'prepare-for-build-pointless',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True, build_target='coral',
      input_properties=BuildTargetProperties(artifact_build=True),
      artifact_pointless=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test(
      'pointless-cq-build',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess),
      cq=True,
      build_target='atlas-slim',
      pointless=True,
  )

  # Install toolchain failure.
  yield api.build_menu.test(
      'install-toolchain-fail',
      api.post_check(post_process.DoesNotRun, 'install packages'),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install toolchain',
                                          'SysrootService/InstallToolchain',
                                          retcode=1),
      cq=True,
      build_target='atlas-slim',
  )

  # Failure to resolve package list.
  yield api.build_menu.test(
      'resolve-packages-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess),
      api.build_menu.set_build_api_return(
          'Determine which packages to build.Attempt to resolve package list',
          'SysrootService/InstallPackages', retcode=1),
      build_target='atlas-slim',
      cq=True,
  )

  # Retry.
  yield api.build_menu.test(
      'cq-retry',
      api.cros_history.is_retry(True),
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(
          post_process.DoesNotRun,
          'Determine which packages to build.Attempt to resolve package list'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess),
      build_target='atlas-slim',
      cq=True,
  )

  # Install packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      build_target='atlas-slim',
      cq=True,
  )

  # Ebuild test failure.
  yield api.build_menu.test(
      'ebuild-tests-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('run ebuild tests',
                                          'TestService/BuildTargetUnitTest',
                                          retcode=1),
      build_target='atlas-slim',
      cq=True,
  )

  # Toolchain CLs applied.
  yield api.build_menu.test(
      'toolchain-change',
      api.cros_relevance.toolchain_cls_applied(True),
      api.post_check(post_process.MustRun, 'install packages'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess),
      build_target='atlas-slim',
      cq=True,
  )
