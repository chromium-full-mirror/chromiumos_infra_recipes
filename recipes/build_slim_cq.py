# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building and testing a BuildTarget's packages."""

DEPS = [
    'build_menu',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure


def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, config)


def DoRunSteps(api, config):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()
  if env_info.pointless:
    return

  try:
    api.build_menu.bootstrap_sysroot(config)
  except StepFailure:
    api.build_menu.upload_artifacts(config, failing_build=True)
    raise

  # TODO(b/189363718): Add logic such that we always install all packages on
  # retries.
  packages = env_info.packages
  install_all_packages = False
  failing_build = False
  try:
    api.build_menu.install_packages(config, packages,
                                    name='Attempt to resolve package list',
                                    include_rev_deps=True, dryrun=True)
  except StepFailure:
    install_all_packages = True

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
      api.build_menu.set_build_api_return('Attempt to resolve package list',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
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
