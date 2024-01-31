# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating artifacts for Informational builders.

This recipe supports the workflow necessary to support asan, UBsan, and fuzzer
builder profiles."""

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'build_menu',
    'test_util',
]



def RunSteps(api: RecipeApi):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, env_info.packages):
      api.build_menu.upload_prebuilts(config)
      api.build_menu.create_containers(config)
    api.build_menu.build_and_test_images(config, include_version=True)
    api.build_menu.upload_artifacts(config)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  yield api.build_menu.test(
      'basic', api.post_check(post_process.DoesNotRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      builder='amd64-generic-fuzzer')

  yield api.build_menu.test(
      'upload prebuilts',
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      builder='amd64-generic-asan')
