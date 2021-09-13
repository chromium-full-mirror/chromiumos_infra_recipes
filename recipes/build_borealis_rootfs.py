# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a Borealis rootfs image."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'depot_tools/depot_tools',
    'build_menu',
    'cros_source',
]


def RunSteps(api):
  with api.build_menu.configure_builder(missing_ok=True), \
    api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api)


def DoRunSteps(api):
  chroot_path = api.cros_source.workspace_path
  borealis_path = chroot_path.join("src/platform/borealis")
  with api.context(cwd=borealis_path), api.depot_tools.on_path():
    # This recipe should only run on bots with docker pre-installed.  Abort
    # immediately if that is not the case.
    api.step("check docker install", ["docker", "help"])

    # Following the instructions at
    # src/platform/borealis/docs/build-and-deploy.md
    api.step("borealis_kernel", ["./tools/borealis_kernel.py"])
    api.step("borealis build_full.py", ["./tools/build_full.py", "--no-cache"])
    api.step("convert_docker_image", ["./tools/convert_docker_image.py"])
    api.step(
        "uprev_dlc.py --bucket_url=gs://chromeos-localmirror-private/borealis/",
        [
            "./tools/uprev_dlc.py",
            "--bucket_url=gs://chromeos-localmirror-private/borealis/"
        ])


def GenTests(api):
  yield api.test(
      'basic',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
  )
