# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to test e2e coverage uploads."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'build_menu',
    'code_coverage',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot()
    api.build_menu.install_packages()
    api.build_menu.build_and_test_images()
    api.code_coverage.update_e2e_metadata('chromeos-image-archive',
                                          'buildername/id')


def GenTests(api):
  yield api.build_menu.test(
      'e2e-uploads-metadata',
      api.post_check(post_process.MustRun, 'upload e2e coverage metadata'),
  )
