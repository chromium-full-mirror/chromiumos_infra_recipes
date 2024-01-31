# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'build_menu',
    'code_coverage',
]



def RunSteps(api):
  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot()
    api.build_menu.install_packages()
    api.build_menu.build_and_test_images()
    api.code_coverage.process_coverage_data('[START_DIR]/coverage.tbz2', 'LCOV')


def GenTests(api):
  yield api.build_menu.test(
      'code-coverage-ensures-binaries',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.MustRun,
                     'upload code coverage data.ensure binaries'),
  )

  yield api.build_menu.test(
      'code-coverage-upload-failure',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.step_data(
          'upload code coverage data.ensure binaries.ensure_installed',
          retcode=2, stdout=api.raw_io.output('lol')),
      api.post_check(lambda check, steps: check(steps[
          'upload code coverage data'].output_properties[
              'process_coverage_data_failure'] is True)),
  )
