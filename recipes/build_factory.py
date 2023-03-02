# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating artifacts for Factory builders.

This recipe supports the workflow necessary to support factory builders."""

from recipe_engine import post_process

DEPS = [
    'build_menu',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config, env_info.packages)
    api.build_menu.build_and_test_images(config, include_version=True)
    api.build_menu.upload_artifacts(config)


def GenTests(api):

  yield api.build_menu.test(
      'basic', api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      builder='factory-corsola-15197.B-corsola')
