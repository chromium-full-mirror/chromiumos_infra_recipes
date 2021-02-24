# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'build_menu',
]

from recipe_engine import post_process


def RunSteps(api):
  with api.build_menu.configure_builder(), \
        api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()

    api.build_menu.bootstrap_sysroot_and_install_packages()
    api.build_menu.build_and_test_images()


def GenTests(api):
  yield api.build_menu.test(
      'code-coverage-build',
      api.post_check(post_process.MustRun, 'run ebuild tests.'
                     'process code coverage data'),
      builder='sarien-code-coverage-postsubmit', input_properties={
          '$chromeos/build_menu': dict(test_with_code_coverage=True),
          '$chromeos/code_coverage': dict(branch='refs/heads/main')
      })

  yield api.build_menu.test(
      'code-coverage-upload-failure',
      api.post_check(post_process.MustRun,
                     'run ebuild tests.process code coverage data'),
      api.step_data(
          'run ebuild tests.process code coverage data.upload coverage to chromium coverage.converting metadata for test coverage',
          retcode=1),
      api.post_check(lambda check, steps: check(steps[
          'run ebuild tests.process code coverage data'].output_properties[
              'process_coverage_data_failure'] == True)),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      builder='sarien-code-coverage-postsubmit', input_properties={
          '$chromeos/build_menu': dict(test_with_code_coverage=True),
          '$chromeos/code_coverage': dict(branch='refs/heads/main')
      })

  yield api.build_menu.test(
      'code-coverage-json-load-failure',
      api.post_check(post_process.MustRun,
                     'run ebuild tests.process code coverage data'),
      api.step_data(
          'run ebuild tests.process code coverage data.upload coverage to ZOSS.read coverage data from [CACHE]/cros_chroot/chroot/build/amd64-generic/build/coverage_data/coverage.json',
          retcode=1), builder='sarien-code-coverage-postsubmit',
      input_properties={
          '$chromeos/build_menu': dict(test_with_code_coverage=True),
          '$chromeos/code_coverage': dict(branch='refs/heads/main')
      })

  yield api.build_menu.test(
      'code-coverage-cq-not-supported',
      api.post_check(
          post_process.MustRun,
          'run ebuild tests.process code coverage data.upload coverage to ZOSS'
      ),
      # Old service should not run, It does not support gerrit.
      api.post_check(
          post_process.DoesNotRun,
          'run ebuild tests.process code coverage data.upload coverage to chromium coverage.converting metadata for test coverage'
      ),
      api.post_process(post_process.DropExpectation),
      cq=True,
      builder='sarien-code-coverage-cq',
      input_properties={
          '$chromeos/build_menu': dict(test_with_code_coverage=True),
          '$chromeos/code_coverage': dict(branch='refs/heads/main')
      })
